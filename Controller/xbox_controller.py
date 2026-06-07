import sys
import os
import pygame

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from snakeoil3_gym import clip

# ──────────────────────────────────────────────────────────────────────────────
# Costanti
# ──────────────────────────────────────────────────────────────────────────────

# Indici assi pygame per controller Xbox su Windows
AXIS_STEER = 0   # Stick sinistro orizzontale
AXIS_LT    = 4   # Grilletto sinistro  (riposo = -1.0, premuto = +1.0)
AXIS_RT    = 5   # Grilletto destro    (riposo = -1.0, premuto = +1.0)

# Indici bottoni Xbox
BTN_A     = 0    # Scala marcia  (gear -1)
BTN_B     = 1    # Ingrana marcia (gear +1)
BTN_SELECT= 6    # Back  → Restart gara
BTN_START = 7    # Start → Toggle pausa / riprendi

# ── Calibrazione input ───────────────────────────────────────────────────────
# Zona morta stick sinistro: movimenti più piccoli di questo vengono ignorati
STEER_DEADZONE   = 0.10

# Curva di potenza sterzo: esponente > 1 → movimenti piccoli diventano ancora più piccoli
STEER_POWER      = 1.7

# Sensibilità massima: 1.0 = sterzo a fondo con lo stick a fondo
STEER_SCALE      = 0.85

# Filtro di smorzamento (low-pass): quanto "peso" ha il valore precedente
STEER_SMOOTH     = 0.45

# Curva di potenza grilletti: > 1 → fase iniziale più morbida
TRIGGER_POWER    = 1.65

# ──────────────────────────────────────────────────────────────────────────────
# Classe: XboxController
# ──────────────────────────────────────────────────────────────────────────────

class XboxController:
    """
    Wrapper pygame per un controller Xbox.
    """

    def __init__(self):
        # Inizializzazione Pygame e Joystick
        os.environ["SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS"] = "1"
        pygame.init()
        pygame.joystick.init()

        n_joy = pygame.joystick.get_count()
        if n_joy == 0:
            print("[WARNING] Nessun joypad rilevato. Accel/steer/brake saranno 0.")
            self.joy = None
        else:
            self.joy = pygame.joystick.Joystick(0)
            self.joy.init()
            print(f"[OK] Joypad rilevato: '{self.joy.get_name()}' "
                  f"({self.joy.get_numaxes()} assi, {self.joy.get_numbuttons()} bottoni)")

        # Stato bottoni per rilevare il fronte di salita
        self._prev_btn_a     = False
        self._prev_btn_b     = False
        self._prev_btn_pause   = False
        self._prev_btn_restart = False

        # Stato pausa
        self.paused = False

        # Marcia corrente (manuale, partenza in prima)
        self.current_gear = 1

        # Valore sterzo dello step precedente (usato dal filtro di smorzamento)
        self._prev_steer = 0.0

    # ── Lettura assi/bottoni ───────────────────────────────────────────────────

    def _axis(self, idx: int) -> float:
        if self.joy is None or idx >= self.joy.get_numaxes():
            return 0.0
        return self.joy.get_axis(idx)

    def _button(self, idx: int) -> bool:
        if self.joy is None or idx >= self.joy.get_numbuttons():
            return False
        return bool(self.joy.get_button(idx))

    @staticmethod
    def _trigger_to_01(raw: float) -> float:
        """Grilletti Xbox: -1.0 a riposo → +1.0 premuto. Converte in [0, 1]."""
        return (raw + 1.0) / 2.0

    def read(self) -> dict:
        """
        Elabora la coda eventi pygame e restituisce i comandi normalizzati:
          steer, accel, brake, gear, quit
        """
        # ── Processa TUTTI gli eventi pygame (obbligatorio per il joystick) ──
        quit_requested = False
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                quit_requested = True

        # ── Assi ──────────────────────────────────────────────────────────────
        raw_steer = self._axis(AXIS_STEER)

        # 1. Zona morta
        if abs(raw_steer) < STEER_DEADZONE:
            raw_steer = 0.0
        else:
            # Ri-normalizza il range post-deadzone in [0,1] per la curva
            sign = 1.0 if raw_steer > 0 else -1.0
            raw_steer = sign * (abs(raw_steer) - STEER_DEADZONE) / (1.0 - STEER_DEADZONE)

        # 2. Curva di potenza: mantieni il segno, applica l'esponente al valore assoluto
        curved = (abs(raw_steer) ** STEER_POWER) * (1.0 if raw_steer >= 0 else -1.0)

        # 3. Scala e inverti (asse SDL: sinistra = negativo, TORCS: sinistra = positivo)
        target_steer = clip(-curved * STEER_SCALE, -1.0, 1.0)

        # 4. Filtro di smorzamento low-pass
        steer = self._prev_steer * STEER_SMOOTH + target_steer * (1.0 - STEER_SMOOTH)
        self._prev_steer = steer

        # ── Grilletti con curva di potenza ────────────────────────────────────
        raw_accel = self._trigger_to_01(self._axis(AXIS_RT))
        raw_brake = self._trigger_to_01(self._axis(AXIS_LT))
        accel = raw_accel ** TRIGGER_POWER
        brake = raw_brake ** TRIGGER_POWER

        # ── Tasto B: ingrana marcia superiore ─────────────────────────────────
        btn_b    = self._button(BTN_B)
        gear_up  = btn_b and not self._prev_btn_b
        self._prev_btn_b = btn_b

        # ── Tasto A: scala marcia inferiore ───────────────────────────────────
        btn_a      = self._button(BTN_A)
        gear_down  = btn_a and not self._prev_btn_a
        self._prev_btn_a = btn_a

        # ── Aggiorna marcia ───────────────────────────────────────────────────
        if gear_up:
            self.current_gear = min(6, self.current_gear + 1)
        if gear_down:
            self.current_gear = max(-1, self.current_gear - 1)

        # ── Tasto Start: toggle pausa ─────────────────────────────────────
        btn_pause = self._button(BTN_START)
        if btn_pause and not self._prev_btn_pause:
            self.paused = not self.paused
            if not self.paused:
                # Azzera lo smorzamento: riparte da zero senza scatto
                self._prev_steer = 0.0
        self._prev_btn_pause = btn_pause

        # ── Tasto Select: restart ─────────────────────────────────────────────
        btn_restart = self._button(BTN_SELECT)
        restart_requested = btn_restart and not self._prev_btn_restart
        self._prev_btn_restart = btn_restart

        return {
            "steer":  steer,
            "accel":  accel,
            "brake":  brake,
            "gear":   self.current_gear,
            "paused":  self.paused,
            "restart": restart_requested,
            "quit":    quit_requested,
        }

    def close(self):
        pygame.joystick.quit()
