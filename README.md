<p aligh="center"> <img width="200" height="200" alt="logoboon" src="https://github.com/user-attachments/assets/c3843492-944e-4e54-aada-c09d36484daf" /> </p>
---

<h1 align="center"> # 🏎️ **AI TORCS Driver – Scuderia PIMBB** </h1>

---

## 📌 **Descrizione**

Progetto sviluppato nell’ambito della **IBM AI Racing League** per la realizzazione di un agente di **guida autonoma** nel simulatore **TORCS (The Open Racing Car Simulator)**.

Questo progetto implementa un sistema basato su **Intelligenza Artificiale**, progettato per controllare un veicolo minimizzando il tempo sul giro e massimizzando la stabilità.

### 🔍 Approccio adottato

* Imitation Learning *(Behavioural Cloning)*
* Analisi della telemetria
* Pipeline di Machine Learning supervisionato

🎯 **Obiettivo:** ottenere prestazioni elevate su circuiti complessi come *Corkscrew*

---

## 📁 **Struttura del Repository**

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

---

## ⚙️ **Strumenti Utilizzati**

### 🧪 Simulazione : TORCS 1.3.x

### 💻 Linguaggio : Python 3.11

### 📚 Librerie principali

* `numpy` – calcolo numerico
* `pandas` – gestione dati
* `socket` – comunicazione UDP
* `pygame` – input controller
* `json / pickle` – persistenza dati

### 🤖 AI Support : IBM Granite *(copilota per sviluppo e debugging)*

---

## 🧩 **Pipeline di Machine Learning**

Il modello segue una pipeline in **3 fasi principali**:

### 1️⃣ Preprocessing

* Clipping dei valori (`np.clip`)
* Normalizzazione statistica *(StandardScaler)*
* Riduzione dimensionale *(PCA)*

### 2️⃣ Training

* Paradigma: **Behavioural Cloning**
* Task: regressione continua *(steer, accel, brake, gear)*

### 3️⃣ Inferenza

* Ottimizzazione tramite **JIT**
* Output in tempo reale per il simulatore

---

## 🧠 **Modello Neurale**

Architettura:
**Feed-Forward Deep Network (TorcsDriverNet)**

---

## 👥 **Team – Scuderia PIMBB**

* Bello Daniel
* Bentivenga Antonio
* Iasevoli Lucia
* Palermo Euplio
* Maffettone Ester

---

## 📚 **Riferimenti**

* TORCS Official Docs
* Gym-TORCS
* IBM SkillsBuild
* IBM AI Racing League

---

## ⭐ **Ringraziamenti**

Un sentito ringraziamento a **IBM Granite** per il contributo determinante nel supportare la progettazione, la generazione e l’ottimizzazione della logica algoritmica nelle fasi iniziali del progetto.

---
