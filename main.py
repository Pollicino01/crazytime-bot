import os
import time
import re
import requests
import telebot
from flask import Flask
from threading import Thread

# ── CREDENZIALI ─────────────────────────────────────────────
TOKEN      = "8754079194:AAEOU2e5HsWnUW1af_vOhEhf7LXU8KciHOM"
CHANNEL_ID = "@pollicino01"
PORT       = int(os.environ.get("PORT", 10000))

# PARAMETRI LOGICA (LA TUA)
SOGLIA_FALLIMENTI = 6  
MAX_SESSIONI      = 12 
POLL_INTERVAL     = 20 

bot = telebot.TeleBot(TOKEN)

# ── STATO ───────────────────────────────────────────────────
stato            = "FILTRO"   
fase_ciclo       = 0          
cicli_falliti    = 0          
sessioni_giocate = 0          
prev_spins_since = None

def invia(msg):
    try:
        bot.send_message(CHANNEL_ID, msg, parse_mode="Markdown")
    except Exception as e:
        print(f"❌ Errore Telegram: {e}")

def reset_totale():
    global stato, fase_ciclo, cicli_falliti, sessioni_giocate
    stato, fase_ciclo, cicli_falliti, sessioni_giocate = "FILTRO", 0, 0, 0

# ── LOGICA CORE (Filtro 6 / Sessione 12) ────────────────────
def process_spin(tipo_numero):
    global stato, fase_ciclo, cicli_falliti, sessioni_giocate
    
    if stato == "FILTRO":
        if fase_ciclo == 0:
            if tipo_numero == "5": fase_ciclo = 1
        elif fase_ciclo == 1:
            if tipo_numero == "5": cicli_falliti, fase_ciclo = 0, 0
            else: fase_ciclo = 2
        elif fase_ciclo == 2:
            if tipo_numero == "5": cicli_falliti, fase_ciclo = 0, 0
            else:
                cicli_falliti += 1
                fase_ciclo = 0
                # Ti avvisa nel canale così vedi che sta lavorando
                invia(f"📊 **Analisi:** Filtro a {cicli_falliti}/{SOGLIA_FALLIMENTI}")
                if cicli_falliti >= SOGLIA_FALLIMENTI:
                    stato, sessioni_giocate = "SESSIONE", 0
                    invia(f"🚨 **TRIGGER ATTIVATO!**\nInizio **SESSIONE** (12 cicli).")

    elif stato == "SESSIONE":
        if fase_ciclo == 0 and tipo_numero == "5":
            sessioni_giocate += 1
            invia(f"🎰 **Ciclo {sessioni_giocate}/{MAX_SESSIONI}**\n👉 Punta sul **5** (2 colpi)!")
            fase_ciclo = 1
        elif fase_ciclo == 1:
            if tipo_numero == "5":
                invia("✅ **VINTO al 1° colpo!**"); reset_totale()
            else: fase_ciclo = 2
        elif fase_ciclo == 2:
            if tipo_numero == "5":
                invia("✅ **VINTO al 2° colpo!**"); reset_totale()
            else:
                fase_ciclo = 0
                if sessioni_giocate >= MAX_SESSIONI:
                    invia("🛑 **Limite raggiunto.**"); reset_totale()
                else:
                    invia(f"❌ Ciclo perso. Restano {MAX_SESSIONI - sessioni_giocate} tentativi.")

# ── NUOVO TRACKER (SORGENTE ALTERNATIVA) ────────────────────
def get_tracker_data():
    """Prova a leggere i dati in modo più profondo"""
    try:
        # Usiamo un URL che spesso carica i dati più velocemente
        url = "https://tracksino.com/crazytime"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0",
            "Cache-Control": "no-cache"
        }
        r = requests.get(url, headers=headers, timeout=15)
        
        # Cerchiamo il valore 'spins_since' del numero 5
        # Se questo fallisce, il bot proverà al prossimo giro
        match = re.search(r'n5:\{spins_since:(\d+)', r.text)
        if match:
            return int(match.group(1))
    except:
        return None
    return None

# ── LOOP DI MONITORAGGIO ────────────────────────────────────
def monitor_loop():
    global prev_spins_since
    print("🚀 Analisi avviata con Tracker rinforzato...")
    while True:
        try:
            curr = get_tracker_data()
            if curr is not None:
                if prev_spins_since is None:
                    prev_spins_since = curr
                    print(f"✅ Primo dato ricevuto: {curr}")
                elif curr != prev_spins_since:
                    # RILEVATO NUOVO SPIN
                    if curr < prev_spins_since:
                        process_spin("5")
                        # Se sono passati più spin tra una lettura e l'altra
                        for _ in range(curr): process_spin("non5")
                    else:
                        for _ in range(curr - prev_spins_since): process_spin("non5")
                    prev_spins_since = curr
                else:
                    print(f"📡 Dati stabili: {curr}") # Monitoraggio log
            
            time.sleep(POLL_INTERVAL)
        except Exception as e:
            print(f"💥 Errore: {e}")
            time.sleep(30)

# ── WEB SERVER ──
app = Flask(__name__)
@app.route('/')
def home(): return "<h1>Bot Online 24/7</h1>", 200

if __name__ == "__main__":
    # Avvio Telegram
    Thread(target=bot.infinity_polling, daemon=True).start()
    # Avvio Analisi
    Thread(target=monitor_loop, daemon=True).start()
    
    invia("⚡ **Tracker Aggiornato.**\nAnalisi attiva 24/7 su @pollicino01")
    
    app.run(host='0.0.0.0', port=PORT)
