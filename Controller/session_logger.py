import os
import json
import time
import datetime

# Costante per il percorso della cartella dei log
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")


#  ----------- CLASSE: SessionLogger -----------

class SessionLogger:
    """
    Gestisce il salvataggio dei log di telemetria e comandi in formato JSONL.
    Crea un file di log temporaneo durante la gara e lo salva in maniera permanente
    solo a gara terminata con successo.
    """

    def __init__(self, user: str = "unknown", track: str = "unknown"):
        # Crea la cartella se assente
        os.makedirs(LOG_DIR, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_id     = ts
        self.user           = user
        # Definisco il path temporaneo (sarà rinominato a fine sessione)
        self.filepath       = os.path.join(LOG_DIR, f"session_{ts}.jsonl")
        self.records        = []
        self._step_count    = 0
        self.race_completed = False   # Flag per la validità della gara
        print(f"[LOG] Sessione avviata. I log saranno salvati in: {self.filepath} a fine gara.")

    def log_step(self, server_state: dict, action: dict):
        """Preparo e aggiungo un nuovo record di telemetria per questo step."""
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
        # Aggiungo la stringa JSON compressa all'array in memoria
        self.records.append(json.dumps(record, separators=(',', ':')) + '\n')
        self._step_count += 1

    def reset(self):
        """Azzero i log in memoria (usato per il riavvio della gara)."""
        self.records = []
        self._step_count = 0

    @staticmethod
    def _next_race_number() -> int:
        """Legge la cartella dei log e ricava il prossimo numero progressivo per log_garaN."""
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
        """Rinomina il file di sessione in log_garaN.jsonl per l'archivio definitivo."""
        n = self._next_race_number()
        new_path = os.path.join(LOG_DIR, f"log_gara{n}.jsonl")
        os.rename(self.filepath, new_path)
        self.filepath = new_path
        return new_path

    def save_and_close(self):
        """Scrivo tutto su file se la gara è stata completata correttamente."""
        if self.race_completed:
            with open(self.filepath, "w", encoding="utf-8") as f:
                f.writelines(self.records)
            new_path = self.rename_as_race_log()
            print(f"[LOG] Gara completata! {self._step_count} step salvati -> {new_path}")
        else:
            print(f"[LOG] Sessione terminata senza completare la gara. Nessun log salvato.")
