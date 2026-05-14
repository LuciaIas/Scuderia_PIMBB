"""
controller.py
=============
Controller manuale per TORCS con joypad Xbox (via pygame).

Mappatura tasti/assi
--------------------
  Stick sinistro (asse 0)    →  steer    [-1.0 .. +1.0]
  Grilletto R   (RT, asse 5) →  accel   [ 0.0 .. +1.0]
  Grilletto L   (LT, asse 4) →  brake   [ 0.0 .. +1.0]
  Tasto B       (button 1)   →  gear +1  (ingrana marcia superiore)
  Tasto A       (button 0)   →  gear -1  (scala marcia inferiore)
  Tasto Start   (button 7)   →  salva log e termina la sessione

Log
---
  I dati vengono scritti in tempo reale in:
    logs/session_YYYYMMDD_HHMMSS.jsonl  (sessione normale / interrotta)
    logs/log_garaN.jsonl                 (gara completata, N progressivo)

Avvio
-----
  python controller.py [--host localhost] [--port 3001] [--track nomepista]
"""

import os
import sys
import json
import time
import getopt
import datetime
import socket as _socket   # per drain UDP

import pygame

# Importa le classi e utility dal file snakeoil principale
from mioTraining import Client, clip, destringify

# ──────────────────────────────────────────────────────────────────────────────
# Costanti
# ──────────────────────────────────────────────────────────────────────────────

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

# Indici assi pygame per controller Xbox su Windows
AXIS_STEER = 0   # Stick sinistro orizzontale
AXIS_LT    = 4   # Grilletto sinistro  (riposo = -1.0, premuto = +1.0)
AXIS_RT    = 5   # Grilletto destro    (riposo = -1.0, premuto = +1.0)

# Indici bottoni Xbox
BTN_A     = 0    # Scala marcia  (gear -1)
BTN_B     = 1    # Ingrana marcia (gear +1)
BTN_PAUSE = 7    # Toggle pausa / riprendi
BTN_QUIT  = 6    # Back  → salva log e termina

# ── Calibrazione input ───────────────────────────────────────────────────────
# Zona morta stick sinistro: movimenti più piccoli di questo vengono ignorati
STEER_DEADZONE   = 0.10   # era 0.05 — aumentata per eliminare micro-drift

# Curva di potenza sterzo: esponente > 1 → movimenti piccoli diventano ancora più piccoli,
# il centro è più preciso ma i bordi restano raggiungibili.
# 1.0 = lineare (massima reattività), 2.0 = quadratica (molto morbida)
STEER_POWER      = 1.7

# Sensibilità massima: 1.0 = sterzo a fondo con lo stick a fondo,
# < 1.0 = lo stick al 100% manda solo STEER_SCALE al server
STEER_SCALE      = 0.85

# Filtro di smorzamento (low-pass): quanto "peso" ha il valore precedente.
# 0.0 = nessuno smorzamento (massima reattività),
# 0.6 = forte inerzia (risposta più lenta e fluida)
STEER_SMOOTH     = 0.45

# Curva di potenza grilletti: > 1 → fase iniziale più morbida
TRIGGER_POWER    = 1.65

# ── Dimensioni finestra HUD ────────────────────────────────────────────────────
HUD_W, HUD_H = 700, 420

# ── Palette colori ────────────────────────────────────────────────────────────
C_BG        = (15,  17,  26)    # sfondo scuro
C_PANEL     = (25,  28,  42)    # pannello interno
C_BORDER    = (50,  55,  80)    # bordi
C_TEXT      = (220, 225, 240)   # testo principale
C_DIM       = (90,  95, 120)    # testo secondario
C_ACCEL     = (50,  220, 100)   # verde acceleratore
C_BRAKE     = (220,  60,  60)   # rosso freno
C_STEER     = (80,  160, 255)   # blu sterzo
C_GEAR      = (255, 200,  50)   # giallo marcia
C_SPEED     = (255, 255, 255)   # bianco velocità
C_WARN      = (255, 140,   0)   # arancione avvisi
C_TRACK_ON  = (80,  160, 255)   # posizione in pista
C_TRACK_OFF = (200,  60,  60)   # fuori pista


# ──────────────────────────────────────────────────────────────────────────────
# Classe: XboxController
# ──────────────────────────────────────────────────────────────────────────────

