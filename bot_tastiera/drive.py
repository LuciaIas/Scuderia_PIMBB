import ctypes   # Importo la libreria necessaria per l'input da tastiera
import json # Importo la libreria per l'interazione coi file json

def clip(v, lo, hi):
    """
    Funzione di utilità matematica per limitare i valori fra lo e hi
    
    """
    if v < lo: return lo
    elif v > hi: return hi
    else: return v


# Funzione di guida a partire da quelle di "snakeoil3-gym" per l'AI
def drive_example(c):
    """
    Funzione principale (Bot) che viene richiamata ad ogni tick/frame del simulatore (circa 50 volte al secondo).
    Contiene sia il bot di guida, che l'intercettazione fisica della tastiera.

    """
    
    # S: Dizionario contenente i valori dei Sensori appena ricevuti dal server di Torcs (Velocità, danni, ecc.)
    # R: Dizionario contenente le Risposte (attuatori) che invieremo al server (Acceleratore, freno, sterzo)
    S, R = c.S.d, c.R.d


    # === LOGICA DI GUIDA AUTOMATICA (BOT) 
    # Viene eseguita solo se l'utente non ha scelto la modalità 1
    if c.control_mode == 'auto':
        
        #  -----------  1. ANALISI DEL TRACCIATO (Traiettoria centrata fluida) ----------- 
        # Verifico quanta strada dritta si trova davanti alla vettura, interrogando i laser centrali dell'auto
        look_ahead = max(S['track'][7:12])
        


        #  -----------  2. CALCOLO DELLA VELOCITÀ TARGET E STACCATA -----------
        # Regolo la velocità in base allo spazio disponibile
        if look_ahead > 160:
            target_speed = 290.0
        else:
            # Se siamo in curva, aggiusto la velocità in base ad essa
            target_speed = look_ahead * 2.3


        # Regolo la velocità in base alla posizione in pista; Se abs(S['trackPos']) > 0.95, siamo molto vicini al bordo 
        # e bisogna rallentare        
        if abs(S['trackPos']) > 0.95:
            target_speed = min(target_speed, 250.0)

