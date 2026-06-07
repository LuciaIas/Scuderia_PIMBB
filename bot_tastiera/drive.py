import ctypes
import json

def clip(v, lo, hi):
    if v < lo: return lo
    elif v > hi: return hi
    else: return v

def drive_example(c):
    '''Bot with keyboard override (WASD) and no ML/Controller dependencies'''
    S, R = c.S.d, c.R.d

    if c.control_mode == 'auto':
        # 1. ANALISI DEL TRACCIATO (Traiettoria centrata fluida)
        look_ahead = max(S['track'][7:12])
        
        # 2. CALCOLO DELLA VELOCITÀ TARGET E STACCATA
        if look_ahead > 160:
            target_speed = 330.0
        else:
            target_speed = look_ahead * 2.3

        if abs(S['trackPos']) > 0.95:
            target_speed = min(target_speed, 250.0)

        # === COMPORTAMENTO FUORI PISTA ===
        is_off_track = abs(S['trackPos']) >= 1.05
        if is_off_track:
            target_speed = 40.0 
            if abs(S['angle']) > 0.7:
                target_speed = 20.0

        # === CONTROLLO SBANDATA (SKID) E CONTROSTERZO ===
        is_skidding = abs(S.get('speedY', 0)) > 5.0 or (abs(S['angle']) > 0.45 and S['speedX'] > 60.0)

        # 3. CONTROLLO STERZO
        if is_off_track:
            steer_target = (S['angle'] * 0.9) - (S['trackPos'] * 0.4)
        elif is_skidding:
            steer_target = (S['angle'] * 1.5) - (S['trackPos'] * 0.1)
        else:
            track_correction = (S['trackPos'] ** 3) * 0.8
            steer_target = (S['angle'] * 0.8) - track_correction
            
        R['steer'] = clip(steer_target, -1.0, 1.0)

        # 4. ACCELERATORE E FRENO
        speed_error = target_speed - S['speedX']

        if speed_error > 0:
            max_accel = 1.0 - (abs(R['steer']) * 0.5) 
            R['accel'] = clip(speed_error / 20.0, 0.0, max_accel)
            R['brake'] = 0.0
            
            spin_diff = (S['wheelSpinVel'][2] + S['wheelSpinVel'][3]) - (S['wheelSpinVel'][0] + S['wheelSpinVel'][1])
            if spin_diff > 2.0:  
                R['accel'] *= 0.6 
            if is_skidding:
                R['accel'] *= 0.3 
        else:
            R['accel'] = 0.0
            max_brake = 1.0 - (abs(R['steer']) * 0.4)
            R['brake'] = clip(-speed_error / 15.0, 0.0, max_brake)

        if S['speedX'] < 5.0 and target_speed > 10.0:
            R['accel'] = 1.0
            R['brake'] = 0.0
    else:
        R['steer'] = 0.0
        R['accel'] = 0.0
        R['brake'] = 0.0

    # === PRECEDENZA ASSOLUTA MA FLUIDA: OVERRIDE MANUALE ===
    if not hasattr(c, 'smooth_steer'):
        c.smooth_steer = R['steer']
        c.smooth_accel = R['accel']
        c.smooth_brake = R['brake']
        c.manual_steer_active = False
        c.manual_pedal_active = False
        c.manual_gear_active = not c.auto_gear

    manual_w = (ctypes.windll.user32.GetAsyncKeyState(0x57) & 0x8000) != 0
    manual_s = (ctypes.windll.user32.GetAsyncKeyState(0x53) & 0x8000) != 0
    manual_a = (ctypes.windll.user32.GetAsyncKeyState(0x41) & 0x8000) != 0
    manual_d = (ctypes.windll.user32.GetAsyncKeyState(0x44) & 0x8000) != 0

    # === MODELLO FISICO AVANZATO ===
    speed_factor = max(1.0, S['speedX'])
    aero_grip = clip(0.4 + (speed_factor / 280.0)**2, 0.4, 1.0)
    max_steer_angle = clip(120.0 / speed_factor, 0.15, 1.0)
    
    alpha_steer = 0.25  
    alpha_pedals = 0.4  
    decay_rate = 0.85    

    # --- Pedali ---
    if manual_w:
        c.smooth_accel = c.smooth_accel * (1 - alpha_pedals) + 1.0 * alpha_pedals
        c.smooth_brake = 0.0
        R['accel'] = c.smooth_accel
        R['brake'] = c.smooth_brake
        c.manual_pedal_active = True
    elif manual_s:
        if S.get('speedX', 0) < 1.0:
            c.smooth_accel = c.smooth_accel * (1 - alpha_pedals) + 1.0 * alpha_pedals
            c.smooth_brake = 0.0
            R['accel'] = c.smooth_accel
            R['brake'] = c.smooth_brake
            c.manual_pedal_active = True
        else:
            c.smooth_brake = c.smooth_brake * (1 - alpha_pedals) + aero_grip * alpha_pedals
            c.smooth_accel = 0.0
            R['brake'] = c.smooth_brake
            R['accel'] = c.smooth_accel
            c.manual_pedal_active = True
    else:
        if c.manual_pedal_active:
            c.smooth_accel = c.smooth_accel * decay_rate + R['accel'] * (1 - decay_rate)
            c.smooth_brake = c.smooth_brake * decay_rate + R['brake'] * (1 - decay_rate)
            R['accel'] = c.smooth_accel
            R['brake'] = c.smooth_brake
            if abs(c.smooth_accel - R['accel']) < 0.05 and abs(c.smooth_brake - R['brake']) < 0.05:
                c.manual_pedal_active = False
        else:
            c.smooth_accel = R['accel']
            c.smooth_brake = R['brake']

    # --- Sterzo Manuale ---
    if manual_a or manual_d:
        if manual_a:
            target_steer = max_steer_angle
        elif manual_d:
            target_steer = -max_steer_angle
            
        c.smooth_steer = c.smooth_steer * (1 - alpha_steer) + target_steer * alpha_steer
        R['steer'] = clip(c.smooth_steer, -1.0, 1.0)
        c.manual_steer_active = True
    else:
        if c.manual_steer_active:
            c.smooth_steer = c.smooth_steer * decay_rate + R['steer'] * (1 - decay_rate)
            R['steer'] = clip(c.smooth_steer, -1.0, 1.0)
            if abs(c.smooth_steer - R['steer']) < 0.05:
                c.manual_steer_active = False
        else:
            c.smooth_steer = R['steer']

    # === ABS GLOBALE AVANZATO ===
    if R['brake'] > 0:
        steer_penalty = (abs(R['steer']) ** 2) * 0.85
        max_safe_brake = clip(1.0 - steer_penalty, 0.0, aero_grip if 'aero_grip' in locals() else 1.0)
        R['brake'] = min(R['brake'], max_safe_brake)

    # 5. GESTIONE CAMBIO AUTOMATICO
    if not c.manual_gear_active:
        rpm = S.get('rpm', 0)
        speed = S.get('speedX', 0)
        gear = S.get('gear', 1)
        
        if not hasattr(c, 'gear_step'): c.gear_step = 0
        c.gear_step += 1

        if c.gear_step > 10:
            if gear < 6 and rpm > 13000:
                R['gear'] = gear + 1
                c.gear_step = 0
            
            elif gear > 1 and rpm < 6500:
                R['gear'] = gear - 1
                c.gear_step = 0
        
        if gear <= 0 and speed < 5 and not manual_s:
            R['gear'] = 1

        if manual_s and speed < 1.0:
            R['gear'] = -1

    # 6. RECUPERO EMERGENZA
    if c.control_mode == 'auto' and S.get('stucktimer', 0) > 50: 
        R['gear'] = -1           
        R['accel'] = 0.8         
        R['brake'] = 0.0
        R['steer'] = -S.get('angle', 0)
        
    # =======================================================
    # FASE DI LOGGING DEI DATI IN FORMATO JSON ARRAY STANDARD
    # =======================================================
    if 'track' in S and 'wheelSpinVel' in S and 'speedX' in S:
        c.step_count += 1
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
        
        c.log_file.write(json.dumps(record) + "\n")

    return
