import socket
import sys
import getopt
import os
import time
import json
import random
from datetime import datetime
import ctypes
import pygame

# Inizializzazione Pygame per il controller
pygame.init()
pygame.joystick.init()

PI = 3.14159265359
data_size = 2**17

ophelp=  'Options:\n'
ophelp+= ' --host, -H <host>    TORCS server host. [localhost]\n'
ophelp+= ' --port, -p <port>    TORCS port. [3001]\n'
ophelp+= ' --id, -i <id>        ID for server. [SCR]\n'
ophelp+= ' --steps, -m <#>      Maximum simulation steps. 1 sec ~ 50 steps. [100000]\n'
ophelp+= ' --episodes, -e <#>   Maximum learning episodes. [1]\n'
ophelp+= ' --track, -t <track>  Your name for this track. Used for learning. [unknown]\n'
ophelp+= ' --stage, -s <#>      0=warm up, 1=qualifying, 2=race, 3=unknown. [3]\n'
ophelp+= ' --debug, -d          Output full telemetry.\n'
ophelp+= ' --help, -h           Show this help.\n'
ophelp+= ' --version, -v        Show current version.'
usage= 'Usage: %s [ophelp [optargs]] \n' % sys.argv[0]
usage= usage + ophelp
version= "20130505-2-ML-Ready"

def clip(v,lo,hi):
    if v<lo: return lo
    elif v>hi: return hi
    else: return v

def bargraph(x,mn,mx,w,c='X'):
    if not w: return '' 
    if x<mn: x= mn      
    if x>mx: x= mx      
    tx= mx-mn 
    if tx<=0: return 'backwards' 
    upw= tx/float(w) 
    if upw<=0: return 'what?' 
    negpu, pospu, negnonpu, posnonpu= 0,0,0,0
    if mn < 0: 
        if x < 0: 
            negpu= -x + min(0,mx)
            negnonpu= -mn + x
        else: 
            negnonpu= -mn + min(0,mx) 
    if mx > 0: 
        if x > 0: 
            pospu= x - max(0,mn)
            posnonpu= mx - x
        else: 
            posnonpu= mx - max(0,mn) 
    nnc= int(negnonpu/upw)*'-'
    npc= int(negpu/upw)*c
    ppc= int(pospu/upw)*c
    pnc= int(posnonpu/upw)*'_'
    return '[%s]' % (nnc+npc+ppc+pnc)

