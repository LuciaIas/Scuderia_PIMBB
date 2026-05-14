
import socket
import sys
import getopt
import os
import time
PI= 3.14159265359

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
version= "20130505-2"

def clip(v,lo,hi):
    if v<lo: return lo
    elif v>hi: return hi
    else: return v

def bargraph(x,mn,mx,w,c='X'):
    '''Draws a simple asciiart bar graph. Very handy for
    visualizing what's going on with the data.
    x= Value from sensor, mn= minimum plottable value,
    mx= maximum plottable value, w= width of plot in chars,
    c= the character to plot with.'''
    if not w: return '' # No width!
    if x<mn: x= mn      # Clip to bounds.
    if x>mx: x= mx      # Clip to bounds.
    tx= mx-mn # Total real units possible to show on graph.
    if tx<=0: return 'backwards' # Stupid bounds.
    upw= tx/float(w) # X Units per output char width.
    if upw<=0: return 'what?' # Don't let this happen.
    negpu, pospu, negnonpu, posnonpu= 0,0,0,0
    if mn < 0: # Then there is a negative part to graph.
        if x < 0: # And the plot is on the negative side.
            negpu= -x + min(0,mx)
            negnonpu= -mn + x
        else: # Plot is on pos. Neg side is empty.
            negnonpu= -mn + min(0,mx) # But still show some empty neg.
    if mx > 0: # There is a positive part to the graph
        if x > 0: # And the plot is on the positive side.
            pospu= x - max(0,mn)
            posnonpu= mx - x
        else: # Plot is on neg. Pos side is empty.
            posnonpu= mx - max(0,mn) # But still show some empty pos.
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
        self.maxEpisodes=1 # "Maximum number of learning episodes to perform"
        self.trackname= 'unknown'
        self.stage= 3 # 0=Warm-up, 1=Qualifying 2=Race, 3=unknown <Default=3>
        self.debug= False
        self.maxSteps= 100000  # 50steps/second
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
                    print("relaunch torcs")
                    os.system('pkill torcs')
                    time.sleep(1.0)
                    if self.vision is False:
                        os.system('torcs -nofuel -nodamage -nolaptime &')
                    else:
                        os.system('torcs -nofuel -nodamage -nolaptime -vision &')

                    time.sleep(1.0)
                    os.system('sh autostart.sh')
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
        '''Server's input is stored in a ServerState object'''
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
                        (self.port,self.S.d['racePos'])))
                self.shutdown()
                return
            elif '***restart***' in sockdata:
                print("Server has restarted the race on %d." % self.port)
                self.shutdown()
                return
            elif not sockdata: # Empty?
                continue       # Try again.
            else:
                self.S.parse_server_str(sockdata)
                if self.debug:
                    sys.stderr.write("\x1b[2J\x1b[H") # Clear for steady output.
                    print(self.S)
                break # Can now return from this function.

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

