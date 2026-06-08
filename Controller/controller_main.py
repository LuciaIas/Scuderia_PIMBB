import os
import sys
import getopt

# Evita la creazione di file compilati __pycache__
sys.dont_write_bytecode = True

# Aggiungo la root del progetto a sys.path per importare il package Controller
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Controller.manual_session import run_manual_session


#  ----------- ENTRY POINT (OPZIONI CLI) -----------

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

def main():
    host      = "localhost"
    port      = 3001
    track     = "unknown"
    user      = "unknown"
    max_steps = 100_000

    try:
        # Prendo in input i parametri passati da riga di comando
        opts, _ = getopt.getopt(
            sys.argv[1:],
            "H:p:t:u:m:h",
            ["host=", "port=", "track=", "user=", "steps=", "help"],
        )
    except getopt.error as e:
        print(f"Errore opzioni: {e}\n{_HELP}")
        sys.exit(1)

    # Scorro le opzioni per configurare la sessione
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

    # Avvio la sessione di guida con le impostazioni scelte
    run_manual_session(host=host, port=port, track=track, user=user, max_steps=max_steps)

if __name__ == "__main__":
    main()
