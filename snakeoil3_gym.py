# snakeoil3_gym.py
# Libreria di interfacciamento con il simulatore TORCS

# Moduli standard Python per operazioni base
import socket # Gestione delle comunicazioni di rete UDP con TORCS
import os     # Interazione col sistema operativo (creazione/lettura file, path)
import time   # Modulo per la gestione dei ritardi (sleep) e conteggio del tempo

PI = 3.14159265359

# Grandezza del buffer UDP
data_size = 2**17

def clip(v, lo, hi):

    # Limita il valore numerico v tagliandolo tra i margini lo (basso) e hi (alto).
    # Viene usato costantemente per assicurarsi che i comandi come lo sterzo non superino [-1.0, 1.0].
    if v < lo: return lo
    elif v > hi: return hi
    else: return v

def destringify(s):

    # Converte ricorsivamente i pacchetti dati testuali inviati dal server in numeri (float) o liste di numeri.
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

class Client():
    
    # Client UDP che avvolge tutta la logica di connessione fisica ai server TORCS.
    
    def __init__(self, H='localhost', p=3001, i='SCR', e=1, t='unknown', s=3, d=False, vision=False):
        self.vision = vision
        self.host = H
        self.port = p
        self.sid = i
        self.maxEpisodes = e
        self.trackname = t
        self.stage = s 
        self.debug = d
        self.maxSteps = 100000
        
        # ServerState (Sensori) e DriverAction (Comandi)
        self.S = ServerState()
        self.R = DriverAction()
        
        self.setup_connection()

    def setup_connection(self):

        # Imposta la socket (AF_INET = IPv4, SOCK_DGRAM = UDP) e invia il comando di 'init'.
        try:
            self.so = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        except socket.error:
            print('[ERRORE] Impossibile creare la socket UDP.')
            return
            
        self.so.settimeout(1)
        n_fail = 5
        
        while True:
            # Gli angoli che chiediamo a TORCS di campionare tramite i suoi "laser" frontali
            a = "-45 -19 -12 -7 -4 -2.5 -1.7 -1 -.5 0 .5 1 1.7 2.5 4 7 12 19 45"
            initmsg = f"{self.sid}(init {a})"

            try:
                self.so.sendto(initmsg.encode(), (self.host, self.port))
            except socket.error:
                return
                
            sockdata = ""
            try:
                sockdata, addr = self.so.recvfrom(data_size)
                sockdata = sockdata.decode('utf-8')
            except socket.error:
                print(f"In attesa del server sulla porta {self.port}...")
                if n_fail < 0:
                    print("Riavvio TORCS automatico...")
                    os.system('pkill torcs')
                    time.sleep(1.0)
                    if not self.vision:
                        os.system('torcs -nofuel -nodamage -nolaptime &')
                    else:
                        os.system('torcs -nofuel -nodamage -nolaptime -vision &')
                    time.sleep(1.0)
                    os.system('sh autostart.sh')
                    n_fail = 5
                n_fail -= 1

            if '***identified***' in sockdata:
                print(f"[TORCS] Client connesso sulla porta {self.port}.")
                break

    def get_servers_input(self):

        # Legge i pacchetti grezzi ricevuti dalla socket UDP e avvia il parse se sono sensori di stato.
        if not self.so: return
        
        while True:
            try:
                sockdata, addr = self.so.recvfrom(data_size)
                sockdata = sockdata.decode('utf-8')
            except socket.error:
                continue
                
            if '***identified***' in sockdata:
                continue
            elif '***shutdown***' in sockdata:
                print("[TORCS] Il server ha interrotto la gara.")
                self.shutdown()
                return
            elif '***restart***' in sockdata:
                print("[TORCS] Il server ha riavviato la gara.")
                self.shutdown()
                return
            elif not sockdata:
                continue
            else:
                self.S.parse_server_str(sockdata)
                break

    def respond_to_server(self):

        # Trasforma l'oggetto DriverAction in formato testuale TORCS-style (brake 0)(accel 1) e lo spedisce via socket.
        if not self.so: return
        try:
            message = repr(self.R)
            self.so.sendto(message.encode(), (self.host, self.port))
        except socket.error as emsg:
            print(f"[ERRORE] Invio fallito: {emsg}")

    def shutdown(self):

        # Smantella e chiude correttamente la porta UDP.
        if not self.so: return
        self.so.close()
        self.so = None

class ServerState():
    
    # Contiene l'intero vocabolario e i valori dei sensori restituiti in tempo reale da TORCS (velocità, pista, rpm, ecc).
    
    def __init__(self):
        self.servstr = ""
        self.d = {}

    def parse_server_str(self, server_string):

        # Taglia le parentesi esterne dalla stringa di TORCS, la divide in liste di variabili e popola il dizionario interno `self.d`.
        self.servstr = server_string.strip()[:-1]
        sslisted = self.servstr.strip().lstrip('(').rstrip(')').split(')(')
        for i in sslisted:
            w = i.split(' ')
            self.d[w[0]] = destringify(w[1:])

class DriverAction():
    
    # Raccoglie i comandi calcolati e li prepara in un dizionario. Contiene le regole fisiche del simulatore.
    
    def __init__(self):
        self.d = {
            'accel': 0.0,
            'brake': 0.0,
            'clutch': 0.0,
            'gear': 1,
            'steer': 0.0,
            'focus': [-90, -45, 0, 45, 90],
            'meta': 0
        }

    def clip_to_limits(self):

        # Effettua un check incrociato chiamando clip() sui pedali per evitare il crash del client in caso di rete che invia valori folli.
        self.d['steer'] = clip(self.d['steer'], -1, 1)
        self.d['brake'] = clip(self.d['brake'], 0, 1)
        self.d['accel'] = clip(self.d['accel'], 0, 1)
        self.d['clutch'] = clip(self.d['clutch'], 0, 1)
        
        if self.d['gear'] not in [-1, 0, 1, 2, 3, 4, 5, 6]:
            self.d['gear'] = 0
        if self.d['meta'] not in [0, 1]:
            self.d['meta'] = 0
        if type(self.d['focus']) is not list or min(self.d['focus']) < -180 or max(self.d['focus']) > 180:
            self.d['focus'] = 0

    def __repr__(self):

        # Scatena prima `clip_to_limits` e poi riassembla la stringa come TORCS UDP richiede.
        self.clip_to_limits()
        out = ""
        for k, v in self.d.items():
            out += f"({k} "
            if type(v) is not list:
                out += f"{v:.3f}"
            else:
                out += " ".join(str(x) for x in v)
            out += ")"
        return out
