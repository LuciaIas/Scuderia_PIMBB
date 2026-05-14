"""
torcs_ai_driver.py
==================
Collega la rete neurale End-to-End JIT con TORCS via UDP.
Gestione 100% IA: Sterzo, Acceleratore, Freno e MARCE!
"""

import os, sys, getopt, time
import numpy as np

# Import dal progetto
from mioTraining import Client, clip

try:
    import torch
except ImportError:
    print("[ERRORE] PyTorch non trovato. Installa con: pip install torch")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# 1. Caricamento Modello End-to-End (JIT)
# ─────────────────────────────────────────────────────────────────────────────

def load_jit_model(model_dir: str):
    """Carica il modello compilato che include gia' Scaler e PCA."""
    model_path = os.path.join(model_dir, "torcs_driver_jit.pt")
    if not os.path.isfile(model_path):
        print(f"[ERRORE] Modello JIT '{model_path}' non trovato.")
        print("         Esegui prima il nuovo train_model.py!")
        sys.exit(1)
        
    net = torch.jit.load(model_path, map_location="cpu")
    net.eval()
    print(f"[PIPELINE] Modello End-to-End caricato da: {model_path}")
    return net

def sensors_to_tensor(S: dict) -> torch.Tensor:
    """Prepara l'array raw. La rete JIT si occupera' di Normalizzazione e PCA."""
    track = list(S.get("track", []))
    if len(track) < 19:   track += [200.0] * (19 - len(track))
    elif len(track) > 19: track = track[:19]

    x_raw = [
        S.get("angle", 0.0), S.get("speedX", 0.0), S.get("speedY", 0.0),
        S.get("trackPos", 0.0), S.get("rpm", 0.0)
    ] + [float(v) for v in track]

    return torch.tensor([x_raw], dtype=torch.float32)

# ─────────────────────────────────────────────────────────────────────────────
# 2. Classe Driver (100% Modello IA)
# ─────────────────────────────────────────────────────────────────────────────

class AIDriver:
    STEER_ALPHA = 0.35  # Filtro per addolcire i movimenti dello sterzo

    def __init__(self, net):
        self.net = net
        self._prev_steer = 0.0
        self.n_total = self.n_ai = 0

    def act(self, C) -> dict:
        S, R = C.S.d, C.R.d
        self.n_total += 1

        # Inferenza Rete End-to-End (Lasciamo guidare l'IA)
        x_raw = sensors_to_tensor(S)
        with torch.no_grad():
            out = self.net(x_raw).squeeze(0).numpy()

        # Estraiamo i 4 valori predetti
        raw_steer = float(out[0])
        accel     = float(out[1])
        brake     = float(out[2])
        raw_gear  = float(out[3])

        # Lo sterzo usa un filtro per fluidità
        steer = clip((self._prev_steer * (1.0 - self.STEER_ALPHA) + raw_steer * self.STEER_ALPHA), -1.0, 1.0)
        self._prev_steer = steer

        # Calcoliamo la marcia: in addestramento era divisa per 6
        pred_gear = int(round(raw_gear * 6.0))
        pred_gear = max(-1, min(6, pred_gear))

        # Inviamo i comandi dell'IA al simulatore
        R["steer"]  = steer
        R["accel"]  = clip(accel, 0.0, 1.0)
        R["brake"]  = clip(brake, 0.0, 1.0)
        R["gear"]   = pred_gear
        R["clutch"] = 0.0
        R["meta"]   = 0

        self.n_ai += 1
        return R

    def print_stats(self):
        tot = max(1, self.n_total)
        print(f"\n[STATS] Step totali: {self.n_total:,}")
        print(f"[STATS] Step IA    : {self.n_ai:,} ({100*self.n_ai/tot:.1f}%)")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Loop Principale
# ─────────────────────────────────────────────────────────────────────────────

def run_ai_session(host="localhost", port=3001, model_dir="models", max_steps=100000, max_episodes=1):
    net = load_jit_model(model_dir)
    driver = AIDriver(net)

    print(f"\n[TORCS] Connessione a {host}:{port} ...")
    C = Client(H=host, p=port)
    print("[TORCS] Connesso!\n")

    for episode in range(1, max_episodes + 1):
        ep_steps, ep_start = 0, time.time()
        for _ in range(max_steps):
            C.get_servers_input()
            if C.so is None: break
            driver.act(C)
            C.respond_to_server()
            ep_steps += 1

            if ep_steps % 250 == 0:
                print(f" step={ep_steps:6d}  t={time.time()-ep_start:5.0f}s  speed={C.S.d.get('speedX', 0.0):6.1f} "
                      f" steer={C.R.d.get('steer', 0.0):+.3f}  accel={C.R.d.get('accel', 0.0):.2f} "
                      f" brake={C.R.d.get('brake', 0.0):.2f}  gear={C.R.d.get('gear', 1)}")

    driver.print_stats()
    C.shutdown()
    print("\n[INFO] Sessione AI terminata.")

if __name__ == "__main__":
    host, port, model_dir, max_steps, max_episodes = "localhost", 3001, "models", 100000, 1
    opts, _ = getopt.getopt(sys.argv[1:], "H:p:m:", ["host=", "port=", "model-dir="])
    for opt, val in opts:
        if opt in ("-H", "--host"): host = val
        elif opt in ("-p", "--port"): port = int(val)
        elif opt in ("-m", "--model-dir"): model_dir = val

    base = os.path.dirname(os.path.abspath(__file__))
    model_dir = model_dir if os.path.isabs(model_dir) else os.path.join(base, model_dir)
    run_ai_session(host, port, model_dir, max_steps, max_episodes)