# train_model.py
# ==============
# Addestramento supervisionato (Behavioural Cloning) per TORCS.
# Versione Ottimizzata: Rete snella, AMP, Esportazione End-to-End JIT.

import os
import sys
import json
import glob
import getopt
import random
import time
import numpy as np

try:
    import torch
    # torch.nn contiene i moduli base per costruire reti neurali (es. layer lineari, attivazioni, loss functions)
    import torch.nn as nn
    # torch.optim contiene gli algoritmi di ottimizzazione (es. AdamW, SGD) per aggiornare i pesi della rete
    import torch.optim as optim
    # Dataset e DataLoader servono per gestire e caricare i dati a batch durante il training
    from torch.utils.data import Dataset, DataLoader, random_split
except ImportError:
    print("[ERRORE] PyTorch non trovato.")
    sys.exit(1)

try:
    # StandardScaler rimuove la media e scala i dati in modo che abbiano varianza unitaria
    from sklearn.preprocessing import StandardScaler
    # PCA (Principal Component Analysis) riduce la dimensionalità dei dati mantenendo la maggior parte della varianza
    from sklearn.decomposition import PCA
except ImportError:
    print("[ERRORE] scikit-learn non trovato.")
    sys.exit(1)


#  ----------- COSTANTI E PARAMETRI -----------

# Fattori di scala per normalizzare i sensori prima della PCA
RAW_SCALE = np.array(
    [3.14159, 300.0, 100.0, 1.0, 10000.0] + [200.0] * 19,
    dtype=np.float32,
)

N_RAW_FEATURES = 24


#  ----------- CARICAMENTO E PRE-PROCESSING DATI -----------

def _iter_records(filepath: str):

    # Leggo riga per riga i log JSONL per estrarre sensori e comandi.
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and "steps" in data:
            for step in data["steps"]:
                sensors = step.get("state", step.get("sensors", {}))
                actions = step.get("actions", step.get("action", {}))
                if isinstance(sensors, dict) and isinstance(actions, dict):
                    yield sensors, actions
            return
    except (json.JSONDecodeError, UnicodeDecodeError, MemoryError):
        pass

    # Gestione JSONL puro iterato riga per riga
    with open(filepath, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line: continue
            try: 
                rec = json.loads(line)
            except json.JSONDecodeError: 
                continue
                
            if not isinstance(rec, dict): continue
            
            sensors = rec.get("sensors", {})
            actions = rec.get("actions", {})
            
            if isinstance(sensors, dict) and isinstance(actions, dict):
                yield sensors, actions

def load_logs(logs_dir: str, min_speed: float = 5.0):

    # Carico tutti i log di telemetria, scartando i dati sotto una certa velocità o corrotti.
    files = sorted(glob.glob(os.path.join(logs_dir, "*.jsonl")) + glob.glob(os.path.join(logs_dir, "*.json")))
    if not files:
        print(f"[ERRORE] Nessun log in '{logs_dir}'")
        sys.exit(1)

    X_list, y_list, skipped, total = [], [], 0, 0

    for filepath in files:
        for sensors, actions in _iter_records(filepath):
            speed = sensors.get("speedX", 0.0)
            
            # Scarto frame a bassa velocità (auto ferma o in testacoda lento)
            if abs(speed) < min_speed:
                skipped += 1
                continue

            track = sensors.get("track", [])
            if len(track) != 19:
                skipped += 1
                continue

            # Strutturo l'input grezzo (Sensori)
            x_raw = np.array([
                sensors.get("angle", 0.0), sensors.get("speedX", 0.0),
                sensors.get("speedY", 0.0), sensors.get("trackPos", 0.0),
                sensors.get("rpm", 0.0),
            ] + [float(v) for v in track], dtype=np.float32)

            x_pre = np.clip(x_raw / RAW_SCALE, -3.0, 3.0)
            
            # Strutturo i Comandi. La marcia viene normalizzata.
            gear_norm = float(actions.get("gear", 1)) / 6.0

            y_raw = np.array([
                float(actions.get("steer", 0.0)), float(actions.get("accel", 0.0)),
                float(actions.get("brake", 0.0)), gear_norm,
            ], dtype=np.float32)

            X_list.append(x_pre)
            y_list.append(y_raw)
            total += 1

    print(f"[DATI] Step validi: {total:,} | Scartati: {skipped:,}")
    if total == 0: sys.exit(1)
    
    return np.stack(X_list), np.stack(y_list)

def fit_scaler_pca(X_raw: np.ndarray, pca_components, model_dir: str):

    # Applico Standardizzazione e PCA per ridurre la dimensionalità degli input.
    # Questo riduce il rumore.
    print("\n[PRE-PROC] Fitting StandardScaler ...")
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_raw)

    print(f"[PRE-PROC] Fitting PCA ({pca_components}) ...")
    pca = PCA(n_components=pca_components, random_state=0)
    X_pca = pca.fit_transform(X_scaled).astype(np.float32)


    return X_pca, pca.n_components_, scaler, pca