class ServerState():
    '''What the server is reporting right now.'''
    def __init__(self):
        self.servstr= str()
        self.d= dict()

    def parse_server_str(self, server_string):
        '''Parse the server string.'''
        self.servstr= server_string.strip()[:-1]
        sslisted= self.servstr.strip().lstrip('(').rstrip(')').split(')(')
        for i in sslisted:
            w= i.split(' ')
            self.d[w[0]]= destringify(w[1:])

    def __repr__(self):
        return self.fancyout()

    def fancyout(self):
        '''Specialty output for useful ServerState monitoring.'''
        out= str()
        sensors= [ # Select the ones you want in the order you want them.
        'stucktimer',
        'fuel',
        'distRaced',
        'distFromStart',
        'opponents',
        'wheelSpinVel',
        'z',
        'speedZ',
        'speedY',
        'speedX',
        'targetSpeed',
        'rpm',
        'skid',
        'slip',
        'track',
        'trackPos',
        'angle',
        ]

        for k in sensors:
            if type(self.d.get(k)) is list: # Handle list type data.
                if k == 'track': # Nice display for track sensors.
                    strout= str()
                    raw_tsens= ['%.1f'%x for x in self.d['track']]
                    strout+= ' '.join(raw_tsens[:9])+'_'+raw_tsens[9]+'_'+' '.join(raw_tsens[10:])
                elif k == 'opponents': # Nice display for opponent sensors.
                    strout= str()
                    for osensor in self.d['opponents']:
                        if   osensor >190: oc= '_'
                        elif osensor > 90: oc= '.'
                        elif osensor > 39: oc= chr(int(osensor/2)+97-19)
                        elif osensor > 13: oc= chr(int(osensor)+65-13)
                        elif osensor >  3: oc= chr(int(osensor)+48-3)
                        else: oc= '?'
                        strout+= oc
                    strout= ' -> '+strout[:18] + ' ' + strout[18:]+' <-'
                else:
                    strlist= [str(i) for i in self.d[k]]
                    strout= ', '.join(strlist)
            else: # Not a list type of value.
                if k == 'gear': # This is redundant now since it's part of RPM.
                    gs= '_._._._._._._._._'
                    p= int(self.d['gear']) * 2 + 2  # Position
                    l= '%d'%self.d['gear'] # Label
                    if l=='-1': l= 'R'
                    if l=='0':  l= 'N'
                    strout= gs[:p]+ '(%s)'%l + gs[p+3:]
                elif k == 'damage':
                    strout= '%6.0f %s' % (self.d[k], bargraph(self.d[k],0,10000,50,'~'))
                elif k == 'fuel':
                    strout= '%6.0f %s' % (self.d[k], bargraph(self.d[k],0,100,50,'f'))
                elif k == 'speedX':
                    cx= 'X'
                    if self.d[k]<0: cx= 'R'
                    strout= '%6.1f %s' % (self.d[k], bargraph(self.d[k],-30,300,50,cx))
                elif k == 'speedY': # This gets reversed for display to make sense.
                    strout= '%6.1f %s' % (self.d[k], bargraph(self.d[k]*-1,-25,25,50,'Y'))
                elif k == 'speedZ':
                    strout= '%6.1f %s' % (self.d[k], bargraph(self.d[k],-13,13,50,'Z'))
                elif k == 'z':
                    strout= '%6.3f %s' % (self.d[k], bargraph(self.d[k],.3,.5,50,'z'))
                elif k == 'trackPos': # This gets reversed for display to make sense.
                    cx='<'
                    if self.d[k]<0: cx= '>'
                    strout= '%6.3f %s' % (self.d[k], bargraph(self.d[k]*-1,-1,1,50,cx))
                elif k == 'stucktimer':
                    if self.d[k]:
                        strout= '%3d %s' % (self.d[k], bargraph(self.d[k],0,300,50,"'"))
                    else: strout= 'Not stuck!'
                elif k == 'rpm':
                    g= self.d['gear']
                    if g < 0:
                        g= 'R'
                    else:
                        g= '%1d'% g
                    strout= bargraph(self.d[k],0,10000,50,g)
                elif k == 'angle':
                    asyms= [
                          "  !  ", ".|'  ", "./'  ", "_.-  ", ".--  ", "..-  ",
                          "---  ", ".__  ", "-._  ", "'-.  ", "'\.  ", "'|.  ",
                          "  |  ", "  .|'", "  ./'", "  .-'", "  _.-", "  __.",
                          "  ---", "  --.", "  -._", "  -..", "  '\.", "  '|."  ]
                    rad= self.d[k]
                    deg= int(rad*180/PI)
                    symno= int(.5+ (rad+PI) / (PI/12) )
                    symno= symno % (len(asyms)-1)
                    strout= '%5.2f %3d (%s)' % (rad,deg,asyms[symno])
                elif k == 'skid': # A sensible interpretation of wheel spin.
                    frontwheelradpersec= self.d['wheelSpinVel'][0]
                    skid= 0
                    if frontwheelradpersec:
                        skid= .5555555555*self.d['speedX']/frontwheelradpersec - .66124
                    strout= bargraph(skid,-.05,.4,50,'*')
                elif k == 'slip': # A sensible interpretation of wheel spin.
                    frontwheelradpersec= self.d['wheelSpinVel'][0]
                    slip= 0
                    if frontwheelradpersec:
                        slip= ((self.d['wheelSpinVel'][2]+self.d['wheelSpinVel'][3]) -
                              (self.d['wheelSpinVel'][0]+self.d['wheelSpinVel'][1]))
                    strout= bargraph(slip,-5,150,50,'@')
                else:
                    strout= str(self.d[k])
            out+= "%s: %s\n" % (k,strout)
        return out

class DriverAction():
    '''What the driver is intending to do (i.e. send to the server).
    Composes something like this for the server:
    (accel 1)(brake 0)(gear 1)(steer 0)(clutch 0)(focus 0)(meta 0) or
    (accel 1)(brake 0)(gear 1)(steer 0)(clutch 0)(focus -90 -45 0 45 90)(meta 0)'''
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
        """There pretty much is never a reason to send the server
        something like (steer 9483.323). This comes up all the time
        and it's probably just more sensible to always clip it than to
        worry about when to. The "clip" command is still a snakeoil
        utility function, but it should be used only for non standard
        things or non obvious limits (limit the steering to the left,
        for example). For normal limits, simply don't worry about it."""
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

    def fancyout(self):
        '''Specialty output for useful monitoring of bot's effectors.'''
        out= str()
        od= self.d.copy()
        od.pop('gear','') # Not interesting.
        od.pop('meta','') # Not interesting.
        od.pop('focus','') # Not interesting. Yet.
        for k in sorted(od):
            if k == 'clutch' or k == 'brake' or k == 'accel':
                strout=''
                strout= '%6.3f %s' % (od[k], bargraph(od[k],0,1,50,k[0].upper()))
            elif k == 'steer': # Reverse the graph to make sense.
                strout= '%6.3f %s' % (od[k], bargraph(od[k]*-1,-1,1,50,'S'))
            else:
                strout= str(od[k])
            out+= "%s: %s\n" % (k,strout)
        return out

