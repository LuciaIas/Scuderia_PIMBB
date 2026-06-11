# Addestramento supervisionato (Behavioural Cloning) per TORCS

import os
import sys
import json
import glob
import getopt
import random
import time

# Evita crash causati da conflitti tra più istanze di OpenMP 
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import numpy as np

try:
    import torch
    # torch.nn contiene i moduli base per costruire reti neurali 
    import torch.nn as nn
    # torch.optim contiene gli algoritmi di ottimizzazione (es. AdamW, SGD) per aggiornare i pesi della rete
    import torch.optim as optim
    # Dataset e DataLoader servono per gestire e caricare i dati durante il training
    from torch.utils.data import Dataset, DataLoader, random_split
except ImportError:
    print("[ERRORE] PyTorch non trovato.")
    sys.exit(1)

try:
    # StandardScaler rimuove la media e scala i dati in modo che abbiano varianza unitaria
    from sklearn.preprocessing import StandardScaler
    # PCA riduce la dimensionalità dei dati mantenendo la maggior parte della varianza
    from sklearn.decomposition import PCA
except ImportError:
    print("[ERRORE] scikit-learn non trovato.")
    sys.exit(1)


# COSTANTI E PARAMETRI 

# Fattori di scala per normalizzare i sensori prima della PCA
RAW_SCALE = np.array(
    [3.14159, 300.0, 100.0, 1.0, 10000.0] + [200.0] * 19,
    dtype=np.float32,
)

N_RAW_FEATURES = 24 # 5 sensori interni + 19 esterni


# CARICAMENTO E PRE-PROCESSING DATI

# Leggo i log JSONL per estrarre sensori e comandi
def _iter_records(filepath: str):

    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh) # Carica tutto il blocco dati
        if isinstance(data, dict) and "steps" in data:
            for step in data["steps"]:
                # Estrazione sicura di sensori e azioni con validazione
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
            line = line.strip() # Rimuove spazi e "a capo"
            if not line: continue
            # Tenta di convertire la stringa di testo in un dizionario Python
            try: 
                rec = json.loads(line)
            except json.JSONDecodeError: 
                continue
                
            if not isinstance(rec, dict): continue
            
            # Estrae i dati di interesse
            sensors = rec.get("sensors", {})
            actions = rec.get("actions", {})
            
            # 'yeld' restituisce la coppia di dati e mette in pausa il ciclo
            if isinstance(sensors, dict) and isinstance(actions, dict):
                yield sensors, actions

# Carica, filtra e normalizza i dati di telemetria
def load_logs(logs_dir: str, min_speed: float = 5.0):

    # Ricerca file di log
    files = sorted(glob.glob(os.path.join(logs_dir, "*.jsonl")) + glob.glob(os.path.join(logs_dir, "*.json")))
    if not files:
        print(f"[ERRORE] Nessun log in '{logs_dir}'")
        sys.exit(1)

    # Inizializza le liste per accumulare i dati validi e i contatori per le statistiche
    X_list, y_list, skipped, total = [], [], 0, 0

    for filepath in files:
        for sensors, actions in _iter_records(filepath):
            speed = sensors.get("speedX", 0.0)
            
            # Scarto frame a bassa velocità (auto ferma o in testacoda lento)
            if abs(speed) < min_speed:
                skipped += 1
                continue

            # Verifica che ci siano esattamente 19 misurazioni
            track = sensors.get("track", [])
            if len(track) != 19:
                skipped += 1
                continue

            # COSTRUZIONE DEL VETTORE DELLE FEATURES (X_raw)
            x_raw = np.array([
                sensors.get("angle", 0.0), sensors.get("speedX", 0.0),
                sensors.get("speedY", 0.0), sensors.get("trackPos", 0.0),
                sensors.get("rpm", 0.0),
            ] + [float(v) for v in track], dtype=np.float32)

            # NORMALIZZAZIONE E CLIPPING
            x_pre = np.clip(x_raw / RAW_SCALE, -3.0, 3.0)
            
            # NORMALIZZAZIONE DELLE AZIONI (y_raw)
            gear_norm = float(actions.get("gear", 1)) / 6.0

            # Assembla il vettore contenente i target che l'IA dovrà imparare a prevedere
            y_raw = np.array([
                float(actions.get("steer", 0.0)), float(actions.get("accel", 0.0)),
                float(actions.get("brake", 0.0)), gear_norm,
            ], dtype=np.float32)

            X_list.append(x_pre)
            y_list.append(y_raw)
            total += 1

    print(f"[DATI] Step validi: {total:,} | Scartati: {skipped:,}")
    if total == 0: sys.exit(1)
    
    # np.stack aggrega la lista di vettori in una singola matrice multidimensionale
    return np.stack(X_list), np.stack(y_list)

