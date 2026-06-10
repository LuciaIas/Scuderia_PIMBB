# torcs_ai_driver.py
# ==================
# Modulo per collegare la rete neurale End-to-End JIT con TORCS via UDP.
# Gestione 100% IA: Sterzo, Acceleratore, Freno e Marce.

import os
import sys
import getopt
import time

# Evito la creazione di file compilati __pycache__ velocizzando l'esecuzione
sys.dont_write_bytecode = True

# Importo il client UDP base per interfacciarsi con il server di TORCS
from snakeoil3_gym import Client, clip

try:
    # Libreria principale per il calcolo tensoriale e inferenza neurale
    import torch
except ImportError:
    print("[ERRORE] PyTorch non trovato.")
    sys.exit(1)


#  ----------- 1. CARICAMENTO MODELLO END-TO-END -----------

def load_jit_model(model_dir: str):

    # Carico il modello compilato JIT (TorchScript) che include già Scaler e PCA.
    # A differenza di torch.load, jit.load non ha bisogno della definizione delle classi in python.
    model_path = os.path.join(model_dir, "torcs_driver_jit.pt")
    
    if not os.path.isfile(model_path):
        print(f"[ERRORE] Modello JIT '{model_path}' non trovato.")
        print("         Esegui prima l'addestramento con train_model.py!")
        sys.exit(1)
        
    # Carico il modello mappandolo sulla CPU per un'inferenza super leggera, 
    # dato che le GPU su frame singoli non offrono vantaggi e aggiungono overhead.
    net = torch.jit.load(model_path, map_location="cpu")
    
    # Imposto il modello in modalità valutazione (disabilita Dropout e simili)
    net.eval()
    
    print(f"[PIPELINE] Modello End-to-End caricato da: {model_path}")
    return net

def sensors_to_tensor(S: dict) -> torch.Tensor:

    # Preparo l'array raw da dare in pasto alla rete. 
    # La rete JIT si occuperà in automatico della Normalizzazione e PCA ai pesi interni.
    track = list(S.get("track", []))
    
    # Riempio i valori mancanti del telemetro o li taglio a 19 per uniformare l'input
    if len(track) < 19:   
        track += [200.0] * (19 - len(track))
    elif len(track) > 19: 
        track = track[:19]

    # Assemblo i sensori grezzi nello stesso identico ordine usato per il training
    x_raw = [
        S.get("angle", 0.0), S.get("speedX", 0.0), S.get("speedY", 0.0),
        S.get("trackPos", 0.0), S.get("rpm", 0.0)
    ] + [float(v) for v in track]

    # torch.tensor crea la struttura dati principale usata da PyTorch
    return torch.tensor([x_raw], dtype=torch.float32)


#  ----------- 2. CLASSE DRIVER (IA) -----------

class AIDriver:
    
    # Pilota autonomo gestito interamente dalla rete neurale.
    
    def __init__(self, net):
        self.net = net
        self.n_total = 0
        self.n_ai = 0

    def act(self, C) -> dict:

        # Calcolo e applico l'azione da compiere basandomi sullo stato dei sensori correnti.
        S, R = C.S.d, C.R.d
        self.n_total += 1

        # Inferenza Rete End-to-End
        x_raw = sensors_to_tensor(S)
        
        # torch.no_grad() disabilita il calcolo dei gradienti per risparmiare moltissima RAM e CPU in fase di esecuzione
        with torch.no_grad():
            # squeeze(0) rimuove la dimensione di batch, numpy() converte il tensore in array classico
            out = self.net(x_raw).squeeze(0).numpy()

        # Estraggo le 4 componenti predette dalla rete (Sterzo, Gas, Freno, Marcia)
        raw_steer = float(out[0])
        accel     = float(out[1])
        brake     = float(out[2])
        raw_gear  = float(out[3])

        # Applico lo sterzo diretto, limitandolo al range consentito (-1.0, 1.0)
        steer = clip(raw_steer, -1.0, 1.0)

        # La marcia era stata normalizzata (divisa per 6) durante l'addestramento, qui la ripristino
        pred_gear = int(round(raw_gear * 6.0))
        pred_gear = max(-1, min(6, pred_gear))

        # Imposto i comandi calcolati all'interno della risposta da inviare al simulatore
        R["steer"]  = steer
        R["accel"]  = clip(accel, 0.0, 1.0)
        R["brake"]  = clip(brake, 0.0, 1.0)
        R["gear"]   = pred_gear
        R["clutch"] = 0.0
        R["meta"]   = 0

        self.n_ai += 1
        return R

    def print_stats(self):

        # Stampo le statistiche finali di intervento al termine della gara.
        tot = max(1, self.n_total)
        print(f"\n[STATS] Step totali: {self.n_total:,}")
        print(f"[STATS] Step IA    : {self.n_ai:,} ({100 * self.n_ai / tot:.1f}%)")


#  ----------- 3. LOOP PRINCIPALE -----------

def run_ai_session(host="localhost", port=3001, model_dir="models", max_steps=100000, max_episodes=1):
    
    # Inizializzo il client UDP e avvio il loop di guida automatica infinito.
    
    # Preparo il modello e il pilota
    net = load_jit_model(model_dir)
    driver = AIDriver(net)

    print(f"\n[TORCS] Connessione a {host}:{port} ...")
    C = Client(H=host, p=port)
    print("[TORCS] Connesso!\n")

    for episode in range(1, max_episodes + 1):
        ep_steps = 0
        ep_start = time.time()
        
        for _ in range(max_steps):
            
            # Ricevo lo stato aggiornato dal simulatore
            C.get_servers_input()
            
            # Se la socket è chiusa, esco dal loop
            if C.so is None: 
                break 
                
            # Calcolo l'azione tramite IA
            driver.act(C)
            
            # Invio la risposta fisica all'auto
            C.respond_to_server()
            
            ep_steps += 1

            # Stampo log leggeri a schermo ogni 250 frame
            if ep_steps % 250 == 0:
                print(f" step={ep_steps:6d}  t={time.time()-ep_start:5.0f}s  speed={C.S.d.get('speedX', 0.0):6.1f} "
                      f" steer={C.R.d.get('steer', 0.0):+.3f}  accel={C.R.d.get('accel', 0.0):.2f} "
                      f" brake={C.R.d.get('brake', 0.0):.2f}  gear={C.R.d.get('gear', 1)}")

    driver.print_stats()
    C.shutdown()
    print("\n[INFO] Sessione AI terminata.")

if __name__ == "__main__":
    host, port, model_dir, max_steps, max_episodes = "localhost", 3001, "models", 100000, 1
    
    # getopt per leggere agevolmente eventuali flag (es. -H, -p) passati da console
    opts, _ = getopt.getopt(sys.argv[1:], "H:p:m:", ["host=", "port=", "model-dir="])
    for opt, val in opts:
        if opt in ("-H", "--host"): 
            host = val
        elif opt in ("-p", "--port"): 
            port = int(val)
        elif opt in ("-m", "--model-dir"): 
            model_dir = val

    # Imposto il path assoluto per la cartella dei modelli così il client li trova ovunque si trovi
    base = os.path.dirname(os.path.abspath(__file__))
    model_dir = model_dir if os.path.isabs(model_dir) else os.path.join(base, model_dir)
    
    run_ai_session(host, port, model_dir, max_steps, max_episodes)