class Client():
    def __init__(self,H=None,p=None,i=None,e=None,t=None,s=None,d=None,vision=False):
        self.vision = vision

        self.host= 'localhost'
        self.port= 3001
        self.sid= 'SCR'
        self.maxEpisodes=1 
        self.trackname= 'unknown'
        self.stage= 3 
        self.debug= False
        self.maxSteps= 100000 
        self.parse_the_command_line()
        if H: self.host= H
        if p: self.port= p
        if i: self.sid= i
        if e: self.maxEpisodes= e
        if t: self.trackname= t
        if s: self.stage= s
        if d: self.debug= d
        self.S= ServerState()
        self.R= DriverAction()
        
        # --- ML MODIFICATIONS START ---
        
        # 1. GENERAZIONE PERSONALITÀ CASUALE PER ESPLORAZIONE
        # Crea lievi variazioni ad ogni avvio (5-15%) per avere dati eterogenei
        self.bot_profile = {
            'speed_mult': random.uniform(0.95, 1.10), # Quanto spinge sui rettilinei
            'brake_mult': random.uniform(0.85, 1.15), # Quanto frena forte
            'steer_mult': random.uniform(0.90, 1.10), # Quanto è aggressivo sul volante
            'grip_mult':  random.uniform(0.80, 1.20)  # Quanto tollera lo slittamento
        }
        print(f"--- BOT PROFILE GENERATO ---")
        for k, v in self.bot_profile.items():
            print(f"{k}: {v:.3f}")
        
        # 2. SETUP LOGGER JSON LINES IN CARTELLA DEDICATA
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = "log di gara"
        
        # Crea la cartella se non esiste già
        os.makedirs(log_dir, exist_ok=True)
            
        self.log_filename = os.path.join(log_dir, f"telemetry_{timestamp}.jsonl")
        self.log_file = open(self.log_filename, mode='w', encoding='utf-8')
        self.step_count = 0  # Contatore step per il log
        print(f"Logging JSON avviato su: {self.log_filename}")
        
        # Inizializzazione Joystick
        self.joystick = None
        if pygame.joystick.get_count() > 0:
            self.joystick = pygame.joystick.Joystick(0)
            self.joystick.init()
            print(f"--- CONTROLLER RILEVATO: {self.joystick.get_name()} ---")
        else:
            print("--- NESSUN CONTROLLER RILEVATO (Usa Tastiera WASD) ---")
            
        # 3. SELEZIONE MODALITÀ DI GUIDA
        print("\n" + "="*45)
        print("           CONFIGURAZIONE GUIDA")
        print("="*45)
        print(" [1] AI Completa (Automatico + Assistenza)")
        print(" [2] Manuale Assistita (Joypad + Cambio AUTO)")
        print(" [3] Manuale Pura (Joypad + Cambio MANUALE)")
        try:
            scelta = input("\n Scegli modalità (1/2/3) [Default 1]: ").strip()
        except EOFError:
            scelta = '1'
            
        if scelta == '2':
            self.control_mode = 'manual'
            self.auto_gear = True
        elif scelta == '3':
            self.control_mode = 'manual'
            self.auto_gear = False
        else:
            self.control_mode = 'auto'
            self.auto_gear = True
            
        print(f"--- MODALITÀ: {self.control_mode.upper()} | CAMBIO: {'AUTO' if self.auto_gear else 'MANUAL'} ---")
        print("="*45 + "\n")
        
        # --- ML MODIFICATIONS END ---

        self.setup_connection()

    def setup_connection(self):
        try:
            self.so= socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        except socket.error as emsg:
            print('Error: Could not create socket...')
            sys.exit(-1)
        self.so.settimeout(1)

        n_fail = 5
        while True:
            a= "-45 -19 -12 -7 -4 -2.5 -1.7 -1 -.5 0 .5 1 1.7 2.5 4 7 12 19 45"
            initmsg='%s(init %s)' % (self.sid,a)

            try:
                self.so.sendto(initmsg.encode(), (self.host, self.port))
            except socket.error as emsg:
                sys.exit(-1)
            sockdata= str()
            try:
                sockdata,addr= self.so.recvfrom(data_size)
                sockdata = sockdata.decode('utf-8')
            except socket.error as emsg:
                print("Waiting for server on %d............" % self.port)
                print("Count Down : " + str(n_fail))
                if n_fail < 0:
                    print("Se il server e' attivo, questo avviso si risolvera' da solo.")
                    n_fail = 5
                n_fail -= 1

            identify = '***identified***'
            if identify in sockdata:
                print("Client connected on %d.............." % self.port)
                break

    def parse_the_command_line(self):
        try:
            (opts, args) = getopt.getopt(sys.argv[1:], 'H:p:i:m:e:t:s:dhv',
                       ['host=','port=','id=','steps=',
                        'episodes=','track=','stage=',
                        'debug','help','version'])
        except getopt.error as why:
            print('getopt error: %s\n%s' % (why, usage))
            sys.exit(-1)
        try:
            for opt in opts:
                if opt[0] == '-h' or opt[0] == '--help':
                    print(usage)
                    sys.exit(0)
                if opt[0] == '-d' or opt[0] == '--debug':
                    self.debug= True
                if opt[0] == '-H' or opt[0] == '--host':
                    self.host= opt[1]
                if opt[0] == '-i' or opt[0] == '--id':
                    self.sid= opt[1]
                if opt[0] == '-t' or opt[0] == '--track':
                    self.trackname= opt[1]
                if opt[0] == '-s' or opt[0] == '--stage':
                    self.stage= int(opt[1])
                if opt[0] == '-p' or opt[0] == '--port':
                    self.port= int(opt[1])
                if opt[0] == '-e' or opt[0] == '--episodes':
                    self.maxEpisodes= int(opt[1])
                if opt[0] == '-m' or opt[0] == '--steps':
                    self.maxSteps= int(opt[1])
                if opt[0] == '-v' or opt[0] == '--version':
                    print('%s %s' % (sys.argv[0], version))
                    sys.exit(0)
        except ValueError as why:
            print('Bad parameter \'%s\' for option %s: %s\n%s' % (
                                       opt[1], opt[0], why, usage))
            sys.exit(-1)
        if len(args) > 0:
            print('Superflous input? %s\n%s' % (', '.join(args), usage))
            sys.exit(-1)

    def get_servers_input(self):
        if not self.so: return
        sockdata= str()

        while True:
            try:
                sockdata,addr= self.so.recvfrom(data_size)
                sockdata = sockdata.decode('utf-8')
            except socket.error as emsg:
                print('.', end=' ')
            if '***identified***' in sockdata:
                print("Client connected on %d.............." % self.port)
                continue
            elif '***shutdown***' in sockdata:
                print((("Server has stopped the race on %d. "+
                        "You were in %d place.") %
                        (self.port,self.S.d.get('racePos', 0))))
                self.shutdown()
                return
            elif '***restart***' in sockdata:
                print("Server has restarted the race on %d." % self.port)
                self.shutdown()
                return
            elif not sockdata: 
                continue       
            else:
                self.S.parse_server_str(sockdata)
                if self.debug:
                    sys.stderr.write("\x1b[2J\x1b[H") 
                    print(self.S)
                break 

    def respond_to_server(self):
        if not self.so: return
        try:
            message = repr(self.R)
            self.so.sendto(message.encode(), (self.host, self.port))
        except socket.error as emsg:
            print("Error sending to server: %s Message %s" % (emsg[1],str(emsg[0])))
            sys.exit(-1)
        if self.debug: print(self.R.fancyout())

    def shutdown(self):
        if not self.so: return
        print(("Race terminated or %d steps elapsed. Shutting down %d."
               % (self.maxSteps,self.port)))
        self.so.close()
        self.so = None
        # Chiude il file JSON in modo sicuro per salvare tutti i dati raccolti
        if self.log_file and not self.log_file.closed:
            self.log_file.close()
            print(f"Log JSON salvato con successo in: {self.log_filename}")
            print(f"Totale step registrati: {self.step_count}")