class XboxController:
    """
    Wrapper pygame per un controller Xbox.
    NOTA: pygame.display.set_mode() DEVE essere chiamato prima di creare
    questa classe affinché il sottosistema eventi funzioni su Windows.
    """

    def __init__(self):
        # Il display è già stato inizializzato da HUD; qui aggiungiamo solo il joystick
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
        self._prev_btn_pause = False
        self._prev_btn_quit  = False

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
        btn_pause = self._button(BTN_PAUSE)
        if btn_pause and not self._prev_btn_pause:
            self.paused = not self.paused
            if not self.paused:
                # Azzera lo smorzamento: riparte da zero senza scatto
                self._prev_steer = 0.0
        self._prev_btn_pause = btn_pause

        # ── Tasto Back: esci ──────────────────────────────────────────────────
        btn_quit = self._button(BTN_QUIT)
        quit_requested = quit_requested or (btn_quit and not self._prev_btn_quit)
        self._prev_btn_quit = btn_quit

        return {
            "steer":  steer,
            "accel":  accel,
            "brake":  brake,
            "gear":   self.current_gear,
            "paused": self.paused,
            "quit":   quit_requested,
        }

    def close(self):
        pygame.joystick.quit()


# ──────────────────────────────────────────────────────────────────────────────
# Classe: HUD  (finestra pygame con indicatori di guida)
# ──────────────────────────────────────────────────────────────────────────────

