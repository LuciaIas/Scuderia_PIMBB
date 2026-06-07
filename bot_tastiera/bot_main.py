import sys
import os
from datetime import datetime

# Prevent creation of __pycache__
sys.dont_write_bytecode = True

# Aggiungi root al sys.path per snakeoil3_gym
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from snakeoil3_gym import Client

# Aggiungi cartella corrente per importare drive
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from drive import drive_example

def ask_mode(C):
    print("\n" + "="*45)
    print("          CONFIGURAZIONE GUIDA")
    print("="*45)
    print(" [1] AI Completa (Automatico + Assistenza)")
    print(" [2] Manuale Assistita (Tastiera WASD + Cambio AUTO)")
    print(" [3] Manuale Pura (Tastiera WASD + Cambio MANUALE)")
    try:
        scelta = input("\n Scegli modalità (1/2/3) [Default 1]: ").strip()
    except EOFError:
        scelta = '1'
        
    if scelta == '2':
        C.control_mode = 'manual'
        C.auto_gear = True
    elif scelta == '3':
        C.control_mode = 'manual'
        C.auto_gear = False
    else:
        C.control_mode = 'auto'
        C.auto_gear = True
        
    print(f"--- MODALITÀ: {C.control_mode.upper()} | CAMBIO: {'AUTO' if C.auto_gear else 'MANUAL'} ---")
    print("="*45 + "\n")

def setup_logging(C):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
        
    C.log_filename = os.path.join(log_dir, f"telemetry_{timestamp}.jsonl")
    C.log_file = open(C.log_filename, mode='w', encoding='utf-8')
    C.step_count = 0 
    print(f"Logging JSONL avviato su: {C.log_filename}")

def main():
    C = Client(p=3001)
    
    ask_mode(C)
    setup_logging(C)

    for step in range(C.maxSteps, 0, -1):
        C.get_servers_input()
        if not C.so: 
            break 
        drive_example(C)
        C.respond_to_server()
        
    if hasattr(C, 'log_file') and not C.log_file.closed:
        C.log_file.close()
        print(f"Log JSONL salvato con successo in: {C.log_filename}")
        print(f"Totale step registrati: {C.step_count}")
        
    C.shutdown()

if __name__ == "__main__":
    main()
