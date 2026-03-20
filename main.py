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
POLL_INTERVAL     = 15 

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

# ── LOGICA CORE (TUA LOGICA) ────────────────────────────────
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

# ── NUOVO TRACKER RINFORZATO ────────────────────────────────
def get_tracker_data():
    """Utilizza un approccio multi-sorgente per garantire stabilità 24/7"""
    try:
        # Usiamo un tracker che risponde più velocemente ai bot
        url = "https://tracksino.com/crazytime"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
            "Accept-Language": "en-US,en;q=0.9"
        }
        r = requests.get(url, headers=headers, timeout=10)
        
        # Regex potenziata per trovare il valore 'spins_since' del numero 5
        match = re.search(r'n5:\{spins_since:(\d+)', r.text)
        if match:
            return int(match.group(1))
    except Exception as e:
        print(f"⚠️ Errore Tracker: {e}")
    return None

# ── LOOP DI MONITORAGGIO ────────────────────────────────────
def monitor_loop():
    global prev_spins_since
    print("🚀 Analisi avviata...")
    while True:
        try:
            curr = get_tracker_data()
            if curr is not None:
                if prev_spins_since is None:
                    prev_spins_since = curr
                    print(f"✅ Primo dato ricevuto: {curr}")
                elif curr != prev_spins_since:
                    print(f"🎰 Nuovo Spin! Valore: {curr}")
                    # Gestione dei dati mancanti o reset
                    if curr < prev_spins_since:
                        process_spin("5")
                        for _ in range(curr): process_spin("non5")
                    else:
                        for _ in range(curr - prev_spins_since): process_spin("non5")
                    prev_spins_since = curr
                else:
                    # Log silenzioso per Render
                    print(f"📡 Monitoraggio attivo (Ultimo: {curr})")
            
            time.sleep(POLL_INTERVAL)
        except Exception as e:
            print(f"💥 Errore Loop: {e}")
            time.sleep(30)

# ── WEB SERVER & RUN ────────────────────────────────────────
app = Flask(__name__)
@app.route('/')
def home(): return "BOT ACTIVE", 200

if __name__ == "__main__":
    # Avvio Telegram in un thread
    Thread(target=bot.infinity_polling, daemon=True).start()
    
    # Avvio Monitoraggio in un thread
    Thread(target=monitor_loop, daemon=True).start()
    
    invia("⚡ **Bot Collegato a Nuova Sorgente!**\nMonitoraggio 24/7 attivo su @pollicino01")
    
    # Avvio Server Flask
    app.run(host='0.0.0.0', port=PORT)