class HUD:
    """
    Finestra pygame con HUD grafico per il monitoring della guida.
    Inizializza il display (OBBLIGATORIO su Windows per il pump degli eventi).
    """

    def __init__(self):
        # Permette la lettura del joystick anche senza focus sulla finestra
        os.environ["SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS"] = "1"
        pygame.init()                                           # ← init completo
        self.screen = pygame.display.set_mode((HUD_W, HUD_H))
        pygame.display.set_caption("TORCS – Controller Xbox  [joystick attivo in background]")

        # Font
        self.font_big   = pygame.font.SysFont("Consolas", 52, bold=True)
        self.font_med   = pygame.font.SysFont("Consolas", 22, bold=True)
        self.font_small = pygame.font.SysFont("Consolas", 16)

        self.clock = pygame.time.Clock()

    # ── Helper disegno ────────────────────────────────────────────────────────

    def _bar(self, surf, x, y, w, h, value, color, bg=C_PANEL, border=C_BORDER):
        """Barra orizzontale riempita proporzionalmente a value ∈ [0,1]."""
        pygame.draw.rect(surf, bg,     (x, y, w, h))
        pygame.draw.rect(surf, border, (x, y, w, h), 1)
        fill_w = int(w * max(0.0, min(1.0, value)))
        if fill_w > 0:
            pygame.draw.rect(surf, color, (x, y, fill_w, h))

    def _bar_center(self, surf, x, y, w, h, value, color, bg=C_PANEL, border=C_BORDER):
        """Barra centrata (sterzo): value ∈ [-1,1]."""
        pygame.draw.rect(surf, bg,     (x, y, w, h))
        pygame.draw.rect(surf, border, (x, y, w, h), 1)
        cx = x + w // 2
        fill = int((w // 2) * max(-1.0, min(1.0, value)))
        if fill > 0:
            pygame.draw.rect(surf, color, (cx, y, fill, h))
        elif fill < 0:
            pygame.draw.rect(surf, color, (cx + fill, y, -fill, h))
        pygame.draw.line(surf, C_DIM, (cx, y), (cx, y + h - 1), 1)

    def _text(self, surf, txt, font, color, x, y, anchor="topleft"):
        s = font.render(str(txt), True, color)
        r = s.get_rect(**{anchor: (x, y)})
        surf.blit(s, r)

    # ── Render principale ─────────────────────────────────────────────────────

    def render(self, torcs_state: dict, action: dict, step: int, log_path: str):
        """Disegna l'HUD completo con i dati correnti."""
        s   = self.screen
        sd  = torcs_state
        s.fill(C_BG)

        # ── Titolo ────────────────────────────────────────────────────────────
        self._text(s, "TORCS  MANUAL  CONTROLLER", self.font_med, C_DIM, HUD_W // 2, 14, "midtop")

        # ── Pannello velocità (grande, centro) ────────────────────────────────
        speed = sd.get("speedX", 0.0)
        speed_color = C_SPEED if abs(speed) < 200 else C_WARN
        self._text(s, f"{speed:+.0f}", self.font_big, speed_color, HUD_W // 2, 42, "midtop")
        self._text(s, "km/h", self.font_small, C_DIM, HUD_W // 2, 104, "midtop")

        # ── Pannello marcia ───────────────────────────────────────────────────
        gear = action.get("gear", 1)
        gear_label = "R" if gear == -1 else ("N" if gear == 0 else str(gear))
        pygame.draw.rect(s, C_PANEL, (HUD_W - 110, 36, 80, 80), border_radius=8)
        pygame.draw.rect(s, C_BORDER, (HUD_W - 110, 36, 80, 80), 2, border_radius=8)
        self._text(s, gear_label, self.font_big, C_GEAR, HUD_W - 70, 50, "midtop")
        self._text(s, "GEAR", self.font_small, C_DIM, HUD_W - 70, 102, "midtop")

        # ── RPM ───────────────────────────────────────────────────────────────
        rpm     = sd.get("rpm", 0.0)
        rpm_pct = rpm / 10000.0
        rpm_col = C_ACCEL if rpm_pct < 0.8 else C_WARN
        self._text(s, "RPM", self.font_small, C_DIM, 30, 130)
        self._bar(s, 30, 150, HUD_W - 60, 18, rpm_pct, rpm_col)
        self._text(s, f"{rpm:.0f}", self.font_small, rpm_col, HUD_W - 35, 148, "topright")

        # ── Acceleratore ──────────────────────────────────────────────────────
        accel = action.get("accel", 0.0)
        self._text(s, "ACCEL", self.font_small, C_DIM, 30, 182)
        self._bar(s, 30, 202, HUD_W - 60, 22, accel, C_ACCEL)
        self._text(s, f"{accel:.2f}", self.font_small, C_ACCEL, HUD_W - 35, 200, "topright")

        # ── Freno ─────────────────────────────────────────────────────────────
        brake = action.get("brake", 0.0)
        self._text(s, "BRAKE", self.font_small, C_DIM, 30, 236)
        self._bar(s, 30, 256, HUD_W - 60, 22, brake, C_BRAKE)
        self._text(s, f"{brake:.2f}", self.font_small, C_BRAKE, HUD_W - 35, 254, "topright")

        # ── Sterzo ────────────────────────────────────────────────────────────
        steer = action.get("steer", 0.0)
        self._text(s, "STEER", self.font_small, C_DIM, 30, 290)
        self._bar_center(s, 30, 310, HUD_W - 60, 22, steer, C_STEER)
        self._text(s, f"{steer:+.3f}", self.font_small, C_STEER, HUD_W - 35, 308, "topright")

        # ── Posizione pista ───────────────────────────────────────────────────
        track_pos  = sd.get("trackPos", 0.0)
        tp_color   = C_TRACK_ON if abs(track_pos) <= 1.0 else C_TRACK_OFF
        tp_pct     = (track_pos + 2.0) / 4.0   # mappa [-2,+2] → [0,1]
        self._text(s, "TRACK POS", self.font_small, C_DIM, 30, 344)
        self._bar(s, 30, 364, HUD_W - 60, 18, tp_pct, tp_color)
        label_tp = f"{track_pos:+.3f}" + ("  ⚠ FUORI PISTA" if abs(track_pos) > 1.0 else "")
        self._text(s, label_tp, self.font_small, tp_color, HUD_W // 2, 363, "midtop")

        # ── Barra inferiore: step + log path ──────────────────────────────────
        pygame.draw.line(s, C_BORDER, (0, HUD_H - 30), (HUD_W, HUD_H - 30), 1)
        self._text(s, f"step {step:06d}", self.font_small, C_DIM, 14, HUD_H - 22, "topleft")
        self._text(s, os.path.basename(log_path), self.font_small, C_DIM, HUD_W - 14, HUD_H - 22, "topright")

        pygame.display.flip()
        # Nessun clock.tick(): il timing è guidato da TORCS (50 Hz).
        # Il rendering viene chiamato time-gated dal loop principale.

    def process_events(self) -> bool:
        """
        Pompa la coda eventi pygame e restituisce True se è stata
        richiesta l'uscita (chiusura finestra). Da chiamare ad OGNI step
        anche quando non si fa il render, altrimenti Windows congela la finestra.
        """
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return True
        return False

    def render_paused(self, step: int, log_path: str):
        """Overlay semitrasparente ‘IN PAUSA’ sovrapposto all’HUD normale."""
        # Rettangolo scuro semi-opaco
        overlay = pygame.Surface((HUD_W, HUD_H), pygame.SRCALPHA)
        overlay.fill((10, 12, 20, 190))          # RGBA: quasi opaco
        self.screen.blit(overlay, (0, 0))

        # Icona e testo principale
        self._text(self.screen, "⏸  IN PAUSA",
                   self.font_big, (255, 220, 60), HUD_W // 2, HUD_H // 2 - 50, "center")

        # Hint ripresa
        self._text(self.screen, "Premi  START  per riprendere   |   BACK  per uscire",
                   self.font_small, (160, 165, 190), HUD_W // 2, HUD_H // 2 + 20, "center")

        # Barra inferiore
        pygame.draw.line(self.screen, (50, 55, 80), (0, HUD_H - 30), (HUD_W, HUD_H - 30), 1)
        self._text(self.screen, f"step {step:06d}",
                   self.font_small, (90, 95, 120), 14, HUD_H - 22, "topleft")
        self._text(self.screen, os.path.basename(log_path),
                   self.font_small, (90, 95, 120), HUD_W - 14, HUD_H - 22, "topright")

        pygame.display.flip()

    def close(self):
        pygame.quit()


# ──────────────────────────────────────────────────────────────────────────────
# Classe: SessionLogger
# ──────────────────────────────────────────────────────────────────────────────

class SessionLogger:
    """
    Scrive un record JSON per ogni step in formato JSON Lines.
    Ogni riga è un oggetto JSON autonomo:
      {"user":..., "timestamp":..., "sensors":{...}, "actions":{...}}

    Il file viene aperto in append mode con line-buffering:
    il flush avviene automaticamente dopo ogni '\\n', senza
    bloccare mai il loop di gioco.
    """

    def __init__(self, user: str = "unknown", track: str = "unknown"):
        os.makedirs(LOG_DIR, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_id     = ts
        self.user           = user
        # Estensione .jsonl per chiarire il formato (una riga = un record)
        self.filepath       = os.path.join(LOG_DIR, f"session_{ts}.jsonl")
        # buffering=1 → line-buffering: flush automatico su ogni '\n'
        self._file          = open(self.filepath, "a", encoding="utf-8", buffering=1)
        self._step_count    = 0
        self.race_completed = False   # True se TORCS ha segnalato shutdown/restart
        print(f"[LOG] Sessione avviata \u2192 {self.filepath}")

    def log_step(self, server_state: dict, action: dict):
        """Scrive una riga JSON per questo step. Ritorna immediatamente."""
        record = {
            "user":      self.user,
            "timestamp": time.time(),
            "sensors": {
                "speedX":   server_state.get("speedX",   0.0),
                "speedY":   server_state.get("speedY",   0.0),
                "angle":    server_state.get("angle",    0.0),
                "trackPos": server_state.get("trackPos", 0.0),
                "rpm":      server_state.get("rpm",      0.0),
                "track":    server_state.get("track",    []),
            },
            "actions": {
                "steer": action.get("steer", 0.0),
                "accel": action.get("accel", 0.0),
                "brake": action.get("brake", 0.0),
                "gear":  action.get("gear",  1),
            },
        }
        # Compact JSON + newline → il line-buffering fa il flush automaticamente
        self._file.write(json.dumps(record, separators=(',', ':')) + '\n')
        self._step_count += 1

    @staticmethod
    def _next_race_number() -> int:
        """Restituisce il prossimo N per log_garaN.jsonl nella cartella LOG_DIR."""
        existing = [
            f for f in os.listdir(LOG_DIR)
            if f.startswith("log_gara") and f.endswith(".jsonl")
        ]
        nums = []
        for name in existing:
            try:
                nums.append(int(name[len("log_gara"):-len(".jsonl")]))
            except ValueError:
                pass
        return max(nums, default=0) + 1

    def rename_as_race_log(self) -> str:
        """Rinomina il file corrente in log_garaN.jsonl e aggiorna self.filepath."""
        n = self._next_race_number()
        new_path = os.path.join(LOG_DIR, f"log_gara{n}.jsonl")
        os.rename(self.filepath, new_path)
        self.filepath = new_path
        return new_path

    def save_and_close(self):
        """Chiude il file; se la gara è stata completata lo rinomina in log_garaN."""
        self._file.close()
        if self.race_completed:
            new_path = self.rename_as_race_log()
            print(f"[LOG] Gara completata! {self._step_count} step \u2192 {new_path}")
        else:
            print(f"[LOG] Sessione terminata. {self._step_count} step \u2192 {self.filepath}")


# ──────────────────────────────────────────────────────────────────────────────
# Funzione principale
# ──────────────────────────────────────────────────────────────────────────────

def run_manual_session(host: str = "localhost",
                       port: int = 3001,
                       track: str = "unknown",
                       user: str = "unknown",
                       max_steps: int = 100_000):
    """
    Avvia una sessione manuale completa.

    Architettura anti-lag
    ---------------------
    Il loop è guidato esclusivamente dal timing di TORCS (50 Hz / 20 ms per step).
    - La lettura del joypad e gli eventi pygame avvengono ad OGNI step.
    - Il rendering dell'HUD avviene al massimo ogni HUD_RENDER_INTERVAL ms,
      senza mai bloccare il loop con sleep o clock.tick.
    - I pacchetti UDP stantii vengono drenati prima di leggere il joypad,
      così il comando inviato si riferisce sempre all'ultimo stato ricevuto.
    """
    # ── 1. Display pygame (DEVE essere prima del joystick) ────────────────────
    hud  = HUD()

    # ── 2. Joypad (display già attivo) ───────────────────────────────────────
    xbox = XboxController()

    # ── 3. Logger ────────────────────────────────────────────────────
    logger = SessionLogger(user=user, track=track)

    # ── 4. Connessione TORCS ─────────────────────────────────────────────────
    print(f"\n[TORCS] Connessione a {host}:{port} ...")
    C = Client(H=host, p=port, t=track)
    print("[TORCS] Connesso!\n")
    print("Controlli: Stick=steer  RT=accel  LT=brake  B=gear+  A=gear-  Start=esci")
    print()

    step    = 0
    running = True

    # ── Conteggio giri ────────────────────────────────────────────────────────
    # Un giro è completato quando distFromStart torna vicino a 0
    # (scende di oltre LAP_WRAP_THRESHOLD rispetto al valore dello step precedente).
    LAP_WRAP_THRESHOLD = 200.0    # metri — soglia sicura per qualsiasi pista
    LAPS_TO_COMPLETE   = 3        # giri necessari per una gara valida
    _prev_dist         = None     # distFromStart al passo precedente
    _laps_completed    = 0        # giri completati finora

    # Intervallo minimo tra due render dell'HUD (secondi)
    _HUD_INTERVAL = 1.0 / 30      # 30 fps massimi per l'HUD
    _hud_last     = 0.0           # timestamp dell'ultimo render

    try:
        while running and step < max_steps:

            # ── 1. Ricevi l'ultimo stato da TORCS ────────────────────────────
            # get_servers_input() è bloccante: aspetta il prossimo pacchetto UDP.
            # Questo è il "master clock" del loop (~50 Hz / 20 ms per step).
            C.get_servers_input()
            if C.so is None:
                # Gara completata SOLO se abbiamo percorso tutti i giri richiesti
                logger.race_completed = (_laps_completed >= LAPS_TO_COMPLETE)
                if logger.race_completed:
                    print(f"[TORCS] Gara completata ({_laps_completed} giri).")
                else:
                    print(f"[TORCS] Gara terminata anticipatamente "
                          f"(giri completati: {_laps_completed}/{LAPS_TO_COMPLETE}).")
                break

            # ── 2. Drena pacchetti UDP in eccesso (anti-stale-frame) ──────────
            # Se il render ha impiegato più di 20ms, TORCS potrebbe aver già
            # inviato il frame successivo. Lo leggiamo per avere lo stato fresco.
            if C.so is not None:
                C.so.settimeout(0)          # non-blocking momentaneo
                try:
                    while True:
                        raw, _ = C.so.recvfrom(2**17)
                        decoded = raw.decode('utf-8')
                        if decoded and '***' not in decoded:
                            C.S.parse_server_str(decoded)   # aggiorna allo stato più recente
                except _socket.error:
                    pass                                    # coda svuotata
                finally:
                    C.so.settimeout(1)      # ripristina timeout normale

            # ── 3. Pompa eventi pygame (OGNI step, anche senza render) ────────
            # Necessario per evitare il freeze della finestra su Windows.
            win_close = hud.process_events()

            # ── 4. Leggi joypad ───────────────────────────────────────────────
            ctrl = xbox.read()
            if ctrl["quit"] or win_close:
                print("\n[INFO] Uscita richiesta.")
                running = False

            paused = ctrl["paused"]

            if paused:
                # ── MODALITÀ PAUSA ──────────────────────────────────────────
                # Dobbiamo comunque rispondere a TORCS altrimenti il server
                # pensa che il client si sia disconnesso e resetta la gara.
                # Inviamo freno leggero per fermare l’auto dolcemente.
                R = C.R.d
                R["accel"]  = 0.0
                R["brake"]  = 0.5    # freno leggero — l’auto rallenta e si ferma
                R["steer"]  = 0.0
                R["clutch"] = 0.0
                R["meta"]   = 0
                C.respond_to_server()
                # Render overlay pausa (time-gated)
                _now = time.monotonic()
                if _now - _hud_last >= _HUD_INTERVAL:
                    hud.render_paused(step, logger.filepath)
                    _hud_last = _now
                continue                          # salta log e applica comandi

            # ── 5. Applica comandi (solo se NON in pausa) ─────────────────
            R = C.R.d
            R["accel"]  = ctrl["accel"]
            R["brake"]  = ctrl["brake"]
            R["steer"]  = ctrl["steer"]
            R["gear"]   = ctrl["gear"]
            R["clutch"] = 0.0
            R["meta"]   = 0

            # ── 6. Invia al server (più vicino possibile alla lettura) ─────────
            C.respond_to_server()

            # ── 7. Conteggio giri ─────────────────────────────────────────────
            dist = C.S.d.get("distFromStart", 0.0)
            if _prev_dist is not None and dist < _prev_dist - LAP_WRAP_THRESHOLD:
                _laps_completed += 1
                print(f"[LAP] Giro {_laps_completed} completato!")
            _prev_dist = dist

            # ── 8. Log ────────────────────────────────────────────────────────
            step += 1
            logger.log_step(C.S.d, R)

            # ── 9. Render HUD — solo se è passato abbastanza tempo ────────────
            # Non blocca mai il loop: se non è il momento, salta.
            _now = time.monotonic()
            if _now - _hud_last >= _HUD_INTERVAL:
                hud.render(C.S.d, R, step, logger.filepath)
                _hud_last = _now

    except KeyboardInterrupt:
        print("\n[INFO] Ctrl+C rilevato — salvataggio log in corso...")
    except Exception as exc:
        print(f"\n[ERRORE] {exc}")

    finally:
        logger.save_and_close()
        C.shutdown()
        xbox.close()
        hud.close()
        print("\n[INFO] Sessione terminata correttamente.")


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

_HELP = """
Uso: python controller.py [opzioni]

Opzioni:
  -H, --host <host>    Host del server TORCS  [default: localhost]
  -p, --port <port>    Porta UDP di TORCS      [default: 3001]
  -t, --track <nome>   Nome della pista        [default: unknown]
  -u, --user <nome>    Nome utente nel log     [default: unknown]
  -m, --steps <n>      Step massimi per sessione [default: 100000]
  -h, --help           Mostra questo messaggio
"""

if __name__ == "__main__":
    host      = "localhost"
    port      = 3001
    track     = "unknown"
    user      = "unknown"
    max_steps = 100_000

    try:
        opts, _ = getopt.getopt(
            sys.argv[1:],
            "H:p:t:u:m:h",
            ["host=", "port=", "track=", "user=", "steps=", "help"],
        )
    except getopt.error as e:
        print(f"Errore opzioni: {e}\n{_HELP}")
        sys.exit(1)

    for opt, val in opts:
        if opt in ("-H", "--host"):
            host = val
        elif opt in ("-p", "--port"):
            port = int(val)
        elif opt in ("-t", "--track"):
            track = val
        elif opt in ("-u", "--user"):
            user = val
        elif opt in ("-m", "--steps"):
            max_steps = int(val)
        elif opt in ("-h", "--help"):
            print(_HELP)
            sys.exit(0)

    run_manual_session(host=host, port=port, track=track, user=user, max_steps=max_steps)