def destringify(s):
    '''makes a string into a value or a list of strings into a list of
    values (if possible)'''
    if not s: return s
    if type(s) is str:
        try:
            return float(s)
        except ValueError:
            print("Could not find a value in %s" % s)
            return s
    elif type(s) is list:
        if len(s) < 2:
            return destringify(s[0])
        else:
            return [destringify(i) for i in s]

import numpy as np

def ottieni_stato_da_snakeoil(S):
    '''
    Converte il dizionario dei sensori di snakeoil in un array numpy 
    che la rete neurale può capire.
    '''
    stato = [
        S['angle'] / 3.1416,           # Angolo rispetto alla pista
        S['speedX'] / 300.0,           # Velocità in avanti
        S['speedY'] / 100.0,           # Velocità laterale
        S['trackPos'] / 1.0            # Posizione sulla pista (-1 destra, +1 sinistra)
    ]
    # Aggiungi i sensori di distanza del tracciato (19 valori)
    stato.extend([x / 200.0 for x in S['track']])
    
    return np.array(stato)

import math

def drive(c, modello_ia=None):
    S = c.S.d
    R = c.R.d

    track = S['track']
    angle = S['angle']
    pos = S['trackPos']
    speed = S['speedX']
    
    old_steer = R.get('steer', 0.0)

    # === 0. CAMBIO (Salvagente per la Retromarcia) ===
    # Se stiamo andando all'indietro a velocità sostenuta, mantieni la retro!
    if speed < -2: 
        R['gear'] = -1
    else:
        if speed < 40: R['gear'] = 1
        elif speed < 90: R['gear'] = 2
        elif speed < 140: R['gear'] = 3
        elif speed < 190: R['gear'] = 4
        elif speed < 240: R['gear'] = 5
        else: R['gear'] = 6

    # === 1. RECOVERY (NUOVO - Anti-Incastro) ===
    # Se l'auto è girata al contrario (> 90 gradi)
    if abs(angle) > 1.57:
        R['gear'] = -1
        R['accel'] = 0.8
        R['brake'] = 0.0
        R['steer'] = -1.0 if angle > 0 else 1.0 
        return

    # Se l'auto è fuori pista (ruote sull'erba/muro)
    if abs(pos) > 1.0:
        if speed < 5.0:
            # SIAMO INCASTRATI: Metti la retro fissa, fai girare il muso verso il centro
            R['gear'] = -1
            R['accel'] = 0.8
            R['brake'] = 0.0
            # Se siamo a sinistra (pos > 0), sterza a sinistra in retro per far puntare il muso a destra
            R['steer'] = 1.0 if pos > 0 else -1.0 
        else:
            # RIENTRO IN PISTA: Andiamo piano e puntiamo aggressivamente il centro
            R['gear'] = 1 if speed < 40 else R['gear']
            R['accel'] = 0.3
            R['brake'] = 0.2 # Usiamo un po' di freno per non scivolare
            target_angle = -pos * 0.4 # Angolo ideale per rientrare dolcemente
            steer_rec = (angle - target_angle) * 2.0
            R['steer'] = max(-1.0, min(1.0, steer_rec))
        return

    # === 2. SCANNER DELLA CURVA (RAYCASTING CORRETTO) ===
    front = track[9]
    longest_idx = 9
    longest_dist = front # Partiamo assumendo che il centro sia la via migliore
    
    # Se la visuale centrale è già oltre i 190 metri, siamo palesemente in un lungo rettilineo.
    # Non serve nemmeno cercare punti di fuga laterali.
    if front < 190.0:
        for i, dist in enumerate(track):
            # Cambiamo il punto di fuga SOLO se un sensore laterale vede
            # *chiaramente* più lontano (almeno 5 metri in più) rispetto all'attuale.
            if dist > longest_dist + 5.0:
                longest_dist = dist
                longest_idx = i

    fuga_angle = (longest_idx - 9) * 10.0 
    severita_curva = min(1.0, abs(fuga_angle) / 90.0)

    # === 3. TARGET POS E VELOCITÀ ===
    target_pos = 0.0
    target_speed = min(300.0, front * 2.5)

    if abs(fuga_angle) > 0 or front < 130:
        moltiplicatore = 1.6 - (severita_curva * 0.8)

        if fuga_angle > 0:
            if front > 60:
                target_pos = -0.8 # Un po' meno estremo sull'erba in ingresso
                target_speed = max(80.0, longest_dist * moltiplicatore)
            else:
                target_pos = 0.9 
                target_speed = max(55.0, longest_dist * (moltiplicatore - 0.2)) 
        elif fuga_angle < 0:
            if front > 60:
                target_pos = 0.8 
                target_speed = max(80.0, longest_dist * moltiplicatore)
            else:
                target_pos = -0.9 
                target_speed = max(55.0, longest_dist * (moltiplicatore - 0.2))

    if speed < 40:
        target_pos = 0.0

    # === 4. STERZO (Reattività e Centramento Ripristinati) ===
    error = pos - target_pos

    if front > 120:
        # RETTILINEO: Rimesso il magnetismo verso il centro!
        peso_angolo = 1.5
        peso_pos = 0.4 # Ora l'auto CERCERÀ attivamente la riga di mezzo
        steer_target = (angle * peso_angolo) - (error * peso_pos)
        
        # Deadzone totale solo se sei praticamente già perfetto
        if abs(angle) < 0.02 and abs(pos) < 0.1:
            steer_target = 0.0
    else:
        # CURVA
        peso_angolo = 1.0
        peso_pos = 1.8 
        steer_target = (angle * peso_angolo) - (error * peso_pos) - (S['speedY'] * 0.15)

    # Ridotto l'ammortizzatore per renderla più scattante nel tornare al centro
    steer_target *= max(0.2, 1.0 - (speed / 300.0))

    # Filtro fluido meno aggressivo (reagisce più in fretta)
    alpha = max(0.5, 1.0 - (speed / 200.0)) 
    steer = (old_steer * (1.0 - alpha)) + (steer_target * alpha)

    R['steer'] = max(-1.0, min(1.0, steer))

    # === 5. PEDALI ===
    diff = target_speed - speed
    grip_usato = abs(R['steer'])
    grip_rimanente = max(0.0, 1.0 - grip_usato)

    if diff > 0:
        raw_accel = min(1.0, diff / 8.0) 
        early_throttle_allowance = 0.3 + (front / 100.0)
        
        R['accel'] = min(raw_accel, grip_rimanente + early_throttle_allowance) 
        R['brake'] = 0.0
        
        if speed < 30 and R['gear'] == 1:
            R['accel'] = min(R['accel'], 0.5)
    else:
        raw_brake = min(1.0, abs(diff) / 10.0) 
        R['brake'] = min(raw_brake, grip_rimanente + 0.1)
        R['accel'] = 0.0 

    # === 6. ESP & TCS ===
    spin = (S['wheelSpinVel'][2] + S['wheelSpinVel'][3]) - (S['wheelSpinVel'][0] + S['wheelSpinVel'][1])
    if spin > 12 and abs(R['steer']) > 0.2: 
        R['accel'] *= 0.6

    if abs(S['speedY']) > 5.0: 
        R['steer'] *= 0.9 
        R['accel'] *= 0.7 

    return