#  ----------- MODELLO NEURALE -----------

class TorcsDataset(Dataset):
    
    # Wrapper per il dataset PyTorch. Consente a DataLoader di iterare sui batch (Raggruppamenti di dati).
    def __init__(self, X, y):
        self.X, self.y = torch.from_numpy(X), torch.from_numpy(y)
        
    def __len__(self): 
        return len(self.X)
        
    def __getitem__(self, idx): 
        return self.X[idx], self.y[idx]



class TorcsDriverNet(nn.Module):

    # Architettura della Rete Neurale Core (Post-PCA). 
    # Eredita da nn.Module che è la classe base di PyTorch per i modelli.
    def __init__(self, input_dim: int, hidden: int = 128, dropout: float = 0.1):
        super().__init__()
        
        # nn.Sequential: Esegue i layer tra parentesi in cascata (Collegamenti fra i neuroni).

        # nn.Linear: Layer completamente connesso (y = xA^T + b: x = dati in ingresso, A = pesi, b = bias) e serve
        # per mappare le feature in uno spazio a dimensionalità maggiore, in questo caso hidden = 128.
        # Avremo quindi 128 neuroni di ingresso collegati a 128 neuroni d'uscita mediante 128 * 128 collegamenti pesati.

        # nn.BatchNorm1d: Normalizza gli output del layer precedente per velocizzare e stabilizzare il training.

        # nn.ReLU: Funzione di attivazione che azzera i valori negativi per introdurre non linearità.
        # La non linearità permette alla rete di imparare relazioni complesse tra i dati, specializzando
        # i singoli neuroni a riconoscere pattern specifici (es. curve strette vs rettilinei).

        self.encoder = nn.Sequential(
            nn.Linear(input_dim, hidden), 
            nn.BatchNorm1d(hidden), 
            nn.ReLU(inplace=True)
        )
        
        # Blocchi Residuali: prevengono la perdita di informazione nei layer profondi (vanishing gradient).
        self.res_blocks = nn.ModuleList([
            nn.Sequential(
                nn.Linear(hidden, hidden), 
                nn.BatchNorm1d(hidden), 
                nn.ReLU(inplace=True),
                nn.Linear(hidden, hidden), 
                nn.BatchNorm1d(hidden),
            ) for _ in range(1)
        ])
        
        self.res_act = nn.ReLU(inplace=True)
        
        # Bottleneck comprime la rappresentazione
        # nn.Dropout: azzera casualmente una percentuale di neuroni per evitare l'overfitting (Di imparare le cose a memoria).
        self.bottleneck = nn.Sequential(
            nn.Dropout(dropout), 
            nn.Linear(hidden, 64), 
            nn.BatchNorm1d(64), 
            nn.ReLU(inplace=True)
        )
        
        # Teste indipendenti per ogni comando fisico
        # Tanh mappa i valori tra [-1, 1] (perfetto per lo sterzo e marce -1..6 normalizzate).
        # In questo caso nn.Linear (64,1) comprime i valori in uno solo per fornire l'output
        self.head_steer = nn.Sequential(nn.Linear(64, 1), nn.Tanh())
        self.head_gear  = nn.Sequential(nn.Linear(64, 1), nn.Tanh())
        
        # Sigmoid mappa i valori tra [0, 1] (perfetto per acceleratore e freno).
        self.head_accel = nn.Sequential(nn.Linear(64, 1), nn.Sigmoid())
        self.head_brake = nn.Sequential(nn.Linear(64, 1), nn.Sigmoid())

    def forward(self, x):

        # Definisce il passaggio in avanti dei dati nella rete (Forward Pass)
        h = self.encoder(x)
        for block in self.res_blocks: 
            h = self.res_act(h + block(h))
            
        h = self.bottleneck(h)
        
        # torch.cat unisce i tensori (Evoluzione di matrice) di output in un unico array
        return torch.cat([self.head_steer(h), self.head_accel(h), self.head_brake(h), self.head_gear(h)], dim=1)