# Applico standardizzazione e PCA per eliminare rumore
def fit_scaler_pca(X_raw: np.ndarray, pca_components, model_dir: str):

    print("\n[PRE-PROC] Fitting StandardScaler ...")
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_raw)

    print(f"[PRE-PROC] Fitting PCA ({pca_components}) ...")
    pca = PCA(n_components=pca_components, random_state=0)
    X_pca = pca.fit_transform(X_scaled).astype(np.float32)


    return X_pca, pca.n_components_, scaler, pca


# MODELLO NEURALE
 
# Classe wrapper per interfacciare le matrici dei dati (NumPy) 
# con il sistema di caricamento a pacchetti di PyTorch
class TorcsDataset(Dataset):
    
    def __init__(self, X, y):
        # Converte matrici in "Tensori"
        self.X, self.y = torch.from_numpy(X), torch.from_numpy(y)
        
    
    def __len__(self): 
        return len(self.X) # Dimensione dataset
        
    # Funzione chiamata dal DataLoader ripetutamente per assemblare i pacchetti
    def __getitem__(self, idx): 
        return self.X[idx], self.y[idx]


# Architettura della Rete Neurale (post-PCA) 
# nn.Module che è la classe base di PyTorch per i modelli
class TorcsDriverNet(nn.Module):


    def __init__(self, input_dim: int, hidden: int = 128, dropout: float = 0.1):
        super().__init__()
        
        # ENCODER (Espansione)
        # Riceve i dati compressi dalla PCA e li dispone in uno spazio a dimensionalità maggiore (128 neuroni)
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, hidden), #  Linear: Crea 128 connessioni pesate per ogni dato in ingresso
            nn.BatchNorm1d(hidden), # BatchNorm1d: Standardizza i segnali per velocizzare e stabilizzare l'apprendimento
            nn.ReLU(inplace=True)  # ReLU: Azzera i valori negativi
        )
        
        # BLOCCHI RESIDUALI (Elaborazione)
        # Prevengono la perdita di informazione nelle reti profonde
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
        
        # BOTTLENECK (Compressione)
        # Raccoglie le analisi dei blocchi residuali e le condensa da 128 a 64 neuroni.
        self.bottleneck = nn.Sequential(
            nn.Dropout(dropout), # "Spegne" casualmente una percentuale di neuroni  ad ogni ciclo
            nn.Linear(hidden, 64), 
            nn.BatchNorm1d(64), 
            nn.ReLU(inplace=True)
        )
        
        # OUTPUT HEADS 
        # Da 64 neuroni a 4 ramificazioni indipendenti
        # Tanh mappa i valori tra [-1.0, 1.0]
        self.head_steer = nn.Sequential(nn.Linear(64, 1), nn.Tanh())
        self.head_gear  = nn.Sequential(nn.Linear(64, 1), nn.Tanh())
        
        # Sigmoid mappa i valori tra [0, 1] 
        self.head_accel = nn.Sequential(nn.Linear(64, 1), nn.Sigmoid())
        self.head_brake = nn.Sequential(nn.Linear(64, 1), nn.Sigmoid())

    # Definisce il percorso di andata dei dati attraverso i neuroni
    def forward(self, x):

        h = self.encoder(x)

        for block in self.res_blocks: 
            h = self.res_act(h + block(h))
   
        h = self.bottleneck(h)
        
        # torch.cat unisce i tensori di output in un unico array
        return torch.cat([self.head_steer(h), self.head_accel(h), self.head_brake(h), self.head_gear(h)], dim=1)

# Modello Unificato JIT che incapsula la logica matematica dello StandardScaler 
# e della PCA direttamente nel grafo computazionale di PyTorch
class TorcsEndToEndNet(nn.Module):

    def __init__(self, net, scaler, pca):
        super().__init__()
        self.net = net # Salva la rete neurale già addestrata al suo interno
        
        self.register_buffer("raw_scale", torch.tensor(RAW_SCALE, dtype=torch.float32))
        # Estrae i parametri matematici dallo StandardScaler (Media e Deviazione Standard)
        self.register_buffer("scaler_mean", torch.tensor(scaler.mean_, dtype=torch.float32))
        self.register_buffer("scaler_scale", torch.tensor(scaler.scale_, dtype=torch.float32))
        # Estrae i parametri matematici della PCA (Media e Matrice delle Componenti)
        self.register_buffer("pca_mean", torch.tensor(pca.mean_, dtype=torch.float32))
        self.register_buffer("pca_comps", torch.tensor(pca.components_.T, dtype=torch.float32))

    # Esegue l'intera pipeline in tempo reale sui dati grezzi ricevuti dal simulatore.
    def forward(self, x_raw):

        # Normalizzazione e clipping
        # torch.clamp forza i valori nei limiti scelti
        x = torch.clamp(x_raw / self.raw_scale, -3.0, 3.0)
        
        # Standardizzazione
        x = (x - self.scaler_mean) / self.scaler_scale
        
        # Proiezione PCA tramite moltiplicazione di matrici (torch.matmul)
        x = torch.matmul(x - self.pca_mean, self.pca_comps)
        
        return self.net(x)