def calcola_reward(S):
    '''
    Calcola quanto è stata brava l'IA in questo step.
    Premia la velocità dritta, penalizza i fuori pista.
    '''
    if abs(S['trackPos']) > 1.0:
        return -100  # Fuori pista! Penalità enorme.
    
    # Premia la velocità moltiplicata per il coseno dell'angolo 
    # (più vai veloce E dritto, più punti fai)
    return S['speedX'] * np.cos(S['angle'])


if __name__ == "__main__":
    C = Client(p=3001)
    
    # Qui inizializzerai la tua rete neurale (es. un modello PPO o DDPG con PyTorch/TensorFlow)
    # mio_modello_ia = CreaMioModelloIA()
    mio_modello_ia = None # Lasciato a None per farti testare il bot di fallback
    
    # Loop degli episodi (le "partite")
    for episode in range(C.maxEpisodes):
        
        # Loop degli step all'interno della gara
        for step in range(C.maxSteps, 0, -1):
            # 1. Snakeoil riceve i sensori dal server
            C.get_servers_input()
            
            # --- INIZIO LOGICA TRAINING ---
            stato_corrente = ottieni_stato_da_snakeoil(C.S.d)
            
            # 2. Chiamiamo la funzione drive che imposta i controlli su C.R.d
            drive(C, mio_modello_ia)
            
            # 3. Snakeoil invia i comandi (sterzo, freno, accel) al server TORCS
            C.respond_to_server()
            
            # 4. Calcoliamo la ricompensa per l'azione appena fatta
            reward = calcola_reward(C.S.d)
            
            # Se stai addestrando l'IA, qui chiami la funzione per aggiornare i pesi:
            # mio_modello_ia.train_step(stato_corrente, azione_presa, reward)
            # --- FINE LOGICA TRAINING ---

    C.shutdown()
