import sys
import os
import time
import socket as _socket

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from snakeoil3_gym import Client

from Controller.xbox_controller import XboxController
from Controller.session_logger import SessionLogger

# ──────────────────────────────────────────────────────────────────────────────
# Funzione principale: run_manual_session
# ──────────────────────────────────────────────────────────────────────────────

def run_manual_session(host: str = "localhost",
                       port: int = 3001,
                       track: str = "unknown",
                       user: str = "unknown",
                       max_steps: int = 100_000):
    """
    Avvia una sessione manuale completa.

    Architettura anti-lag
    ---------------------
    Il loop è guidato esclusivamente dal timing di TORCS (50 Hz / 20 ms per step).
    - La lettura del joypad ed eventi pygame avvengono ad OGNI step.
    - I pacchetti UDP stantii vengono drenati prima di leggere il joypad,
      così il comando inviato si riferisce sempre all'ultimo stato ricevuto.
    """
    # ── 1. Joypad ───────────────────────────────────────
    xbox = XboxController()

    # ── 2. Logger ────────────────────────────────────────────────────
    logger = SessionLogger(user=user, track=track)

    # ── 3. Connessione TORCS ─────────────────────────────────────────────────
    print(f"\n[TORCS] Connessione a {host}:{port} ...")
    C = Client(H=host, p=port, t=track)
    print("[TORCS] Connesso!\n")
    print("Controlli: Stick=steer  RT=accel  LT=brake  B=gear+  A=gear-  Select=restart  Start=pausa")
    print()

    step    = 0
    running = True

    # ── Conteggio giri ────────────────────────────────────────────────────────
    # Un giro è completato quando distFromStart torna vicino a 0
    # (scende di oltre LAP_WRAP_THRESHOLD rispetto al valore dello step precedente).
    LAP_WRAP_THRESHOLD = 200.0    # metri — soglia sicura per qualsiasi pista
    LAPS_TO_COMPLETE   = 1        # giri necessari per una gara valida
    _prev_dist         = None     # distFromStart al passo precedente
    _laps_completed    = 0        # giri completati finora

    try:
        while running and step < max_steps:

            # ── 1. Ricevi l'ultimo stato da TORCS ────────────────────────────
            # get_servers_input() è bloccante: aspetta il prossimo pacchetto UDP.
            # Questo è il "master clock" del loop (~50 Hz / 20 ms per step).
            C.get_servers_input()
            if C.so is None:
                # Gara completata SOLO se abbiamo percorso tutti i giri richiesti
                logger.race_completed = (_laps_completed >= LAPS_TO_COMPLETE)
                if logger.race_completed:
                    print(f"[TORCS] Gara completata ({_laps_completed} giri).")
                else:
                    print(f"[TORCS] Gara terminata anticipatamente "
                          f"(giri completati: {_laps_completed}/{LAPS_TO_COMPLETE}).")
                break

            # ── 2. Drena pacchetti UDP in eccesso (anti-stale-frame) ──────────
            # Se il render ha impiegato più di 20ms, TORCS potrebbe aver già
            # inviato il frame successivo. Lo leggiamo per avere lo stato fresco.
            if C.so is not None:
                C.so.settimeout(0)          # non-blocking momentaneo
                try:
                    while True:
                        raw, _ = C.so.recvfrom(2**17)
                        decoded = raw.decode('utf-8')
                        if decoded and '***' not in decoded:
                            C.S.parse_server_str(decoded)   # aggiorna allo stato più recente
                except _socket.error:
                    pass                                    # coda svuotata
                finally:
                    C.so.settimeout(1)      # ripristina timeout normale

            # ── 3. Leggi joypad ───────────────────────────────────────────────
            ctrl = xbox.read()
            if ctrl["quit"]:
                print("\n[INFO] Uscita richiesta.")
                running = False

            if ctrl["restart"]:
                print("\n[INFO] Riavvio gara richiesto!")
                R = C.R.d
                R["meta"] = 1
                C.respond_to_server()
                logger.reset()
                _laps_completed = 0
                _prev_dist = None
                continue

            paused = ctrl["paused"]

            if paused:
                # ── MODALITÀ PAUSA ──────────────────────────────────────────
                # Dobbiamo comunque rispondere a TORCS altrimenti il server
                # pensa che il client si sia disconnesso e resetta la gara.
                # Inviamo freno leggero per fermare l’auto dolcemente.
                R = C.R.d
                R["accel"]  = 0.0
                R["brake"]  = 0.5    # freno leggero — l’auto rallenta e si ferma
                R["steer"]  = 0.0
                R["clutch"] = 0.0
                R["meta"]   = 0
                C.respond_to_server()
                continue                          # salta log e applica comandi

            # ── 5. Applica comandi (solo se NON in pausa) ─────────────────
            R = C.R.d
            R["accel"]  = ctrl["accel"]
            R["brake"]  = ctrl["brake"]
            R["steer"]  = ctrl["steer"]
            R["gear"]   = ctrl["gear"]
            R["clutch"] = 0.0
            R["meta"]   = 0

            # ── 6. Invia al server (più vicino possibile alla lettura) ─────────
            C.respond_to_server()

            # ── 7. Conteggio giri ─────────────────────────────────────────────
            dist = C.S.d.get("distFromStart", 0.0)
            if _prev_dist is not None and dist < _prev_dist - LAP_WRAP_THRESHOLD:
                _laps_completed += 1
                print(f"[LAP] Giro {_laps_completed} completato!")
            _prev_dist = dist

            # ── 8. Log ────────────────────────────────────────────────────────
            step += 1
            logger.log_step(C.S.d, R)

    except KeyboardInterrupt:
        print("\n[INFO] Ctrl+C rilevato — salvataggio log in corso...")
    except Exception as exc:
        print(f"\n[ERRORE] {exc}")

    finally:
        logger.save_and_close()
        C.shutdown()
        xbox.close()
        print("\n[INFO] Sessione terminata correttamente.")
