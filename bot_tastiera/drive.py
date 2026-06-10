import ctypes   # Libreria l'input da tastiera
import json # Libreria per l'interazione coi file json

def clip(v, lo, hi):
    """
    Funzione di utilità matematica per limitare i valori fra lo e hi
    
    """
    if v < lo: return lo
    elif v > hi: return hi
    else: return v


def drive_example(c):
    """
    Funzione principale che viene richiamata ad ogni frame del simulatore (circa 50 volte al secondo).
    Contiene sia il bot di guida, che l'intercettazione fisica della tastiera.
   
    """
    
    # S: Dizionario contenente i valori dei sensori appena ricevuti dal server di Torcs (Velocità, danni, ecc.)
    # R: Dizionario contenente le risposte che invieremo al server (Acceleratore, freno, sterzo)
    S, R = c.S.d, c.R.d


    # LOGICA DI GUIDA AUTOMATICA (BOT) 
    # Viene eseguita solo se l'utente ha scelto la modalità 1
    if c.control_mode == 'auto':
        
        # ANALISI DEL TRACCIATO 
        # Verifico quanta strada dritta si trova davanti alla vettura interrogando i laser centrali dell'auto
        look_ahead = max(S['track'][7:12])
        


        # CALCOLO DELLA VELOCITÀ TARGET E STACCATA 
        # Regolo la velocità in base allo spazio disponibile
        if look_ahead > 160:
            target_speed = 290.0
        else:
            # Se siamo in curva, aggiusto la velocità in base ad essa
            target_speed = look_ahead * 2.3


        # Regolo la velocità in base alla posizione in pista
        # Se abs(S['trackPos']) > 0.95, siamo molto vicini al bordo, quindi deve rallentare
        if abs(S['trackPos']) > 0.95:
            target_speed = min(target_speed, 250.0)


        # Comportamento dell'auto fuori pista
        is_off_track = abs(S['trackPos']) >= 1.05

        if is_off_track:
            target_speed = 40.0 # Fuori pista rallento molto per non slittare o girarmi
            
            # Se l'auto è orientata male (angolo elevato), rallento ancora di più
            if abs(S['angle']) > 0.7:
                target_speed = 20.0

        # Altro controllo per capire se stiammo sbandando e quindi aggiustare lo sterzo
        is_skidding = abs(S.get('speedY', 0)) > 5.0 or (abs(S['angle']) > 0.45 and S['speedX'] > 60.0)



        # CONTROLLO STERZO 

        if is_off_track:
            
            # Manovra per rientrare basata sull'angolo relativo alla pista
            steer_target = (S['angle'] * 0.9) - (S['trackPos'] * 0.4)

        elif is_skidding:
            
            # In sbandata, sterzo in direzione opposta per raddrizzarmi
            steer_target = (S['angle'] * 1.5) - (S['trackPos'] * 0.1)

        else:
            
            # La correzione spaziale usa una curva cubica: è morbida al centro della pista
            # e diventa più forte se l'auto si avvicina ai bordi
            track_correction = (S['trackPos'] ** 3) * 0.8

            # Il target dello sterzo cerca di restare parallelo all'asse della pista e al centro
            steer_target = (S['angle'] * 0.8) - track_correction
            

        # Applica il limite tra tutto a destra (-1.0) e tutto a sinistra (1.0)
        R['steer'] = clip(steer_target, -1.0, 1.0)




        # CONTROLLO ACCELERATORE E FRENO

        # Calcola la differenza tra quanto vorremmo andare e la nostra velocità reale
        speed_error = target_speed - S['speedX']

        if speed_error > 0: # Dobbiamo accelerare se siamo sotto la velocità target
            
            # Riduco l'acceleratore se lo sterzo è piegato (per non dare gas e curvare forte allo stesso tempo)
            max_accel = 1.0 - (abs(R['steer']) * 0.5) 
            R['accel'] = clip(speed_error / 20.0, 0.0, max_accel)
            R['brake'] = 0.0 # Stacco il freno
            

            # Controllo la trazione: calcola la differenza di rotazione tra ruote posteriori (motrici) e anteriori
            spin_diff = (S['wheelSpinVel'][2] + S['wheelSpinVel'][3]) - (S['wheelSpinVel'][0] + S['wheelSpinVel'][1])

            if spin_diff > 2.0:  
                # Se le ruote posteriori girano a vuoto, taglio il gas per riprendere grip
                R['accel'] *= 0.6 
            if is_skidding:
                # Se l'auto sbanda di traverso, taglia il gas per permettere alle ruote posteriori di smettere di slittare
                R['accel'] *= 0.3 

        else:

            # Bisogna rallentare
            R['accel'] = 0.0
            # Evita frenate violente se l'auto è sterzata
            max_brake = 1.0 - (abs(R['steer']) * 0.4)
            # Frena in modo proporzionale a quanto siamo fuori velocità
            R['brake'] = clip(-speed_error / 15.0, 0.0, max_brake)

        # Se la macchina è ferma (vel < 5) ma deve andare (> 10), schiaccio il pedale del gas al massimo
        if S['speedX'] < 5.0 and target_speed > 10.0:
            R['accel'] = 1.0
            R['brake'] = 0.0
    else:
        # Se la modalità scelta NON è auto, l'AI è disattivata. Inizializzo i motori a 0 in attesa dell'input
        R['steer'] = 0.0
        R['accel'] = 0.0
        R['brake'] = 0.0


    # OVERRIDE MANUALE 
    # Inizializzo le variabili interne per la memoria dello stato di pedali e sterzo
    if not hasattr(c, 'smooth_steer'):
        c.smooth_steer = R['steer']
        c.smooth_accel = R['accel']
        c.smooth_brake = R['brake']
        c.manual_steer_active = False # Flag per indicare se il giocatore sta sterzando
        c.manual_pedal_active = False # Flag per indicare se il giocatore usa gas/freno
        c.manual_gear_active = not c.auto_gear # Gestione marce manuale attivata se richiesto 

    # Lettura diretta dell'hardware tramite ctypes. Ritorna True se il tasto corrispondente è premuto
    manual_w = (ctypes.windll.user32.GetAsyncKeyState(0x57) & 0x8000) != 0 # Tasto W (0x57)
    manual_s = (ctypes.windll.user32.GetAsyncKeyState(0x53) & 0x8000) != 0 # Tasto S (0x53)
    manual_a = (ctypes.windll.user32.GetAsyncKeyState(0x41) & 0x8000) != 0 # Tasto A (0x41)
    manual_d = (ctypes.windll.user32.GetAsyncKeyState(0x44) & 0x8000) != 0 # Tasto D (0x44)


    # MODELLO FISICO AVANZATO (Input Shaping)

    speed_factor = max(1.0, S['speedX'])

    # Simulazione del carico aerodinamico: maggiore velocità = maggiore aderenza
    aero_grip = clip(0.4 + (speed_factor / 280.0)**2, 0.4, 1.0)
    
    # Limito l'angolo di sterzo della tastiera alle alte velocità per evitare testacoda
    max_steer_angle = clip(120.0 / speed_factor, 0.15, 1.0)
    
    # Sensibilità e reattività degli input
    alpha_steer = 1.0  
    alpha_pedals = 1.0  
    decay_rate = 0.0


    # ELABORAZIONE PEDALI

    if manual_w:
        # Pressione di W: accelero al 100%
        c.smooth_accel = c.smooth_accel * (1 - alpha_pedals) + 1.0 * alpha_pedals
        c.smooth_brake = 0.0
        R['accel'] = c.smooth_accel
        R['brake'] = c.smooth_brake
        c.manual_pedal_active = True
        
    elif manual_s:
        if S.get('speedX', 0) < 1.0:
            # Macchina quasi ferma: premo S e innesco la retromarcia
            c.smooth_accel = c.smooth_accel * (1 - alpha_pedals) + 1.0 * alpha_pedals
            c.smooth_brake = 0.0
            R['accel'] = c.smooth_accel
            R['brake'] = c.smooth_brake
            c.manual_pedal_active = True
        else:
            # In movimento: S agisce da freno
            c.smooth_brake = c.smooth_brake * (1 - alpha_pedals) + aero_grip * alpha_pedals
            c.smooth_accel = 0.0
            R['brake'] = c.smooth_brake
            R['accel'] = c.smooth_accel
            c.manual_pedal_active = True
            
    else:
        # Tasti rilasciati
        if c.manual_pedal_active:
            # Applico il decadimento per ripassare gradualmente il controllo all'AI
            c.smooth_accel = c.smooth_accel * decay_rate + R['accel'] * (1 - decay_rate)
            c.smooth_brake = c.smooth_brake * decay_rate + R['brake'] * (1 - decay_rate)
            R['accel'] = c.smooth_accel
            R['brake'] = c.smooth_brake
            
            # Quando i valori sono simili a quelli dell'AI, disattivo il flag manuale
            if abs(c.smooth_accel - R['accel']) < 0.05 and abs(c.smooth_brake - R['brake']) < 0.05:
                c.manual_pedal_active = False
        else:
            # Controllo interamente lasciato all'AI
            c.smooth_accel = R['accel']
            c.smooth_brake = R['brake']


    # ELABORAZIONE STERZO MANUALE

    if manual_a or manual_d:
        if manual_a:
            target_steer = max_steer_angle  # Tasto A = Sterza a Sinistra
        elif manual_d:
            target_steer = -max_steer_angle # Tasto D = Sterza a Destra
            
        # Applico lo sterzo bersaglio
        c.smooth_steer = c.smooth_steer * (1 - alpha_steer) + target_steer * alpha_steer
        R['steer'] = clip(c.smooth_steer, -1.0, 1.0)
        c.manual_steer_active = True
        
    else:
        # Quando rilascio il tasto dello sterzo, torno dritto
        if c.manual_steer_active:
            c.smooth_steer = c.smooth_steer * decay_rate + R['steer'] * (1 - decay_rate)
            R['steer'] = clip(c.smooth_steer, -1.0, 1.0)
            if abs(c.smooth_steer - R['steer']) < 0.05:
                c.manual_steer_active = False
        else:
            c.smooth_steer = R['steer']


    # ABS GLOBALE AVANZATO

    if R['brake'] > 0:
        # Riduco la potenza frenante massima in curva per non bloccare le ruote
        steer_penalty = (abs(R['steer']) ** 2) * 0.85 
        max_safe_brake = clip(1.0 - steer_penalty, 0.0, aero_grip if 'aero_grip' in locals() else 1.0)
        R['brake'] = min(R['brake'], max_safe_brake)


    # GESTIONE CAMBIO AUTOMATICO

    if not c.manual_gear_active:
        rpm = S.get('rpm', 0)
        speed = S.get('speedX', 0)
        gear = S.get('gear', 1)
        
        # Contatore di attesa tra una cambiata e l'altra 
        if not hasattr(c, 'gear_step'): c.gear_step = 0
        c.gear_step += 1

        if c.gear_step > 10:
            if gear < 6 and rpm > 13000:
                R['gear'] = gear + 1 # Salgo di marcia ad alti giri
                c.gear_step = 0
            elif gear > 1 and rpm < 6500:
                R['gear'] = gear - 1 # Scalo di marcia a bassi giri
                c.gear_step = 0
        
        # Inserisco la prima marcia se l'auto è quasi ferma
        if gear <= 0 and speed < 5 and not manual_s:
            R['gear'] = 1

        # Inserisco la retromarcia in automatico se premo il tasto 'S' da fermo
        if manual_s and speed < 1.0:
            R['gear'] = -1


    # RECUPERO EMERGENZA 

    # Manovra automatica per sganciarsi se l'auto è bloccata ad un ostacolo
    if c.control_mode == 'auto' and S.get('stucktimer', 0) > 50: 
        R['gear'] = -1                  # Mette retromarcia
        R['accel'] = 0.8                # Accelera all'indietro
        R['brake'] = 0.0
        R['steer'] = -S.get('angle', 0) # Sterza per uscire dall'ostacolo
        

    # FASE DI LOGGING DEI DATI (JSONL)

    # Salvo il log solo se i pacchetti base sono presenti
    if 'track' in S and 'wheelSpinVel' in S and 'speedX' in S:
        c.step_count += 1
        
        # Dizionario contenente i parametri della vettura
        record = {
            "step":        c.step_count,                             
            "mode":        c.control_mode,                           
            "speedX":      round(S['speedX'], 4),                    
            "speedY":      round(S.get('speedY', 0), 4),             
            "speedZ":      round(S.get('speedZ', 0), 4),             
            "angle":       round(S.get('angle', 0), 5),              
            "trackPos":    round(S.get('trackPos', 0), 5),           
            "rpm":         round(S.get('rpm', 0), 1),                
            "gear":        int(S.get('gear', 0)),                    
            "damage":      round(S.get('damage', 0), 1),             
            "distRaced":   round(S.get('distRaced', 0), 2),          
            "racePos":     int(S.get('racePos', 0)),                 
            "track":       [round(v, 3) for v in S['track']],        
            "wheelSpinVel": [round(v, 3) for v in S['wheelSpinVel']],
            "cmd": {                                                 
                "steer": round(R['steer'], 5),
                "accel": round(R['accel'], 5),
                "brake": round(R['brake'], 5),
                "gear":  int(R['gear'])
            }
        }
        
        # Aggiungo all'array in memoria
        c.records.append(json.dumps(record) + "\n")

    return