#------------------------------------------------------------------
        # Comportamento dell'auto fuori pista
        is_off_track = abs(S['trackPos']) >= 1.05

        if is_off_track:
            target_speed = 40.0 # Fuori pista rallento pesantemente per non slittare o girarmi
            
            # Se l'auto è orientata male (angolo di imbardata elevato), rallento ancora di più
            if abs(S['angle']) > 0.7:
                target_speed = 20.0   # ...rallento ancora di più.

        # === CONTROLLO SBANDATA (SKID) E CONTROSTERZO ===
        # Se la velocità laterale (speedY) è alta o siamo molto storti ma stiamo andando forte, stiamo sbandando/derapando
        is_skidding = abs(S.get('speedY', 0)) > 5.0 or (abs(S['angle']) > 0.45 and S['speedX'] > 60.0)



        #  ----------- 3. CONTROLLO STERZO -----------  
        if is_off_track:
            # Manovra disperata per rientrare (si basa fortemente sull'angolazione e poco sulla posizione laterale per non testacoda)
            steer_target = (S['angle'] * 0.9) - (S['trackPos'] * 0.4)
        elif is_skidding:
            # In sbandata, applica una massiccia correzione sterzando "contro" la sbandata per raddrizzare l'auto (controsterzo)
            steer_target = (S['angle'] * 1.5) - (S['trackPos'] * 0.1)
        else:
            # In condizioni normali:
            # La correzione spaziale segue una curva al cubo per essere morbida al centro pista,
            # ma fortissima e reattiva se ci stiamo allontanando troppo ai lati (effetto calamita morbido)
            track_correction = (S['trackPos'] ** 3) * 0.8
            # Il target dello sterzo cerca di tenerci paralleli all'asse della pista (- angle) e al centro (- trackPos)
            steer_target = (S['angle'] * 0.8) - track_correction
            
        # Applica il limite hardware tra tutto a destra (-1.0) e tutto a sinistra (1.0)
        R['steer'] = clip(steer_target, -1.0, 1.0)

        # 4. ACCELERATORE E FRENO
        # Calcoliamo l'errore di velocità (la differenza tra quanto vorremmo andare e la nostra velocità reale longitudinale)
        speed_error = target_speed - S['speedX']

        if speed_error > 0:
            # Dobbiamo accelerare perché siamo sotto la velocità target
            # Riduciamo l'acceleratore massimo se lo sterzo è piegato (non puoi dare gas e curvare forte allo stesso tempo senza slittare)
            max_accel = 1.0 - (abs(R['steer']) * 0.5) 
            R['accel'] = clip(speed_error / 20.0, 0.0, max_accel)
            R['brake'] = 0.0 # Stacca il freno
            
            # Controllo di Trazione (TCS): Calcola la differenza di rotazione tra ruote posteriori (motrici) e anteriori
            spin_diff = (S['wheelSpinVel'][2] + S['wheelSpinVel'][3]) - (S['wheelSpinVel'][0] + S['wheelSpinVel'][1])
            if spin_diff > 2.0:  
                # Se le ruote posteriori girano a vuoto (pattinano/burnout), taglia il gas istantaneamente per riprendere grip
                R['accel'] *= 0.6 
            if is_skidding:
                # Se l'auto sbanda di traverso, taglia pesantemente il gas per permettere alle ruote posteriori di smettere di derapare
                R['accel'] *= 0.3 
        else:
            # Dobbiamo frenare perché siamo troppo veloci rispetto alla target_speed
            R['accel'] = 0.0
            # Evita frenate "piene" se l'auto è sterzata (Trail Braking / ABS per non bloccare)
            max_brake = 1.0 - (abs(R['steer']) * 0.4)
            # Frena in modo proporzionale a quanto siamo fuori velocità
            R['brake'] = clip(-speed_error / 15.0, 0.0, max_brake)

        # Ripresa da fermo: se la macchina è piantata (vel < 5) ma deve andare (> 10), schiaccia tutto
        if S['speedX'] < 5.0 and target_speed > 10.0:
            R['accel'] = 1.0
            R['brake'] = 0.0
    else:
        # Se la modalità scelta NON è auto, l'AI è zittita. Inizializziamo i motori a 0 in attesa dell'uomo
        R['steer'] = 0.0
        R['accel'] = 0.0
        R['brake'] = 0.0

    # === PRECEDENZA ASSOLUTA MA FLUIDA: OVERRIDE MANUALE ===
    # Inizializziamo al primo loop le variabili interne per tenere in memoria lo stato precedente dei pedali/sterzo
    if not hasattr(c, 'smooth_steer'):
        c.smooth_steer = R['steer']
        c.smooth_accel = R['accel']
        c.smooth_brake = R['brake']
        c.manual_steer_active = False # Flag: l'uomo sta sterzando?
        c.manual_pedal_active = False # Flag: l'uomo sta usando gas/freno?
        c.manual_gear_active = not c.auto_gear # Gestione marce manuale attivata se richiesto dal menu

    # Lettura diretta dell'hardware. Intercetta la pressione fisica dei tasti W A S D
    # tramite chiamate di basso livello a Windows (ctypes). 
    # Ritorna True se il tasto corrispondente (in esadecimale) è premuto
    manual_w = (ctypes.windll.user32.GetAsyncKeyState(0x57) & 0x8000) != 0 # Tasto W (0x57)
    manual_s = (ctypes.windll.user32.GetAsyncKeyState(0x53) & 0x8000) != 0 # Tasto S (0x53)
    manual_a = (ctypes.windll.user32.GetAsyncKeyState(0x41) & 0x8000) != 0 # Tasto A (0x41)
    manual_d = (ctypes.windll.user32.GetAsyncKeyState(0x44) & 0x8000) != 0 # Tasto D (0x44)

    # === MODELLO FISICO AVANZATO (Input Shaping) ===
    speed_factor = max(1.0, S['speedX'])
    # Simulazione del carico aerodinamico (downforce): più andiamo veloci, più le ruote sono schiacciate a terra e il grip base sale
    aero_grip = clip(0.4 + (speed_factor / 280.0)**2, 0.4, 1.0)
    # Limita l'angolo massimo di sterzo della tastiera alle alte velocità, per simulare la resistenza meccanica e non fare testacoda istantanei
    max_steer_angle = clip(120.0 / speed_factor, 0.15, 1.0)
    
    # Valori di sensibilità (Exponential Moving Average): a 1.0 la reattività è massima (nessun ritardo), 
    # azzerando l'input lag originario.
    alpha_steer = 1.0  
    alpha_pedals = 1.0  
    # Velocità con cui l'auto smette di sterzare o frenare se lasciamo il tasto: a 0.0 torna istantaneamente dritto
    decay_rate = 0.0

    # --- Elaborazione Pedali ---
    if manual_w:
        # Se premo W, accelera al 100% (usando l'alpha per l'applicazione immediata)
        c.smooth_accel = c.smooth_accel * (1 - alpha_pedals) + 1.0 * alpha_pedals
        c.smooth_brake = 0.0
        R['accel'] = c.smooth_accel
        R['brake'] = c.smooth_brake
        c.manual_pedal_active = True
    elif manual_s:
        # Se si preme 'S' a macchina pressocché ferma, innesca l'acceleratore in retromarcia (retromarcia fisica)
        if S.get('speedX', 0) < 1.0:
            c.smooth_accel = c.smooth_accel * (1 - alpha_pedals) + 1.0 * alpha_pedals
            c.smooth_brake = 0.0
            R['accel'] = c.smooth_accel
            R['brake'] = c.smooth_brake
            c.manual_pedal_active = True
        else:
            # Se siamo in moto in avanti, allora 'S' si comporta da FRENO
            # L'efficacia frenante è influenzata dal grip aerodinamico per evitare blocchi gomma improvvisi a bassa velocità
            c.smooth_brake = c.smooth_brake * (1 - alpha_pedals) + aero_grip * alpha_pedals
            c.smooth_accel = 0.0
            R['brake'] = c.smooth_brake
            R['accel'] = c.smooth_accel
            c.manual_pedal_active = True
    else:
        # Nessun tasto di gas/freno premuto (W e S rilasciati)
        if c.manual_pedal_active:
            # Se stavamo usando i pedali, applica il decadimento (decay_rate).
            # Essendo 0.0, c.smooth_accel diventa istantaneamente uguale a R['accel'] (cioè quello dell'AI o 0.0 in manuale)
            c.smooth_accel = c.smooth_accel * decay_rate + R['accel'] * (1 - decay_rate)
            c.smooth_brake = c.smooth_brake * decay_rate + R['brake'] * (1 - decay_rate)
            R['accel'] = c.smooth_accel
            R['brake'] = c.smooth_brake
            # Spegne il flag quando l'intervento manuale sfuma fondendosi completamente con l'AI
            if abs(c.smooth_accel - R['accel']) < 0.05 and abs(c.smooth_brake - R['brake']) < 0.05:
                c.manual_pedal_active = False
        else:
            # Se nessuno sta usando il pedale manuale, usa ciecamente i comandi calcolati dall'AI
            c.smooth_accel = R['accel']
            c.smooth_brake = R['brake']

    # --- Elaborazione Sterzo Manuale ---
    if manual_a or manual_d:
        if manual_a:
            target_steer = max_steer_angle  # Tasto A = Sterza tutto a Sinistra (+ positivo nel mondo di Torcs)
        elif manual_d:
            target_steer = -max_steer_angle # Tasto D = Sterza tutto a Destra (- negativo)
            
        # Applica immediatamente lo sterzo bersaglio
        c.smooth_steer = c.smooth_steer * (1 - alpha_steer) + target_steer * alpha_steer
        R['steer'] = clip(c.smooth_steer, -1.0, 1.0)
        c.manual_steer_active = True
    else:
        # Quando rilasci il tasto dello sterzo...
        if c.manual_steer_active:
            # Torna dritto immediatamente e restituisci il controllo all'AI
            c.smooth_steer = c.smooth_steer * decay_rate + R['steer'] * (1 - decay_rate)
            R['steer'] = clip(c.smooth_steer, -1.0, 1.0)
            if abs(c.smooth_steer - R['steer']) < 0.05:
                c.manual_steer_active = False
        else:
            c.smooth_steer = R['steer']

    # === ABS GLOBALE AVANZATO ===
    # Sistema Anti-Bloccaggio d'emergenza, indipendentemente se sta frenando l'AI o il giocatore umano
    if R['brake'] > 0:
        steer_penalty = (abs(R['steer']) ** 2) * 0.85 # La penalità al freno scala col quadrato dell'angolo di sterzo (se curvi devi frenare meno)
        # La massima potenza frenante sicura cala drasticamente in curva (Circle of friction)
        max_safe_brake = clip(1.0 - steer_penalty, 0.0, aero_grip if 'aero_grip' in locals() else 1.0)
        R['brake'] = min(R['brake'], max_safe_brake)

    # 5. GESTIONE CAMBIO AUTOMATICO
    # Viene eseguita solo se l'utente ha scelto il Cambio AUTO nel menu iniziale
    if not c.manual_gear_active:
        rpm = S.get('rpm', 0)
        speed = S.get('speedX', 0)
        gear = S.get('gear', 1)
        
        # Semplice contatore di attesa tra una cambiata e l'altra per evitare lo "sfarfallio" 
        # (se la macchina sobbalza, non devi scalare-salire all'infinito in 10 millisecondi)
        if not hasattr(c, 'gear_step'): c.gear_step = 0
        c.gear_step += 1

        if c.gear_step > 10:
            # Scala MARCIA SUPERIORE se giri altissimi oltre i 13000
            if gear < 6 and rpm > 13000:
                R['gear'] = gear + 1
                c.gear_step = 0
            
            # Scala MARCIA INFERIORE se i giri si abbassano troppo sotto 6500 (motore che affoga)
            elif gear > 1 and rpm < 6500:
                R['gear'] = gear - 1
                c.gear_step = 0
        
        # Inserimento intelligente della prima marcia se l'auto è quasi ferma
        if gear <= 0 and speed < 5 and not manual_s:
            R['gear'] = 1

        # Inserisce la Retromarcia in automatico se si sta premendo il tasto freno 'S' da veicolo quasi fermo
        if manual_s and speed < 1.0:
            R['gear'] = -1

    # 6. RECUPERO EMERGENZA (Anti-Stuck)
    # Se il server rileva che siamo fisicamente bloccati a un ostacolo da oltre 50 frame ed eravamo guidati dall'AI,
    # esegue una manovra automatica per sganciarsi dal muro
    if c.control_mode == 'auto' and S.get('stucktimer', 0) > 50: 
        R['gear'] = -1                  # Mette retromarcia
        R['accel'] = 0.8                # Accelera all'indietro per staccarsi
        R['brake'] = 0.0
        R['steer'] = -S.get('angle', 0) # Sterza contro per uscire dalla collisione frontale
        
    # =======================================================
    # FASE DI LOGGING DEI DATI IN FORMATO JSON ARRAY STANDARD
    # =======================================================
    # Creiamo un "fotogramma" dei dati (log) solo se i pacchetti base sensibili sono arrivati sani e non corrotti
    if 'track' in S and 'wheelSpinVel' in S and 'speedX' in S:
        c.step_count += 1
        
        # Struttura dati (dizionario Python) che impacchetta fedelmente tutti i parametri del veicolo in questo istante
        # Utilissimo per il Machine Learning futuro o per la revisione telemetrica
        record = {
            "step":        c.step_count,                             # Istante di tempo
            "mode":        c.control_mode,                           # Modalità corrente di controllo
            "speedX":      round(S['speedX'], 4),                    # Velocità asse longitudinale
            "speedY":      round(S.get('speedY', 0), 4),             # Velocità asse trasversale (sbandamento laterale)
            "speedZ":      round(S.get('speedZ', 0), 4),             # Velocità asse verticale (salti)
            "angle":       round(S.get('angle', 0), 5),              # Angolo rispetto al centro pista
            "trackPos":    round(S.get('trackPos', 0), 5),           # Distanza laterale dal centro (-1 destra, 1 sinistra)
            "rpm":         round(S.get('rpm', 0), 1),                # Giri del motore
            "gear":        int(S.get('gear', 0)),                    # Marcia corrente (-1 = retro, 0 = folle)
            "damage":      round(S.get('damage', 0), 1),             # Danni cumulati alla vettura
            "distRaced":   round(S.get('distRaced', 0), 2),          # Distanza in metri percorsa dalla partenza assoluta
            "racePos":     int(S.get('racePos', 0)),                 # Posizione in gara (classifica)
            "track":       [round(v, 3) for v in S['track']],        # Distanze dai bordi (Array di 19 telemetri)
            "wheelSpinVel": [round(v, 3) for v in S['wheelSpinVel']],# Velocità rotazionale per ogni singola ruota
            "cmd": {                                                 # Comandi attuati alla fine dell'elaborazione di questo script
                "steer": round(R['steer'], 5),
                "accel": round(R['accel'], 5),
                "brake": round(R['brake'], 5),
                "gear":  int(R['gear'])
            }
        }
        
        # Convertiamo il record Python in una stringa JSON compatta.
        # Aggiungendo un "A capo" (\n) si crea il formato JSONL (JSON Lines) comodissimo da leggere progressivamente.
        # Appendiamo questo fotogramma alla lista in RAM per scriverli tutti su disco poi (in main.py)
        c.records.append(json.dumps(record) + "\n")

    return