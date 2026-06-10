<p align="center">
  <img src="https://github.com/user-attachments/assets/c3843492-944e-4e54-aada-c09d36484daf" width="180">
</p>
<h1 align="center">
 AI TORCS Driver – Scuderia PIMBB
</h1>
<p align="center">
  AI Driver basato su Machine Learning per TORCS
</p>

<br>

## **Descrizione**

Progetto sviluppato nell’ambito della **IBM AI Racing League** per la realizzazione di un agente di **guida autonoma** nel simulatore **TORCS (The Open Racing Car Simulator)**.

Questo progetto implementa un sistema basato su **Intelligenza Artificiale**, progettato per controllare un veicolo minimizzando il tempo sul giro e massimizzando la stabilità.

<br>

## **Team – Scuderia PIMBB**

* Bello Daniel
* Bentivenga Antonio
* Iasevoli Lucia
* Palermo Euplio
* Maffettone Ester

<br>

## **Obiettivo Del Progetto**
Ottenere prestazioni elevate e guida stabile su circuiti complessi come *Corkscrew*.

**Approccio Adottato:** 
* Imitation Learning *(Behavioural Cloning)* per apprendere dai dati di guida.
* Utilizzo di una rete neurale per mappare i sensori alle azioni di guida.
* Analisi e utilizzo della telemetria del veicolo.
* Pipeline completa: raccolta dati, preprocessing e inferenza in tempo reale.



<br>

## **Struttura del Repository**

```bash
/scuderia_pimbb_project
│
├── /bot_tastiera        # Input Manuale / Simulato
├── /controller          # Acquisizione Dati
├── /models              # Modelli Addestrati
├── /logs                # Archiviazione Dati di Training 
├── snakeoil3_gym.py     # Interfaccia TORCS (client-server)
├── torcs_ai_driver.py   # Logica Principale di Guida
├── train_model.py       # Pipeline di Training
└── README.md            # Documentazione Tecnica del Progetto
```

<br>

## **Strumenti Utilizzati**

* **Ambiente di Simulazione:** TORCS 1.3.4

* **Linguaggio:** Python 3.11.15

* **Librerie e Dipendenze Principali**
   `sklearn` – StandardScaler e PCA\
   `numpy` – Calcolo Numerico\
   `pandas` – Gestione Dati\
   `json / jsonl` – Formato Dati\
   `socket` – Comunicazione UDP\
   `pygame / ctypes` – Input Joystick e Tastiera\
   `glob` – Persistenza Dati\
   `os / sys / getopt / time / datetime / random` – Sistema e Utility

* **AI Support:** IBM Granite *(supporto per sviluppo e debugging)*

<br>

## **Pipeline di Machine Learning**

Il modello segue una pipeline in **5 fasi principali**:

**1. Raccolta dati:** acquisizione dei dati dal simulatore TORCS tramite i sensori del veicolo.\
**2. Preprocessing:** normalizzazione e riduzione dimensionale (Scaler + PCA).\
**3. Training:** addestramento della rete neurale con PyTorch (Behavioural Cloning).\
**4. Export:** salvataggio del modello in formato JIT con preprocessing integrato.\
**5. Inferenza:** utilizzo in tempo reale per generare i comandi di guida nel simulatore.

<br>

## **Modello Neurale**

**Architettura:** Rete Neurale Feed-Forward (TorcsDriverNet) per la regressione delle azioni di guida.



<br>

## **Riferimenti**

* TORCS Official Docs
* Gym-TORCS
* IBM SkillsBuild
* IBM AI Racing League

<br>

## **Ringraziamenti**

Un ringraziamento a **IBM Granite** per il supporto nello sviluppo e nell’ottimizzazione del progetto.


