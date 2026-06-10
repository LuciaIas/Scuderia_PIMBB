# Script di guida autonoma: carica il modello TorchScript e controlla l'auto in tempo reale
# Gestisce connessione al simulatore, inferenza del modello e invio dei comandi (sterzo, gas, freno, marce)

import os
import sys
import getopt # Gestisce gli argomenti passati da linea di comando
import time

# Evita crash causati da conflitti tra più istanze di OpenMP 
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

# Evita la creazione di file __pycache__ velocizzando l'esecuzione
sys.dont_write_bytecode = True

# Importo il client UDP base per interfacciarsi con il server di TORCS
from snakeoil3_gym import Client, clip

try:
    # Libreria principale per il calcolo tensoriale e inferenza neurale
    import torch
except ImportError:
    print("[ERRORE] PyTorch non trovato.")
    sys.exit(1)


# CARICAMENTO MODELLO END-TO-END
# Carica il modello compilato JIT (TorchScript) che include già Scaler e PCA
def load_jit_model(model_dir: str):

    model_path = os.path.join(model_dir, "torcs_driver_jit.pt")
    
    if not os.path.isfile(model_path):
        print(f"[ERRORE] Modello JIT '{model_path}' non trovato.")
        print("         Esegui prima l'addestramento con train_model.py!")
        sys.exit(1)
        
    # Carica il modello AI già compilato e lo esegue sulla CPU
    # per evitare rallentamenti inutili dovuti alla GPU 
    net = torch.jit.load(model_path, map_location="cpu")
    
    # Imposto il modello in modalità valutazione (disabilita Dropout e simili)
    net.eval()
    
    print(f"[PIPELINE] Modello End-to-End caricato da: {model_path}")
    return net

# Preparo l'array raw da dare alla rete 
# La rete JIT si occuperà in automatico della Normalizzazione e PCA ai pesi interni
def sensors_to_tensor(S: dict) -> torch.Tensor:

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


# CLASSE DRIVER (IA)
# Pilota autonomo gestito interamente dalla rete neurale
class AIDriver:
    
    def __init__(self, net):
        self.net = net
        self.n_total = 0
        self.n_ai = 0

    # Calcolo e applico l'azione da compiere basandomi sullo stato dei sensori correnti
    def act(self, C) -> dict:

        S, R = C.S.d, C.R.d
        self.n_total += 1 # Frame processati

        # Inferenza rete End-to-End
        x_raw = sensors_to_tensor(S)
        
        # Disabilita il calcolo dei gradienti per risparmiare RAM e CPU in fase di esecuzione
        with torch.no_grad():
            # squeeze(0) rimuove la dimensione di batch, numpy() converte il tensore in array classico
            out = self.net(x_raw).squeeze(0).numpy()

        # Estraggo le 4 componenti predette dalla rete (Sterzo, Gas, Freno, Marcia)
        raw_steer = float(out[0])
        accel     = float(out[1])
        brake     = float(out[2])
        raw_gear  = float(out[3])

        # Limito sterzo al range consentito (-1.0, 1.0)
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

    # Stampa le statistiche finali al termine della gara
    def print_stats(self):

        tot = max(1, self.n_total)
        print(f"\n[STATS] Step totali: {self.n_total:,}")
        print(f"[STATS] Step IA    : {self.n_ai:,} ({100 * self.n_ai / tot:.1f}%)")


# LOOP PRINCIPALE
# Inizializza il client UDP e avvia il loop di guida automatica infinito
def run_ai_session(host="localhost", port=3001, model_dir="models", max_steps=100000, max_episodes=1):
    
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

            # Stampo log a schermo ogni 250 frame
            if ep_steps % 250 == 0:
                print(f" step={ep_steps:6d}  t={time.time()-ep_start:5.0f}s  speed={C.S.d.get('speedX', 0.0):6.1f} "
                      f" steer={C.R.d.get('steer', 0.0):+.3f}  accel={C.R.d.get('accel', 0.0):.2f} "
                      f" brake={C.R.d.get('brake', 0.0):.2f}  gear={C.R.d.get('gear', 1)}")

    driver.print_stats()
    C.shutdown()
    print("\n[INFO] Sessione AI terminata.")

if __name__ == "__main__":
    host, port, model_dir, max_steps, max_episodes = "localhost", 3001, "models", 100000, 1
    
    # Legge argomenti da terminale con getopt
    opts, _ = getopt.getopt(sys.argv[1:], "H:p:m:", ["host=", "port=", "model-dir="])
    for opt, val in opts:
        if opt in ("-H", "--host"): 
            host = val
        elif opt in ("-p", "--port"): 
            port = int(val)
        elif opt in ("-m", "--model-dir"): 
            model_dir = val

    # Cerca la cartella "models" e la converte in un percorso assoluto
    # per trovare il file del modello (torcs_driver_jit.pt)
    base = os.path.dirname(os.path.abspath(__file__))
    model_dir = model_dir if os.path.isabs(model_dir) else os.path.join(base, model_dir)
    
    # Avvia sistema AI
    run_ai_session(host, port, model_dir, max_steps, max_episodes)