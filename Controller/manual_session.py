import sys
import os
import time
import socket as _socket

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from snakeoil3_gym import Client

from Controller.xbox_controller import XboxController
from Controller.session_logger import SessionLogger


#  ----------- SESSIONE MANUALE -----------

def run_manual_session(host: str = "localhost", port: int = 3001, track: str = "unknown", user: str = "unknown", max_steps: int = 100_000):
    """
    Funzione principale che avvia la gara con il joypad Xbox.
    Il ciclo segue la tempistica del server TORCS (50 Hz).
    Vengono scartati pacchetti UDP vecchi per annullare l'input lag.
    """
    
    # Inizializzo il controller Xbox
    xbox = XboxController()

    # Inizializzo il sistema di logging
    logger = SessionLogger(user=user, track=track)

    # Inizializzo la connessione a TORCS
    print(f"\n[TORCS] Connessione a {host}:{port} ...")
    C = Client(H=host, p=port, t=track)
    print("[TORCS] Connesso!\n")
    print("Controlli: Stick=steer  RT=accel  LT=brake  B=gear+  A=gear-  Select=restart  Start=pausa\n")

    step    = 0
    running = True

    # Variabili per il calcolo dei giri completati
    LAP_WRAP_THRESHOLD = 200.0    # Salto di distanza che denota il passaggio del traguardo
    LAPS_TO_COMPLETE   = 1        # Giri necessari per una gara valida
    _prev_dist         = None     
    _laps_completed    = 0        

    try:
        while running and step < max_steps:

            #  ----------- 1. RICEZIONE DATI -----------
            
            # Aspetto il pacchetto dal server bloccando il loop (funge da clock)
            C.get_servers_input()
            
            if C.so is None:
                # Disconnesso. Valuto se la gara è completata con successo
                logger.race_completed = (_laps_completed >= LAPS_TO_COMPLETE)
                if logger.race_completed:
                    print(f"[TORCS] Gara completata ({_laps_completed} giri).")
                else:
                    print(f"[TORCS] Gara interrotta (giri completati: {_laps_completed}/{LAPS_TO_COMPLETE}).")
                break

            #  ----------- 2. GESTIONE INPUT LAG -----------
            
            # Dreno i pacchetti UDP in eccesso per evitare l'accumulo di ritardo 
            if C.so is not None:
                C.so.settimeout(0) # Non bloccante
                try:
                    while True:
                        raw, _ = C.so.recvfrom(2**17)
                        decoded = raw.decode('utf-8')
                        if decoded and '***' not in decoded:
                            C.S.parse_server_str(decoded) # Aggiorno allo stato più recente
                except _socket.error:
                    pass # Ho letto tutti i pacchetti pendenti
                finally:
                    C.so.settimeout(1) # Rimetto il timeout normale

            #  ----------- 3. LETTURA INPUT -----------
            
            ctrl = xbox.read()
            if ctrl["quit"]:
                print("\n[INFO] Uscita richiesta.")
                running = False

            if ctrl["restart"]:
                print("\n[INFO] Riavvio gara richiesto!")
                R = C.R.d
                R["meta"] = 1 # Segnale speciale per il reset
                C.respond_to_server()
                
                # Resetto variabili interne e log
                logger.reset()
                _laps_completed = 0
                _prev_dist = None
                continue

            paused = ctrl["paused"]
            if paused:
                # Se sono in pausa, devo comunque rispondere al server per evitare la disconnessione
                R = C.R.d
                R["accel"]  = 0.0
                R["brake"]  = 0.5 # Freno piano per fermarmi dolcemente
                R["steer"]  = 0.0
                R["clutch"] = 0.0
                R["meta"]   = 0
                C.respond_to_server()
                continue

            #  ----------- 4. INVIO COMANDI -----------
            
            # Applico i comandi rilevati dal joypad
            R = C.R.d
            R["accel"]  = ctrl["accel"]
            R["brake"]  = ctrl["brake"]
            R["steer"]  = ctrl["steer"]
            R["gear"]   = ctrl["gear"]
            R["clutch"] = 0.0
            R["meta"]   = 0

            # Rispondo immediatamente al server
            C.respond_to_server()

            #  ----------- 5. CONTROLLO GIRI E LOG -----------
            
            dist = C.S.d.get("distFromStart", 0.0)
            
            # Se la distanza corrente è molto inferiore rispetto a prima, ho tagliato il traguardo
            if _prev_dist is not None and dist < _prev_dist - LAP_WRAP_THRESHOLD:
                _laps_completed += 1
                print(f"[LAP] Giro {_laps_completed} completato!")
            _prev_dist = dist

            step += 1
            logger.log_step(C.S.d, R)

    except KeyboardInterrupt:
        print("\n[INFO] Rilevato arresto da tastiera, salvo e chiudo...")
    except Exception as exc:
        print(f"\n[ERRORE] {exc}")

    finally:
        logger.save_and_close()
        C.shutdown()
        xbox.close()
        print("\n[INFO] Sessione chiusa correttamente.")
