from pynput.keyboard import Key, Listener
import snakeoil3_jm2 as snakeoil3
import time
import os
from datetime import datetime

class PynputController:
    def __init__(self):
        self.keys = set()
        self.state = {
            'steer': 0.0,
            'accel': 0.0,
            'brake': 0.0,
            'gear': 1
        }
        # Avvia il listener in background
        self.listener = Listener(on_press=self.press, on_release=self.release)
        self.listener.start()

    def press(self, key):
        self.keys.add(key)
        # Gestione del cambio manuale con W (Su) e S (Giù)
        if hasattr(key, "char") and key.char:
            char = key.char.lower()
            if char == 'w':
                self.state['gear'] += 1
            elif char == 's':
                self.state['gear'] -= 1

    def release(self, key):
        self.keys.discard(key)

    def update(self, sensors):
        speed = sensors.get('speedX', 0)
        angle = sensors.get('angle', 0)

        # ========================
        # ACCELERAZIONE SMOOTH
        # ========================
        target_accel = 1.0 if Key.up in self.keys else 0.0
        self.state['accel'] += (target_accel - self.state['accel']) * 0.1

        # ========================
        # FRENO SMOOTH
        # ========================
        target_brake = 1.0 if Key.down in self.keys else 0.0
        self.state['brake'] += (target_brake - self.state['brake']) * 0.2

        # ========================
        # STEERING INPUT CON STABILITÀ
        # ========================
        steer_input = 0.0
        if Key.left in self.keys:
            steer_input += 0.6
        if Key.right in self.keys:
            steer_input -= 0.6

        # Limite sterzata in base alla velocità (più vai veloce, meno sterzi bruscamente)
        max_steer = max(0.25, 1.0 - speed / 200.0)
        steer_input *= max_steer

        # Se non stai sterzando o stai andando dritto, applica correzione di stabilità
        if abs(steer_input) < 0.01:
            steer_target = 0.0
        else:
            stability = angle * 0.3
            steer_target = steer_input - stability

        # Raccordo morbido per lo sterzo
        self.state['steer'] += (steer_target - self.state['steer']) * 0.2

        # Zona morta per evitare micro-vibrazioni
        if abs(self.state['steer']) < 0.02:
            self.state['steer'] = 0.0

        # Clamp finale di sicurezza sui range ammessi [cite: 131]
        self.state['steer'] = max(-1.0, min(1.0, self.state['steer']))
        self.state['accel'] = max(0.0, min(1.0, self.state['accel']))
        self.state['brake'] = max(0.0, min(1.0, self.state['brake']))
        self.state['gear'] = max(-1, min(6, self.state['gear']))


def main():
    if not os.path.exists("giri"): os.makedirs("giri")
    csv_name = f"giri/session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    client = snakeoil3.Client(p=3001, vision=False)
    controller = PynputController()
    
    log_csv = open(csv_name, "w")

    # --- HEADER DINAMICO PER 19 TRACK + 11 EXTRA = 30 INPUT ---
    track_headers = ",".join([f"t_{i}" for i in range(19)])
    extra_headers = "trackPos,angle,speedX,speedY,distFromStart,rpm,wsv_avg,gear_in,z,pitch,accelZ"
    output_headers = "steer,accel,brake,gear_out"
    log_csv.write(f"{track_headers},{extra_headers},{output_headers}\n")

    last_dist = -1.0
    freeze_counter = 0
    recording = False

    print("Arcade driving mode attivo (pynput)")
    print("Freccette per guidare, W/S per le marce.")
    print("Inizia ad accelerare per far partire la registrazione dei dati.")

    try:
        while True:
            # Ricezione dati e aggiornamento stato auto [cite: 182, 183]
            client.get_servers_input()
            S = client.S.d
            
            # Passiamo i sensori al controller per i calcoli di stabilità
            controller.update(S)

            track = S.get('track', [200.0]*19)
            speedX = S.get('speedX', 0)
            distNow = S.get('distFromStart', 0)

            # Impostazione e invio comandi al server [cite: 158, 159, 160]
            client.R.d.update({
                'steer': controller.state['steer'],
                'accel': controller.state['accel'],
                'brake': controller.state['brake'],
                'gear': controller.state['gear']
            })
            client.respond_to_server()

            # --- LOGICA DI REGISTRAZIONE PER DATASET ---
            # Attivazione registrazione solo quando si dà il primo colpo di gas
            if not recording and controller.state['accel'] > 0.2:
                recording = True
                print(">>> REGISTRAZIONE IN CORSO <<<")

            if recording:
                # Anti-Freeze: se l'auto è ferma o bloccata contro un muro per troppo tempo, ferma tutto
                if distNow == last_dist or abs(speedX) < 0.01:
                    freeze_counter += 1
                else:
                    freeze_counter = 0

                if freeze_counter > 100:
                    print(">>> FINE GIRO O AUTO BLOCCATA RILEVATA. SALVATAGGIO... <<<")
                    break

                if freeze_counter == 0:
                    # 1. I 19 sensori track
                    track_str = ",".join(map(str, track))

                    # 2. Gli 11 sensori extra (utili per curve paraboliche/salite)
                    wsv_avg = sum(S.get('wheelSpinVel', [0]*4)) / 4
                    extra_str = (f"{S.get('trackPos',0)},{S.get('angle',0)},{speedX},"
                                 f"{S.get('speedY',0)},{distNow},{S.get('rpm',0)},"
                                 f"{wsv_avg},{S.get('gear',1)},"
                                 f"{S.get('z',0)},{S.get('pitch',0)},{S.get('accelZ',0)}")

                    # 3. I 4 output target (ciò che la rete neurale dovrà imparare) [cite: 364, 365]
                    out_str = (f"{controller.state['steer']},{controller.state['accel']},"
                               f"{controller.state['brake']},{controller.state['gear']}")

                    # Scrittura su file
                    log_csv.write(f"{track_str},{extra_str},{out_str}\n")

                last_dist = distNow
                
            # Sleep di 20ms (50Hz) standard per il tick rate di TORCS
            time.sleep(0.02)

    except KeyboardInterrupt:
        print("\nInterrotto manualmente da terminale.")
    finally:
        log_csv.close()
        print(f"File dataset salvato in: {csv_name}")

if __name__ == "__main__":
    main()