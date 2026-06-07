import os
import json
import time
import datetime

# ──────────────────────────────────────────────────────────────────────────────
# Costanti
# ──────────────────────────────────────────────────────────────────────────────
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")

# ──────────────────────────────────────────────────────────────────────────────
# Classe: SessionLogger
# ──────────────────────────────────────────────────────────────────────────────

class SessionLogger:
    """
    Scrive un record JSON per ogni step in formato JSON Lines.
    Ogni riga è un oggetto JSON autonomo:
      {"user":..., "timestamp":..., "sensors":{...}, "actions":{...}}

    Il file viene aperto in append mode con line-buffering:
    il flush avviene automaticamente dopo ogni '\\n', senza
    bloccare mai il loop di gioco.
    """

    def __init__(self, user: str = "unknown", track: str = "unknown"):
        os.makedirs(LOG_DIR, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_id     = ts
        self.user           = user
        # Estensione .jsonl per chiarire il formato (una riga = un record)
        self.filepath       = os.path.join(LOG_DIR, f"session_{ts}.jsonl")
        self.records        = []
        self._step_count    = 0
        self.race_completed = False   # True se TORCS ha segnalato shutdown/restart
        print(f"[LOG] Sessione avviata \u2192 i log saranno salvati in: {self.filepath} solo a fine gara")

    def log_step(self, server_state: dict, action: dict):
        """Scrive una riga JSON per questo step. Ritorna immediatamente."""
        record = {
            "user":      self.user,
            "timestamp": time.time(),
            "sensors": {
                "speedX":   server_state.get("speedX",   0.0),
                "speedY":   server_state.get("speedY",   0.0),
                "angle":    server_state.get("angle",    0.0),
                "trackPos": server_state.get("trackPos", 0.0),
                "rpm":      server_state.get("rpm",      0.0),
                "track":    server_state.get("track",    []),
            },
            "actions": {
                "steer": action.get("steer", 0.0),
                "accel": action.get("accel", 0.0),
                "brake": action.get("brake", 0.0),
                "gear":  action.get("gear",  1),
            },
        }
        # Aggiunge in memoria
        self.records.append(json.dumps(record, separators=(',', ':')) + '\n')
        self._step_count += 1

    def reset(self):
        """Resetta i log in caso di riavvio gara."""
        self.records = []
        self._step_count = 0

    @staticmethod
    def _next_race_number() -> int:
        """Restituisce il prossimo N per log_garaN.jsonl nella cartella LOG_DIR."""
        existing = [
            f for f in os.listdir(LOG_DIR)
            if f.startswith("log_gara") and f.endswith(".jsonl")
        ]
        nums = []
        for name in existing:
            try:
                nums.append(int(name[len("log_gara"):-len(".jsonl")]))
            except ValueError:
                pass
        return max(nums, default=0) + 1

    def rename_as_race_log(self) -> str:
        """Rinomina il file corrente in log_garaN.jsonl e aggiorna self.filepath."""
        n = self._next_race_number()
        new_path = os.path.join(LOG_DIR, f"log_gara{n}.jsonl")
        os.rename(self.filepath, new_path)
        self.filepath = new_path
        return new_path

    def save_and_close(self):
        """Salva il file solo se la gara è stata completata."""
        if self.race_completed:
            with open(self.filepath, "w", encoding="utf-8") as f:
                f.writelines(self.records)
            new_path = self.rename_as_race_log()
            print(f"[LOG] Gara completata! {self._step_count} step salvati \u2192 {new_path}")
        else:
            print(f"[LOG] Sessione terminata senza completare la gara. Nessun log salvato.")
