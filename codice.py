import socket
import sys
import getopt
import os
import time
import csv
import random
from datetime import datetime

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
        
        # 2. SETUP LOGGER CSV
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_filename = f"telemetry_{timestamp}.csv"
        self.log_file = open(self.log_filename, mode='w', newline='')
        self.csv_writer = csv.writer(self.log_file)
        
        # Scrittura dell'intestazione (Header)
        header = ['speedX', 'speedY', 'speedZ', 'angle', 'trackPos', 'rpm', 'gear_state']
        header += [f'track_{i}' for i in range(19)]
        header += [f'wheelSpin_{i}' for i in range(4)]
        header += ['CMD_steer', 'CMD_accel', 'CMD_brake', 'CMD_gear'] # Gli output da predirre
        self.csv_writer.writerow(header)
        print(f"Logging dati avviato su: {self.log_filename}")
        
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
        # Chiude il file CSV in modo sicuro per salvare tutti i dati raccolti
        if self.log_file and not self.log_file.closed:
            self.log_file.close()
            print(f"Log salvato con successo in {self.log_filename}")

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

    # 1. ANALISI DEL TRACCIATO (Traiettoria centrata fluida)
    look_ahead = max(S['track'][7:12])
    
    # 2. CALCOLO DELLA VELOCITÀ TARGET (Influenzato da speed_mult)
    if look_ahead > 140:
        target_speed = 300.0 * P['speed_mult']
    else:
        target_speed = (look_ahead * 2.0) * P['speed_mult']

    if abs(S['trackPos']) > 0.85:
        target_speed = min(target_speed, 130.0)

    # 3. CONTROLLO STERZO (Influenzato da steer_mult)
    steer_target = (S['angle'] * 0.8 * P['steer_mult']) - (S['trackPos'] * 0.5 * P['steer_mult'])
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
    else:
        R['accel'] = 0.0
        max_brake = 1.0 - (abs(R['steer']) * 0.4)
        # Frenata (Influenzata da brake_mult)
        R['brake'] = clip(-speed_error / (30.0 / P['brake_mult']), 0.0, max_brake)

    if S['speedX'] < 5.0 and target_speed > 10.0:
        R['accel'] = 1.0
        R['brake'] = 0.0

    # 5. GESTIONE CAMBIO AUTOMATICO (Basato sulla velocità per evitare salti di marcia)
    speed = S.get('speedX', 0)

    if speed < 50:
        R['gear'] = 1
    elif speed < 95:
        R['gear'] = 2
    elif speed < 145:
        R['gear'] = 3
    elif speed < 195:
        R['gear'] = 4
    elif speed < 240:
        R['gear'] = 5
    else:
        R['gear'] = 6

    # 6. RECUPERO EMERGENZA
    if S.get('stucktimer', 0) > 50: 
        R['gear'] = -1           
        R['accel'] = 0.8         
        R['brake'] = 0.0
        R['steer'] = -S.get('angle', 0)
        
    # =======================================================
    # FASE DI LOGGING DEI DATI PER IL MACHINE LEARNING
    # =======================================================
    # Registra solo se la gara è in corso (escludiamo i primissimi istanti non validi)
    if 'track' in S and 'wheelSpinVel' in S and 'speedX' in S:
        row = [
            S['speedX'], S['speedY'], S.get('speedZ', 0), 
            S.get('angle', 0), S.get('trackPos', 0), 
            S.get('rpm', 0), S.get('gear', 0)
        ]
        # Aggiungiamo tutti i 19 sensori di distanza
        row.extend(S['track'])
        # Aggiungiamo tutti e 4 i sensori delle ruote
        row.extend(S['wheelSpinVel'])
        # Aggiungiamo i target decisi dal pilota (Le etichette/label da far imparare alla rete neurale)
        row.extend([R['steer'], R['accel'], R['brake'], R['gear']])
        
        # Scriviamo la riga nel file CSV
        c.csv_writer.writerow(row)

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