class ServerState():
    def __init__(self):
        self.servstr= str()
        self.d= dict()

    def parse_server_str(self, server_string):
        self.servstr= server_string.strip()[:-1]
        sslisted= self.servstr.strip().lstrip('(').rstrip(')').split(')(')
        for i in sslisted:
            w= i.split(' ')
            self.d[w[0]]= destringify(w[1:])

class DriverAction():
    def __init__(self):
       self.actionstr= str()
       self.d= { 'accel':0.2,
                   'brake':0,
                  'clutch':0,
                    'gear':1,
                   'steer':0,
                   'focus':[-90,-45,0,45,90],
                    'meta':0
                    }

    def clip_to_limits(self):
        self.d['steer']= clip(self.d['steer'], -1, 1)
        self.d['brake']= clip(self.d['brake'], 0, 1)
        self.d['accel']= clip(self.d['accel'], 0, 1)
        self.d['clutch']= clip(self.d['clutch'], 0, 1)
        if self.d['gear'] not in [-1, 0, 1, 2, 3, 4, 5, 6]:
            self.d['gear']= 0
        if self.d['meta'] not in [0,1]:
            self.d['meta']= 0
        if type(self.d['focus']) is not list or min(self.d['focus'])<-180 or max(self.d['focus'])>180:
            self.d['focus']= 0

    def __repr__(self):
        self.clip_to_limits()
        out= str()
        for k in self.d:
            out+= '('+k+' '
            v= self.d[k]
            if not type(v) is list:
                out+= '%.3f' % v
            else:
                out+= ' '.join([str(x) for x in v])
            out+= ')'
        return out

def destringify(s):
    if not s: return s
    if type(s) is str:
        try:
            return float(s)
        except ValueError:
            return s
    elif type(s) is list:
        if len(s) < 2:
            return destringify(s[0])
        else:
            return [destringify(i) for i in s]

