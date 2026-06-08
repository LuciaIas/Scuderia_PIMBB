import sys  # Importo la libreria per interagire col sistema
import os   # Importo la libreria per interagire con l'OS
from datetime import datetime   # Importo la libreria per interagire con la data e l'ora

# Evita la creazione di file compilati __pycache__ che possono intasare la directory
sys.dont_write_bytecode = True

# Aggiunge la directory padre (root) al sys.path per permettere l'importazione di funzioni dal
# modulo snakeoil3_gym
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from snakeoil3_gym import Client

# Importo la funzione di guida 'drive_example' dal file drive.py presente nella stessa cartella
from drive import drive_example


def ask_mode():
    """
    Funzione che mostra un menu testuale all'avvio per far scegliere all'utente
    la modalità di guida desiderata.
    Ritorna una tupla: (modalità_controllo, cambio_automatico_booleano)

    """
    print("\n" + "="*45)
    print("          CONFIGURAZIONE GUIDA")
    print("="*45)
    print(" [1] AI Completa (Automatico + Assistenza)")
    print(" [2] Manuale Assistita (Tastiera WASD + Cambio AUTO)")
    print(" [3] Manuale Pura (Tastiera WASD + Cambio MANUALE)")
    try:
        # Prende in input la scelta dell'utente eliminando eventuali spazi vuoti
        scelta = input("\n Scegli modalità (1/2/3) [Default 1]: ").strip()
    except EOFError:
        scelta = '1'    # Se l'input viene interrotto, imposta il default a '1'
        
    # Ritorna le impostazioni sotto forma di tupla a seconda della scelta
    if scelta == '2':
        return 'manual', True
    elif scelta == '3':
        return 'manual', False
    else:
        # Modalità 1 di default
        return 'auto', True


def setup_logging(C):
    """
    Inizializza le variabili per il sistema di logging in memoria e per il tracking dei giri.
    I dati verranno tenuti in memoria (C.records) per poi essere scritti tutti insieme a fine gara,
    evitando rallentamenti al programma.

    """

    C.records = []             # Lista dove salvare la telemetria per step 
    C.step_count = 0           # Contatore totale dei frame passati
    C.laps_completed = 0       # Numero di giri interi completati sulla pista
    C.prev_dist = None         # Memorizza la distanza dal traguardo al frame precedente
    C.race_completed = False   # Flag per indicare se la corsa è finita in modo valido (almeno 1 giro compiuto)


def main():

    mode, auto_gear = ask_mode()    # Chiedo all'utente la modalità di guida e cambio
    print(f"--- MODALITÀ: {mode.upper()} | CAMBIO: {'AUTO' if auto_gear else 'MANUAL'} ---")    # Stampa della modalità
    print("="*45 + "\n")

    C = Client(p=3001)  # Inizializza il client di connessione al server UDP di Torcs sulla porta 3001
    
    # Salva le impostazioni nel client in modo che il file drive.py le possa leggere per applicare i comandi
    C.control_mode = mode
    C.auto_gear = auto_gear
    
    setup_logging(C)    # Prepara le variabili interne necessarie per tenere traccia della sessione (logging)

    for step in range(C.maxSteps, 0, -1):  # Loop principale di gara: esegue l'aggiornamento un numero massimo di step stabiliti (maxSteps), procedendo al contrario
        
        C.get_servers_input()  # Attendo e ricevo l'ultimo pacchetto dal server (dati sensori del veicolo e pista)
        
        if not C.so:  # Se il socket (C.so) diventa None, la gara è terminata

            # Verifico se è stato terminato almeno 1 giro per considerare la sessione da salvare
            if C.laps_completed >= 1:
                C.race_completed = True
            break 
            
        
        drive_example(C)    # Chiama la logica di guida vera e propria, contenuta in drive.py
        

        # --- Rilevamento completamento giro reale ---
        
        dist = C.S.d.get("distFromStart", 0.0)  # distanza ciclica dal traguardo (si azzera quando si passa la linea del traguardo)
        dist_raced = C.S.d.get("distRaced", 0.0)    # distanza totale macinata dall'inizio assoluto, non si azzera mai

        
        # if per controllare se siamo tornati ad inizio gara (Distanza scesa improvvisamente di oltre 200m)
        if C.prev_dist is not None and dist < C.prev_dist - 200.0:

            # Ignoro il primo attraversamento del traguardo
            if dist_raced > 500.0: 
                C.laps_completed += 1 # Un giro intero vero è stato concluso!
                print(f"[LAP] Giro {C.laps_completed} completato!")
        
        
        C.prev_dist = dist  # Salviamo la distanza attuale
        

        # Invia acceleratore, freno, sterzo decisi da drive_example al server
        C.respond_to_server()

        
    # Verifico che la gara si sia chiusa correttamente
    if getattr(C, 'race_completed', False) and len(C.records) > 0:

        # Creo il nome del file da salvare nei log basandomi sulla data e sull'orario corrente per non sovrascrivere file passati
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True) # Crea la cartella se assente
        log_filename = os.path.join(log_dir, f"session_{timestamp}.jsonl")    # Nome del file dimanico, numerato in base a quello col numero più grande nella cartella
        
        # Scrivo nel file i dati del log
        with open(log_filename, mode='w', encoding='utf-8') as f:
            f.writelines(C.records)
            
        # Resoconto generale
        print(f"Log JSONL salvato con successo in: {log_filename}")
        print(f"Totale step registrati: {C.step_count}")
    else:
        # Gara ininfluente (pochi metri percorsi o terminata senza tagliare traguardi validi), si scartano i log 
        print("Gara non completata (minimo 1 giro richiesto). Log non salvato.")
        
    # Disconnette il client e rilascia le risorse di rete
    C.shutdown()



# Avvio del main
if __name__ == "__main__":
    main()