# Funzione di costo basata sull'Errore Quadratico Medio (MSE) pesato.
# Modifica il calcolo dell'errore standard per penalizzare in modo diverso 
# le imprecisioni sui comandi critici per la dinamica del veicolo.

class WeightedMSELoss(nn.Module):

    # pesi relativi a: sterzo, acceleratore, freno, marcia
    WEIGHTS = torch.tensor([2.0, 1.0, 1.5, 0.5])
    
    def forward(self, pred, target):
        return ((pred - target) ** 2 * self.WEIGHTS.to(pred.device)).mean()


# CICLO DI ADDESTRAMENTO 

# Prende i dati compressi (X_pca) e i target (y)
# per istruire la rete neurale ad avvicinarsi ai comandi del pilota umano, epoca dopo epoca.
def train(X_pca, y, input_dim, model_dir, epochs, batch_size, lr, val_split, seed):

    # Fissaggio dei seed per riproducibilità
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
    
    # optim.AdamW aggiunge un decadimento del peso (weight_decay) per limitare l'overfitting
    optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    
    # CosineAnnealingLR riduce gradualmente il learning rate seguendo una curva del coseno
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=lr * 0.01)
    
    # GradScaler serve per l'Automatic Mixed Precision (AMP), scala i gradienti per velocizzare il calcolo su GPU
    scaler_amp = torch.cuda.amp.GradScaler() if device.type == "cuda" else None

    print(f"\n[TRAIN] Device: {device} | Parametri: {sum(p.numel() for p in model.parameters() if p.requires_grad):,}")
    

    # Ciclo delle epoche

    for epoch in range(1, epochs + 1):
        t0, tr_loss = time.time(), 0.0
        
        # Imposta il modello in modalità allenamento
        model.train()
        
        # Scorre l'intero Training Set, a blocchi
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            
            # Azzera la memoria degli errori passati
            optimizer.zero_grad()
            
            if scaler_amp:
                # Esegue il foward pass con precisione ridotta
                with torch.cuda.amp.autocast():
                    loss = criterion(model(xb), yb)
                # Calcola i gradienti scalati    
                scaler_amp.scale(loss).backward()
                scaler_amp.unscale_(optimizer)
                # Clip_grad_norm taglia i gradienti troppo grandi per evitare esplosioni
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

        # Media matematica degli errori compiuti sul Training Set    
        tr_loss /= len(train_ds)

        # Fase di validazione (model.eval disabilita il dropout)
        model.eval()
        va_loss = sum(criterion(model(xb.to(device)), yb.to(device)).item() * len(xb) for xb, yb in val_loader) / n_val
        
        # Aggiorna il learning rate
        scheduler.step()
        
        print(f"Ep {epoch:>3d} | Tr Loss: {tr_loss:.6f} | Val Loss: {va_loss:.6f} | Time: {time.time()-t0:.1f}s")



    return model.cpu().eval()


# ENTRY POINT 
# gestisce gli iperparametri, avvia la pipeline di elaborazione e si occupa 
# dell'esportazione finale del modello compilato
if __name__ == "__main__":
    logs_dir = "logs"
    model_dir = "models"
    epochs = 50
    batch = 256
    lr = 1e-3
    val_split = 0.15 # 85% Training / 15% Validation
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

    # Calcolo il percorso esatto della cartella basato sullo script 
    base = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isabs(logs_dir): logs_dir = os.path.join(base, logs_dir)
    if not os.path.isabs(model_dir): model_dir = os.path.join(base, model_dir)
    
    print(f"\n[INFO] Cerco i log nella cartella: {logs_dir}")
    
    # Carico Dati
    X_raw, y = load_logs(logs_dir, min_speed)
    
    # Pre-processing
    X_pca, input_dim, scaler_obj, pca_obj = fit_scaler_pca(X_raw, pca_components, model_dir)
    
    # Addestramento
    model = train(X_pca, y, input_dim, model_dir, epochs, batch, lr, val_split, seed)
    
    # Compilazione ed Esportazione JIT
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