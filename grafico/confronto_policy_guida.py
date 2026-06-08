import pandas as pd
import matplotlib.pyplot as plt
import json
import glob
import os

def load_logs_by_prefix(folder_path, prefix):
    all_data = []
    search_pattern = os.path.join(folder_path, f"{prefix}*.jsonl")
    files = glob.glob(search_pattern)
    print(f"File trovati per '{prefix}': {len(files)}")
    
    for file in files:
        with open(file, 'r') as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    s = rec.get("sensors", {})
                    a = rec.get("actions", {})
                    if s and a:
                        all_data.append({'speedX': s.get('speedX', 0.0), 'steer': a.get('steer', 0.0)})
                except: continue
    return pd.DataFrame(all_data)

# 1. Caricamento Dati
df_tastiera = load_logs_by_prefix('logs', 'session')
df_joystick = load_logs_by_prefix('logs', 'log_gara')

# 2. Creazione della figura con due grafici (Subplots)
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))

# GRAFICO 1: Scatter Plot (Relazione Velocità-Sterzo)
# Disegniamo prima il Joystick (blu) e poi la Tastiera (rossa) per farla risaltare
ax1.scatter(df_joystick['speedX'], df_joystick['steer'], color='blue', label='Joystick', alpha=0.1, s=5)
ax1.scatter(df_tastiera['speedX'], df_tastiera['steer'], color='red', label='Tastiera', alpha=0.2, s=5)

ax1.set_title('Scatter Plot: Velocità vs Sterzo')
ax1.set_xlabel('Velocità (speedX)')
ax1.set_ylabel('Angolo di Sterzo')
ax1.legend(loc='upper right')
ax1.grid(True, linestyle='--')

# GRAFICO 2: Istogramma (Distribuzione dell'input)
# Usiamo histtype='step' per vedere solo i contorni e non coprire le aree
ax2.hist(df_joystick['steer'], bins=30, color='blue', histtype='step', linewidth=2, label='Joystick', density=True)
ax2.hist(df_tastiera['steer'], bins=30, color='red', histtype='step', linewidth=2, label='Tastiera', density=True)

ax2.set_title('Distribuzione Angolo di Sterzo')
ax2.set_xlabel('Angolo di Sterzo')
ax2.set_ylabel('Occorrenza')
ax2.legend(loc='upper right')
ax2.grid(True, linestyle='--')

plt.tight_layout()
plt.savefig('confronto_finale_analisi_migliorato.png', dpi=300)
plt.show()