class TorcsEndToEndNet(nn.Module):

    # Modello Unificato JIT (Pre-processamento + Rete Neurale).
    # Incapsula scalatura e PCA direttamente nel grafo computazionale del modello.

    # Vengono salvati: la media e la scala (deviazione standard) dello scaler,
    #  e la media e i componenti (le direzioni principali) della PCA.
    def __init__(self, net, scaler, pca):
        super().__init__()
        self.net = net
        
        # register_buffer salva costanti direttamente nel modello per esportarlo senza dipendenze esterne
        self.register_buffer("raw_scale", torch.tensor(RAW_SCALE, dtype=torch.float32))
        self.register_buffer("scaler_mean", torch.tensor(scaler.mean_, dtype=torch.float32))
        self.register_buffer("scaler_scale", torch.tensor(scaler.scale_, dtype=torch.float32))
        self.register_buffer("pca_mean", torch.tensor(pca.mean_, dtype=torch.float32))
        self.register_buffer("pca_comps", torch.tensor(pca.components_.T, dtype=torch.float32))

    def forward(self, x_raw):

        # --- Flusso completo di elaborazione ---

        # torch.clamp forza i valori nei limiti scelti
        x = torch.clamp(x_raw / self.raw_scale, -3.0, 3.0)
        
        # Normalizzazione come farebbe lo StandardScaler di scikit-learn
        # sottrae la media e divide per la deviazione standard
        x = (x - self.scaler_mean) / self.scaler_scale
        
        # Proiezione PCA tramite moltiplicazione di matrici (torch.matmul)
        x = torch.matmul(x - self.pca_mean, self.pca_comps)
        
        return self.net(x)

class WeightedMSELoss(nn.Module):

    # Funzione di Loss (Errore che il modello cerca di minimizzare) personalizzata (Mean Squared Error).
    # Pondero diversamente l'errore sui vari comandi, dando priorità allo sterzo e al freno.

    # pesi relativi a: ( sterzo, acceleratore, freno, marcia ) in input
    WEIGHTS = torch.tensor([2.0, 1.0, 1.5, 0.5])
    
    def forward(self, pred, target):
        # calcola l'errore quadratico medio pesato tra le previsioni (pred) e i valori reali (target)
        return ((pred - target) ** 2 * self.WEIGHTS.to(pred.device)).mean()


#  ----------- CICLO DI ADDESTRAMENTO -----------

def train(X_pca, y, input_dim, model_dir, epochs, batch_size, lr, val_split, seed):

    # Avvio l'addestramento della rete neurale.
    
    # Fissaggio dei seed per riproducibilità, garantisce che i risultati siano gli stessi ad ogni run
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    
    # torch.device seleziona la GPU se disponibile (CUDA), altrimenti usa il processore (CPU)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    
    # Creazione dataset e divisione train/pred
    dataset = TorcsDataset(X_pca, y)
    n_val = int(len(dataset) * val_split)
    train_ds, val_ds = random_split(dataset, [len(dataset) - n_val, n_val], generator=torch.Generator().manual_seed(seed))
    
    pin = (device.type == "cuda")
    
    # DataLoader organizza il dataset a blocchi (batch), mescolando i dati in fase di training
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, pin_memory=pin)
    val_loader   = DataLoader(val_ds, batch_size=batch_size, shuffle=False, pin_memory=pin)

    # Inizializzo modello spostandolo nel device scelto
    model = TorcsDriverNet(input_dim=input_dim).to(device)
    criterion = WeightedMSELoss()
    
    # optim.AdamW è una versione avanzata dell'algoritmo di discesa del gradiente Adam, aggiunge un decadimento del peso (weight_decay) per limitare l'overfitting
    optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    
    # CosineAnnealingLR riduce gradualmente il learning rate seguendo una curva del coseno
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=lr * 0.01)
    
    # GradScaler serve per l'Automatic Mixed Precision (AMP), scala i gradienti per velocizzare il calcolo su GPU
    scaler_amp = torch.cuda.amp.GradScaler() if device.type == "cuda" else None

    print(f"\n[TRAIN] Device: {device} | Parametri: {sum(p.numel() for p in model.parameters() if p.requires_grad):,}")
    

    # Ciclo basato sulle epoche

    for epoch in range(1, epochs + 1):
        t0, tr_loss = time.time(), 0.0
        
        # Imposta il modello in modalità allenamento (abilita dropout e batchnorm attivi)
        model.train()
        
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            
            # Azzera i gradienti calcolati nello step precedente
            optimizer.zero_grad()
            
            if scaler_amp:
                # Esegue il foward pass con precisione ridotta
                with torch.cuda.amp.autocast():
                    loss = criterion(model(xb), yb)
                # Calcola i gradienti scalati    
                scaler_amp.scale(loss).backward()
                scaler_amp.unscale_(optimizer)
                # Clip_grad_norm taglia i gradienti troppo grandi per evitare esplosioni (NaN)
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                # Aggiorna i pesi
                scaler_amp.step(optimizer)
                scaler_amp.update()
            else:
                loss = criterion(model(xb), yb)
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                
            tr_loss += loss.item() * len(xb)
            
        tr_loss /= len(train_ds)

        # Fase di validazione (model.eval disabilita il dropout)
        model.eval()
        va_loss = sum(criterion(model(xb.to(device)), yb.to(device)).item() * len(xb) for xb, yb in val_loader) / n_val
        
        # Aggiorna il learning rate
        scheduler.step()
        
        print(f"Ep {epoch:>3d} | Tr Loss: {tr_loss:.6f} | Val Loss: {va_loss:.6f} | Time: {time.time()-t0:.1f}s")



    return model.cpu().eval()