def drive_example(c):
    '''Bot Fluido con variazione di profilo ML e Logging'''
    S, R = c.S.d, c.R.d
    P = c.bot_profile  # Prende i moltiplicatori generati per QUESTA gara

    if c.control_mode == 'auto':
        # 1. ANALISI DEL TRACCIATO (Traiettoria centrata fluida)
        look_ahead = max(S['track'][7:12])
        
        # 2. CALCOLO DELLA VELOCITÀ TARGET E STACCATA
        # Moltiplicatore alzato a 2.3 per fare le curve in modo molto più veloce e aggressivo
        if look_ahead > 160:
            target_speed = 330.0 * P['speed_mult']
        else:
            target_speed = (look_ahead * 2.3) * P['speed_mult']

        # Nessuna frenata brusca sul cordolo interno: penalità leggera solo sull'estremo limite (0.95)
        if abs(S['trackPos']) > 0.95:
            target_speed = min(target_speed, 250.0)

        # === COMPORTAMENTO FUORI PISTA ===
        # Aumentata la soglia a 1.05 così il bot può usare liberamente tutti i cordoli senza rallentare
        is_off_track = abs(S['trackPos']) >= 1.05
        if is_off_track:
            # Se è fuori pista la priorità è rallentare per non scivolare sull'erba/sabbia
            target_speed = 40.0 
            if abs(S['angle']) > 0.7: 
                target_speed = 20.0 # Se è molto storto, va a passo d'uomo per girarsi in sicurezza

        # === CONTROLLO SBANDATA (SKID) E CONTROSTERZO ===
        # Soglie leggermente alzate per evitare falsi positivi sui cordoli (che facevano bloccare l'auto)
        is_skidding = abs(S.get('speedY', 0)) > 5.0 or (abs(S['angle']) > 0.45 and S['speedX'] > 60.0)

        # 3. CONTROLLO STERZO (Influenzato da steer_mult)
        if is_off_track:
            # Recupero fuoripista: sterza verso il centro stabilizzando l'angolo per non derapare
            steer_target = (S['angle'] * 0.9) - (S['trackPos'] * 0.4)
        elif is_skidding:
            # Recupero sbandata: controsterzo aggressivo e rapido ignorando quasi del tutto il centro pista
            steer_target = (S['angle'] * 1.5) - (S['trackPos'] * 0.1)
        else:
            # In pista: tollerante se non è al centro (correzione cubica invece che lineare)
            # Così se lo sposti lateralmente manualmente, non "lotterà" per tornare al centro esatto
            track_correction = (S['trackPos'] ** 3) * 0.8 * P['steer_mult']
            steer_target = (S['angle'] * 0.8 * P['steer_mult']) - track_correction
            
        R['steer'] = clip(steer_target, -1.0, 1.0)

        # 4. ACCELERATORE E FRENO
        speed_error = target_speed - S['speedX']

        if speed_error > 0:
            max_accel = 1.0 - (abs(R['steer']) * 0.5) 
            R['accel'] = clip(speed_error / 20.0, 0.0, max_accel)
            R['brake'] = 0.0
            
            # Traction Control (Influenzato da grip_mult)
            spin_diff = (S['wheelSpinVel'][2] + S['wheelSpinVel'][3]) - (S['wheelSpinVel'][0] + S['wheelSpinVel'][1])
            if spin_diff > (2.0 * P['grip_mult']):  
                R['accel'] *= 0.6 
            if is_skidding:
                R['accel'] *= 0.3 # Taglia nettamente il gas per ridare grip alle ruote posteriori
        else:
            R['accel'] = 0.0
            max_brake = 1.0 - (abs(R['steer']) * 0.4)
            # Frenata molto più brusca e reattiva: basta un eccesso di 15 km/h per applicare il freno massimo
            R['brake'] = clip(-speed_error / (15.0 / P['brake_mult']), 0.0, max_brake)

        if S['speedX'] < 5.0 and target_speed > 10.0:
            R['accel'] = 1.0
            R['brake'] = 0.0
    else:
        # Modalità Manuale: i comandi base partono da 0 e vengono poi gestiti dall'override
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
        # Il cambio parte automatico se richiesto, ma diventa manuale al primo tocco dei tasti
        c.manual_gear_active = not c.auto_gear

    manual_w = (ctypes.windll.user32.GetAsyncKeyState(0x57) & 0x8000) != 0
    manual_s = (ctypes.windll.user32.GetAsyncKeyState(0x53) & 0x8000) != 0
    manual_a = (ctypes.windll.user32.GetAsyncKeyState(0x41) & 0x8000) != 0
    manual_d = (ctypes.windll.user32.GetAsyncKeyState(0x44) & 0x8000) != 0

    # --- INPUT DA CONTROLLER (JOYSTICK) ---
    joy_active = False
    joy_steer = 0.0
    joy_accel = 0.0
    joy_brake = 0.0
    
    if c.joystick:
        pygame.event.pump()
        # Sterzo (Stick Sinistro)
        joy_steer = c.joystick.get_axis(0)
        
        # Acceleratore e Freno (Trigger su Windows spesso sono assi 4 e 5 o asse 2)
        # Mapping tipico Xbox su Windows: 4=LT, 5=RT
        # I trigger partono da -1.0 e vanno a 1.0
        rt = c.joystick.get_axis(5)
        lt = c.joystick.get_axis(4)
        
        # Normalizzazione: se il valore è vicino a 0 all'inizio (non ancora toccato), lo forziamo a 0
        # Altrimenti mappiamo da [-1, 1] a [0, 1]
        joy_accel = (rt + 1.0) / 2.0 if abs(rt) > 0.01 or rt != 0 else 0.0
        joy_brake = (lt + 1.0) / 2.0 if abs(lt) > 0.01 or lt != 0 else 0.0
        
        # Soglia di attivazione (Deadzone)
        if abs(joy_steer) > 0.1 or joy_accel > 0.1 or joy_brake > 0.1:
            joy_active = True
            
        # Gestione Marce Manuale (Cerchio per salire, X per scendere)
        if c.joystick.get_button(1): # Cerchio (Circle / B)
            if not hasattr(c, 'last_joy_up') or not c.last_joy_up:
                R['gear'] = min(R['gear'] + 1, 6)
                c.last_joy_up = True
                c.manual_gear_active = True # Attiva il controllo manuale permanente
        else:
            c.last_joy_up = False
            
        if c.joystick.get_button(0): # X (Cross / A)
            if not hasattr(c, 'last_joy_down') or not c.last_joy_down:
                R['gear'] = max(R['gear'] - 1, -1)
                c.last_joy_down = True
                c.manual_gear_active = True # Attiva il controllo manuale permanente
        else:
            c.last_joy_down = False

    # === MODELLO FISICO AVANZATO (Ispirato a IBM Granite 4.1:8b per TORCS) ===
    speed_factor = max(1.0, S['speedX'])
    
    # 1. Modello Aerodinamico (Downforce): A 300km/h l'aria schiaccia l'auto, permettendo molta frenata.
    # A 50 km/h la downforce è assente, e una frenata eccessiva bloccherebbe le ruote.
    aero_grip = clip(0.4 + (speed_factor / 280.0)**2, 0.4, 1.0)
    
    # 2. Sensibilità dello Sterzo Dinamica (Speed-Sensitivity)
    # La sterzata massima manuale decresce iperbolicamente con la velocità per impedire testacoda ad alte velocità.
    max_steer_angle = clip(120.0 / speed_factor, 0.15, 1.0)
    
    alpha_steer = 0.25   # Reattività aumentata, ma protetta fisicamente da max_steer_angle
    alpha_pedals = 0.4   # Reattività pedali
    decay_rate = 0.85    # Ritorno fluido al bot

    # --- Pedali ---
    if manual_w or joy_accel > 0.1:
        accel_val = 1.0 if manual_w else joy_accel
        c.smooth_accel = c.smooth_accel * (1 - alpha_pedals) + accel_val * alpha_pedals
        c.smooth_brake = 0.0
        R['accel'] = c.smooth_accel
        R['brake'] = c.smooth_brake
        c.manual_pedal_active = True
    elif manual_s or joy_brake > 0.1:
        if S.get('speedX', 0) < 1.0:
            # Retromarcia da fermo o mentre si va già indietro
            accel_val = 1.0 if manual_s else joy_brake
            c.smooth_accel = c.smooth_accel * (1 - alpha_pedals) + accel_val * alpha_pedals
            c.smooth_brake = 0.0
            R['accel'] = c.smooth_accel
            R['brake'] = c.smooth_brake
            c.manual_pedal_active = True
        else:
            # Frena sfruttando al massimo l'aderenza aerodinamica calcolata (aero_grip) invece di bloccare a 1.0
            brake_val = aero_grip if manual_s else joy_brake
            c.smooth_brake = c.smooth_brake * (1 - alpha_pedals) + brake_val * alpha_pedals
            c.smooth_accel = 0.0
            R['brake'] = c.smooth_brake
            R['accel'] = c.smooth_accel
            c.manual_pedal_active = True
    else:
        if c.manual_pedal_active:
            # Sfuma dolcemente verso le decisioni del bot
            c.smooth_accel = c.smooth_accel * decay_rate + R['accel'] * (1 - decay_rate)
            c.smooth_brake = c.smooth_brake * decay_rate + R['brake'] * (1 - decay_rate)
            R['accel'] = c.smooth_accel
            R['brake'] = c.smooth_brake
            if abs(c.smooth_accel - R['accel']) < 0.05 and abs(c.smooth_brake - R['brake']) < 0.05:
                c.manual_pedal_active = False
        else:
            # Il bot ha controllo totale, tieni aggiornati i valori smooth
            c.smooth_accel = R['accel']
            c.smooth_brake = R['brake']

    # --- Sterzo Manuale ---
    if manual_a or manual_d or abs(joy_steer) > 0.1:
        if manual_a:
            target_steer = max_steer_angle
        elif manual_d:
            target_steer = -max_steer_angle
        else:
            # Joystick: lo sterzo è già analogico, lo moltiplichiamo per l'angolo massimo sicuro
            target_steer = -joy_steer * max_steer_angle
            
        c.smooth_steer = c.smooth_steer * (1 - alpha_steer) + target_steer * alpha_steer
        R['steer'] = clip(c.smooth_steer, -1.0, 1.0)
        c.manual_steer_active = True
    else:
        if c.manual_steer_active:
            # Sfuma dolcemente verso la traiettoria del bot
            c.smooth_steer = c.smooth_steer * decay_rate + R['steer'] * (1 - decay_rate)
            R['steer'] = clip(c.smooth_steer, -1.0, 1.0)
            if abs(c.smooth_steer - R['steer']) < 0.05:
                c.manual_steer_active = False
        else:
            # Il bot ha controllo totale
            c.smooth_steer = R['steer']

    # === ABS GLOBALE AVANZATO (Combined Slip Physics) ===
    # Usa una curva quadratica: permette più frenata per piccoli angoli di sterzo, 
    # ma toglie drasticamente i freni ad angoli di sterzo elevati per preservare l'aderenza laterale.
    if R['brake'] > 0:
        steer_penalty = (abs(R['steer']) ** 2) * 0.85
        max_safe_brake = clip(1.0 - steer_penalty, 0.0, aero_grip if 'aero_grip' in locals() else 1.0)
        R['brake'] = min(R['brake'], max_safe_brake)

    # 5. GESTIONE CAMBIO AUTOMATICO (Ottimizzata RPM)
    if not c.manual_gear_active:
        rpm = S.get('rpm', 0)
        speed = S.get('speedX', 0)
        gear = S.get('gear', 1)
        
        # Inizializza un contatore per evitare cambiate troppo rapide (oscillazioni)
        if not hasattr(c, 'gear_step'): c.gear_step = 0
        c.gear_step += 1

        # Cambia marcia solo ogni 10 frame (circa 0.2s) per stabilità ad alti RPM
        if c.gear_step > 10:
            # Upshift (Salita): Impostato a 10500 RPM come richiesto
            if gear < 6 and rpm > 10500:
                R['gear'] = gear + 1
                c.gear_step = 0
            
            # Downshift (Scalata): Impostato a 6500 RPM come richiesto
            elif gear > 1 and rpm < 6500:
                R['gear'] = gear - 1
                c.gear_step = 0
        
        # Gestione partenza: se siamo in folle o fermi, metti la prima
        if gear <= 0 and speed < 5 and not manual_s:
            R['gear'] = 1

        # Override per retromarcia (Tasto S o freno da fermo)
        if manual_s and speed < 1.0:
            R['gear'] = -1

    # 6. RECUPERO EMERGENZA (Solo in modalità Auto)
    if c.control_mode == 'auto' and S.get('stucktimer', 0) > 50: 
        R['gear'] = -1           
        R['accel'] = 0.8         
        R['brake'] = 0.0
        R['steer'] = -S.get('angle', 0)
        
    # =======================================================
    # FASE DI LOGGING DEI DATI IN FORMATO JSON LINES
    # =======================================================
    # Registra solo se la gara è in corso (dati sensori presenti)
    if 'track' in S and 'wheelSpinVel' in S and 'speedX' in S:
        c.step_count += 1
        record = {
            # --- Metadati ---
            "step":        c.step_count,
            "mode":        c.control_mode,
            "profile":     c.bot_profile,

            # --- Stato Vettura ---
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

            # --- Sensori di Distanza (19 raggi) ---
            "track":       [round(v, 3) for v in S['track']],

            # --- Dinamica Ruote ---
            "wheelSpinVel": [round(v, 3) for v in S['wheelSpinVel']],

            # --- Comandi (Label per ML) ---
            "cmd": {
                "steer": round(R['steer'], 5),
                "accel": round(R['accel'], 5),
                "brake": round(R['brake'], 5),
                "gear":  int(R['gear'])
            }
        }
        # Scrittura JSON Lines: un oggetto JSON per riga
        c.log_file.write(json.dumps(record, separators=(',', ':')) + '\n')

    return

if __name__ == "__main__":
    C= Client(p=3001)
    for step in range(C.maxSteps,0,-1):
        C.get_servers_input()
        if not C.so: 
            break # Esce se il server ha chiuso la connessione
        drive_example(C)
        C.respond_to_server()
    C.shutdown()