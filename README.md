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
Ottenere prestazioni elevate su circuiti complessi come *Corkscrew*

**Approccio Adottato:** 
* Imitation Learning *(Behavioural Cloning)*
* Analisi della telemetria
* Pipeline di Machine Learning supervisionato



<br>

## **Struttura del Repository**

```bash
/scuderia_pimbb_project
│
├── /bot_tastiera        # Input manuale / simulato
├── /controller          # Acquisizione e logging telemetria
├── /models              # Modelli addestrati
│
├── snakeoil3_gym.py     # Interfaccia comunicazione TORCS (UDP)
├── torcs_ai_driver.py   # Logica principale di guida
├── train_model.py       # Pipeline di training
└── README.md
```

<br>

## **Strumenti Utilizzati**

* **Ambiente di Simulazione :** TORCS 1.3.4

* **Linguaggio :** Python 3.11.15

* **Librerie principali**

   `numpy` – Calcolo numerico\
   `pandas / jsonl` – Gestione dati\
   `socket` – Comunicazione UDP\
   `pygame / ctypes` – Input controller e tastiera\
   `json / pickle / glob` – Persistenza dati\
   `os / sys / getopt / time / datetime / random` – Sistema e Utility

* **AI Support :** IBM Granite *(copilota per sviluppo e debugging)*

<br>

## **Pipeline di Machine Learning**

Il modello segue una pipeline in **3 fasi principali**:

 **1. Preprocessing**  : Clipping dei valori (`np.clip`), Normalizzazione statistica *(StandardScaler)* e Riduzione dimensionale *(PCA)*
 **2. Training** : Paradigma *Behavioural Cloning*, Task regressione continua *(steer, accel, brake, gear)*
 **3. Inferenza** : Ottimizzazione tramite *JIT*, Output in tempo reale per il simulatore


<br>

## **Modello Neurale**

**Architettura:** Feed-Forward Deep Network (TorcsDriverNet)



<br>

## **Riferimenti**

* TORCS Official Docs
* Gym-TORCS
* IBM SkillsBuild
* IBM AI Racing League

<br>

## **Ringraziamenti**

Un sentito ringraziamento a **IBM Granite** per il contributo determinante nel supportare la progettazione, la generazione e l’ottimizzazione della logica algoritmica nelle fasi iniziali del progetto.