#  ----------- ENTRY POINT -----------

if __name__ == "__main__":
    logs_dir = "logs"
    model_dir = "models"
    epochs = 50
    batch = 256
    lr = 1e-3
    val_split = 0.15
    min_speed = 5.0
    pca_components = 0.95
    seed = 42
    
    # Prendo in input i parametri passati da terminale
    opts, _ = getopt.getopt(sys.argv[1:], "", ["logs-dir=", "model-dir=", "epochs=", "batch=", "lr=", "val-split=", "min-speed=", "pca-components=", "seed="])
    for opt, val in opts:
        if opt == "--logs-dir": logs_dir = val
        elif opt == "--model-dir": model_dir = val
        elif opt == "--epochs": epochs = int(val)
        elif opt == "--batch": batch = int(val)
        elif opt == "--lr": lr = float(val)
        elif opt == "--val-split": val_split = float(val)
        elif opt == "--min-speed": min_speed = float(val)
        elif opt == "--pca-components":
            v = float(val)
            pca_components = int(v) if v >= 1.0 else v
        elif opt == "--seed": seed = int(val)

    # Calcolo il percorso esatto della cartella basato sullo script (Evita errori di file not found)
    base = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isabs(logs_dir): logs_dir = os.path.join(base, logs_dir)
    if not os.path.isabs(model_dir): model_dir = os.path.join(base, model_dir)
    
    print(f"\n[INFO] Cerco i log nella cartella: {logs_dir}")
    
    # 1. Carico Dati
    X_raw, y = load_logs(logs_dir, min_speed)
    
    # 2. Pre-processing
    X_pca, input_dim, scaler_obj, pca_obj = fit_scaler_pca(X_raw, pca_components, model_dir)
    
    # 3. Addestramento
    model = train(X_pca, y, input_dim, model_dir, epochs, batch, lr, val_split, seed)
    
    # 4. Compilazione ed Esportazione JIT
    print("\n[EXPORT] Compilazione JIT del modello End-to-End...")
    end_to_end_model = TorcsEndToEndNet(model, scaler_obj, pca_obj)
    dummy_input = torch.zeros(1, N_RAW_FEATURES, dtype=torch.float32)
    
    # torch.jit.trace compila la rete neurale in uno script statico (TorchScript).
    # Si simula un passaggio in avanti con dummy_input, così PyTorch registra le operazioni.
    # Il file esportato è slegato dai file Python e girerà istantaneamente su CPU.
    traced_model = torch.jit.trace(end_to_end_model, dummy_input)
    traced_path = os.path.join(model_dir, "torcs_driver_jit.pt")
    
    # Salva il file .pt contenente pesi e istruzioni ottimizzate
    traced_model.save(traced_path)
    
    print(f"[EXPORT] Modello JIT ultrarapido pronto e salvato in: {traced_path}")