import socket
import sys
import getopt
import os
import time
import csv
import random
from datetime import datetime
import ctypes
import getpass

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

import getpass # Aggiunto per identificare l'utente

import socket
import sys
import getopt
import os
import time
import csv
import random
import json
import getpass
from datetime import datetime

class Client():
    def __init__(self, H=None, p=None, i=None, e=None, t=None, s=None, d=None, vision=False):
        self.vision = vision

        # Configurazione di default
        self.host = 'localhost'
        self.port = 3001
        self.sid = 'SCR'
        self.maxEpisodes = 1 
        self.trackname = 'unknown'
        self.stage = 3 
        self.debug = False
        self.maxSteps = 100000 
        
        self.parse_the_command_line()
        
        # Override parametri se passati esplicitamente
        if H: self.host = H
        if p: self.port = p
        if i: self.sid = i
        if e: self.maxEpisodes = e
        if t: self.trackname = t
        if s: self.stage = s
        if d: self.debug = d
        
        self.S = ServerState()
        self.R = DriverAction()
        
        # --- ML & GROUP JSON CONFIGURATION ---
        
        # 1. Identificazione Utente (automatico dal sistema operativo)
        self.user_identity = getpass.getuser()
        
        # 2. Setup Cartella e File di Log
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = "log_gruppo_json"
        
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        # Usiamo .jsonl: ogni riga è un oggetto JSON indipendente (più sicuro contro i crash)
        self.log_filename = os.path.join(log_dir, f"log_{self.user_identity}_{timestamp}.jsonl")
        self.log_file = open(self.log_filename, mode='w', encoding='utf-8')
        
        print(f"\n--- SESSIONE AVVIATA ---")
        print(f"UTENTE: {self.user_identity}")
        print(f"LOG:    {self.log_filename}")
        print(f"------------------------\n")
        
        # --- FINE CONFIGURAZIONE ---

        self.setup_connection()

    def setup_connection(self):
        try:
            self.so = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        except socket.error as emsg:
            print('Error: Could not create socket...')
            sys.exit(-1)
        self.so.settimeout(1)

        n_fail = 5
        while True:
            a = "-45 -19 -12 -7 -4 -2.5 -1.7 -1 -.5 0 .5 1 1.7 2.5 4 7 12 19 45"
            initmsg = '%s(init %s)' % (self.sid, a)

            try:
                self.so.sendto(initmsg.encode(), (self.host, self.port))
            except socket.error as emsg:
                sys.exit(-1)
            
            sockdata = str()
            try:
                sockdata, addr = self.so.recvfrom(data_size)
                sockdata = sockdata.decode('utf-8')
            except socket.error as emsg:
                print("Waiting for server on %d............" % self.port)
                if n_fail < 0:
                    print("Assicurati che TORCS sia in modalità 'Race' o 'Practice'.")
                    n_fail = 5
                n_fail -= 1

            if '***identified***' in sockdata:
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
                    print(usage); sys.exit(0)
                if opt[0] == '-d' or opt[0] == '--debug':
                    self.debug = True
                if opt[0] == '-H' or opt[0] == '--host':
                    self.host = opt[1]
                if opt[0] == '-i' or opt[0] == '--id':
                    self.sid = opt[1]
                if opt[0] == '-t' or opt[0] == '--track':
                    self.trackname = opt[1]
                if opt[0] == '-s' or opt[0] == '--stage':
                    self.stage = int(opt[1])
                if opt[0] == '-p' or opt[0] == '--port':
                    self.port = int(opt[1])
                if opt[0] == '-e' or opt[0] == '--episodes':
                    self.maxEpisodes = int(opt[1])
                if opt[0] == '-m' or opt[0] == '--steps':
                    self.maxSteps = int(opt[1])
                if opt[0] == '-v' or opt[0] == '--version':
                    print('%s %s' % (sys.argv[0], version)); sys.exit(0)
        except ValueError as why:
            print('Bad parameter \'%s\' for option %s: %s\n%s' % (opt[1], opt[0], why, usage))
            sys.exit(-1)

    def get_servers_input(self):
        if not self.so: return
        sockdata = str()

        while True:
            try:
                sockdata, addr = self.so.recvfrom(data_size)
                sockdata = sockdata.decode('utf-8')
            except socket.error as emsg:
                print('.', end=' ')
                
            if '***identified***' in sockdata:
                continue
            elif '***shutdown***' in sockdata:
                print(f"\nServer ha chiuso la gara. Posizione: {self.S.d.get('racePos', 0)}")
                self.shutdown()
                return
            elif '***restart***' in sockdata:
                print("\nRestart della gara...")
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
        
        # --- JSON LOGGING ---
        try:
            S, R = self.S.d, self.R.d
            log_entry = {
                "user": self.user_identity,
                "timestamp": time.time(),
                "sensors": {
                    "speedX": S.get('speedX', 0.0),
                    "speedY": S.get('speedY', 0.0),
                    "angle": S.get('angle', 0.0),
                    "trackPos": S.get('trackPos', 0.0),
                    "rpm": S.get('rpm', 0.0),
                    "track": S.get('track', [0.0]*19)
                },
                "actions": {
                    "steer": R['steer'],
                    "accel": R['accel'],
                    "brake": R['brake'],
                    "gear": R['gear']
                }
            }
            self.log_file.write(json.dumps(log_entry) + "\n")
        except Exception as e:
            if self.debug: print(f"Errore scrittura JSON: {e}")

        # Invio messaggio al server
        try:
            message = repr(self.R)
            self.so.sendto(message.encode(), (self.host, self.port))
        except socket.error as emsg:
            print("Error sending to server: %s" % str(emsg))
            sys.exit(-1)

    def shutdown(self):
        if not self.so: return
        print(f"Chiusura in corso. Risorse liberate.")
        
        if self.log_file and not self.log_file.closed:
            self.log_file.flush()
            self.log_file.close()
            
        self.so.close()
        self.so = None

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
    S, R = c.S.d, c.R.d

    speed = S.get('speedX', 0.0)
    angle = S.get('angle', 0.0)
    trackPos = S.get('trackPos', 0.0)
    track = S.get('track', [100.0]*19)
    rpm = S.get('rpm', 0.0)

    # --- 1. STERZO DINAMICO ---
    # Più siamo veloci, più i movimenti devono essere chirurgici
    steer_lock = 0.3 if speed > 100 else 0.7 
    desired_steer = (angle - trackPos * 0.25) / steer_lock
    
    if not hasattr(c, "steer_mem"): c.steer_mem = 0.0
    c.steer_mem = 0.7 * c.steer_mem + 0.3 * desired_steer
    R['steer'] = clip(c.steer_mem, -1.0, 1.0)

    # --- 2. LOGICA DI VELOCITÀ AGGRESSIVA ---
    # Guardiamo i sensori a 10 gradi (indici 8 e 10) per anticipare la curva
    dist_ahead = track[9]
    dist_left = track[8]
    dist_right = track[10]
    
    # Se i sensori laterali sono molto più corti di quello centrale, la curva è secca
    curve_factor = min(dist_left, dist_right)
    
    if dist_ahead > 150:
        target_speed = 280.0  # Rettilineo: punta al massimo
    elif dist_ahead > 80:
        target_speed = 180.0  # Curva veloce
    else:
        # Formula dinamica per le curve: più spazio c'è, più corri
        target_speed = 30.0 + (curve_factor * 1.5)

    # --- 3. ACCELERAZIONE E TRAZIONE ---
    # Permettiamo più gas anche se stiamo sterzando (fino a un certo punto)
    # Se la velocità è bassa, usiamo un launch control per non pattinare
    if speed < 50:
        accel_limit = 0.8 # Evita wheelspin in partenza
    else:
        accel_limit = 1.0 - abs(R['steer']) * 0.5 # Più aggressivo di prima (era 0.8)

    if speed < target_speed:
        R['accel'] = clip(accel_limit, 0.0, 1.0)
        R['brake'] = 0.0
    else:
        R['accel'] = 0.0
        # Frena forte solo se siamo molto sopra il target
        R['brake'] = clip((speed - target_speed) / 20.0, 0.0, 0.8)

    # --- 4. CAMBIO RACING ---
    # Portiamo le marce quasi al limitatore per massimizzare la spinta
    if rpm > 8500: # Cambiata più alta
        R['gear'] = clip(S.get('gear', 1) + 1, 1, 6)
    elif rpm < 3500 and S.get('gear', 1) > 1:
        R['gear'] = clip(S.get('gear', 1) - 1, 1, 6)
if __name__ == "__main__":
    C= Client(p=3001)
    for step in range(C.maxSteps,0,-1):
        C.get_servers_input()
        if not C.so: 
            break # Esce se il server ha chiuso la connessione
        drive_example(C)
        C.respond_to_server()
    C.shutdown()