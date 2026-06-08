import sys
import os
import pygame   # Libreria per l'interazione col controller

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from snakeoil3_gym import clip


#  ----------- SETUP CONTROLLER -----------

# Indici assi pygame per Xbox su Windows
AXIS_STEER = 0   # Stick sinistro (X)
AXIS_LT    = 4   # Grilletto sinistro (-1.0 = riposo, 1.0 = premuto)
AXIS_RT    = 5   # Grilletto destro

# Indici pulsanti
BTN_A      = 0   # Scalo marcia
BTN_B      = 1   # Salgo marcia
BTN_SELECT = 6   # Restart
BTN_START  = 7   # Pausa


#  ----------- CALIBRAZIONE FISICA -----------

STEER_DEADZONE = 0.10 # Ignoro i piccolissimi movimenti dello stick al centro
STEER_POWER    = 1.7  # Curva di risposta esponenziale: raddolcisce i piccoli movimenti e amplifica i grandi
STEER_SCALE    = 0.85 # Limito lo sterzo fisico massimo per prevenire testacoda
STEER_SMOOTH   = 0.45 # Smorzamento: quanto l'input attuale dipende da quello precedente
TRIGGER_POWER  = 1.65 # Curva di risposta per i pedali (corsa iniziale più dolce)


class XboxController:
    """
    Rilevamento e interpretazione dell'hardware Xbox.
    """

    def __init__(self):
        # Inizializzo le librerie SDL per l'input in background
        os.environ["SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS"] = "1"
        pygame.init()
        pygame.joystick.init()

        n_joy = pygame.joystick.get_count()
        if n_joy == 0:
            print("[WARNING] Nessun joypad collegato. I comandi saranno a zero.")
            self.joy = None
        else:
            self.joy = pygame.joystick.Joystick(0)
            self.joy.init()
            print(f"[OK] Controller agganciato: '{self.joy.get_name()}'")

        # Memoria per i bottoni (permette di intercettare il singolo click senza spam)
        self._prev_btn_a       = False
        self._prev_btn_b       = False
        self._prev_btn_pause   = False
        self._prev_btn_restart = False

        self.paused = False
        self.current_gear = 1
        self._prev_steer = 0.0

    def _axis(self, idx: int) -> float:
        """Leggo il valore di un asse analogico (da -1.0 a 1.0)."""
        if self.joy is None or idx >= self.joy.get_numaxes():
            return 0.0
        return self.joy.get_axis(idx)

    def _button(self, idx: int) -> bool:
        """Verifico se un pulsante specifico è fisicamente premuto."""
        if self.joy is None or idx >= self.joy.get_numbuttons():
            return False
        return bool(self.joy.get_button(idx))

    @staticmethod
    def _trigger_to_01(raw: float) -> float:
        """Normalezza i grilletti da [-1, 1] a [0, 1]."""
        return (raw + 1.0) / 2.0


    #  ----------- LETTURA HARDWARE -----------

    def read(self) -> dict:
        """Cattura lo stato corrente e ritorna il dizionario dei comandi pronti all'uso."""
        
        # Svuoto la coda eventi di Pygame, essenziale per fargli aggiornare i dati del joystick
        quit_requested = False
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                quit_requested = True

        raw_steer = self._axis(AXIS_STEER)

        # Appiattisco il centro (Deadzone)
        if abs(raw_steer) < STEER_DEADZONE:
            raw_steer = 0.0
        else:
            sign = 1.0 if raw_steer > 0 else -1.0
            raw_steer = sign * (abs(raw_steer) - STEER_DEADZONE) / (1.0 - STEER_DEADZONE)

        # Curvo l'input per rendere lo sterzo più prevedibile e graduale
        curved = (abs(raw_steer) ** STEER_POWER) * (1.0 if raw_steer >= 0 else -1.0)

        # Invertito perché l'SDL ragiona a specchio rispetto a TORCS
        target_steer = clip(-curved * STEER_SCALE, -1.0, 1.0)

        # Applico un filtro Low-Pass per ammorbidire le sterzate scattose del pollice
        steer = self._prev_steer * STEER_SMOOTH + target_steer * (1.0 - STEER_SMOOTH)
        self._prev_steer = steer

        # Leggo i grilletti e applico la curva esponenziale per i pedali
        raw_accel = self._trigger_to_01(self._axis(AXIS_RT))
        raw_brake = self._trigger_to_01(self._axis(AXIS_LT))
        accel = raw_accel ** TRIGGER_POWER
        brake = raw_brake ** TRIGGER_POWER

        # Gestisco le marce controllando il cambio di stato del pulsante
        btn_b = self._button(BTN_B)
        if btn_b and not self._prev_btn_b:
            self.current_gear = min(6, self.current_gear + 1)
        self._prev_btn_b = btn_b

        btn_a = self._button(BTN_A)
        if btn_a and not self._prev_btn_a:
            self.current_gear = max(-1, self.current_gear - 1)
        self._prev_btn_a = btn_a

        # Gestisco la pausa
        btn_pause = self._button(BTN_START)
        if btn_pause and not self._prev_btn_pause:
            self.paused = not self.paused
            if not self.paused:
                self._prev_steer = 0.0 # Ripartenza senza sbandamenti brutali
        self._prev_btn_pause = btn_pause

        # Gestisco il riavvio rapido
        btn_restart = self._button(BTN_SELECT)
        restart_requested = btn_restart and not self._prev_btn_restart
        self._prev_btn_restart = btn_restart

        return {
            "steer":   steer,
            "accel":   accel,
            "brake":   brake,
            "gear":    self.current_gear,
            "paused":  self.paused,
            "restart": restart_requested,
            "quit":    quit_requested,
        }

    def close(self):
        """Chiudo in modo sicuro la connessione col joypad."""
        pygame.joystick.quit()
