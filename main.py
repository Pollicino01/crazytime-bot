import os
import time
import random
import logging
import requests
import telebot
from flask import Flask
from threading import Thread

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("crazy-time-immortal")

# --- CONFIGURAZIONE DIRETTA ---
TOKEN = "8754079194:AAEOU2e5HsWnUW1af_vOhEhf7LXU8KciHOM"
CHANNEL_ID = "@pollicino01"
PORT = int(os.environ.get("PORT", 10000))

bot = telebot.TeleBot(TOKEN)

# --- STATO MACCHINA ---
stato = "FILTRO"
fase_ciclo = 0
cicli_falliti = 0
sessioni_contate = 0
prev_spins = None
errori_consecutivi = 0

# --- FUNZIONI TELEGRAM ---
def invia(msg):
    """Invia messaggi al canale con retry automatico."""
    try:
        bot.send_message(CHANNEL_ID, msg)
        log.info(f"📤 Telegram: {msg[:40]}...")
    except Exception as e:
        log.error(f"❌ Errore Telegram: {e}")

# --- FETCH DATI (API CASINOSCORES) ---
def get_data():
    """Recupera n5.spins_since dall'API evitando lo scraping HTML di Tracksino."""
    global errori_consecutivi
    try:
        url = "https://api.casinoscores.com/svc-evolution-game-events/api/events/crazytime/summary"
        r = requests.get(url, timeout=10)
        
        if r.status_code == 200:
            errori_consecutivi = 0
            data = r.json()
            spins = data.get('stats', {}).get('n5', {}).get('spins_since')
            return int(spins) if spins is not None else None
            
        errori_consecutivi += 1
        return None
    except Exception as e:
        log.error(f"⚠️ Errore API: {e}")
        errori_consecutivi += 1
        return None

# --- LOGICA DI GIOCO ---
def process_spin(tipo):
    global stato, fase_ciclo, cicli_falliti, sessioni_contate
    is_cinque = (tipo == "5")

    if stato == "FILTRO":
        if fase_ciclo == 0 and is_cinque: 
            fase_ciclo = 1
        elif fase_ciclo == 1:
            if is_cinque: fase_ciclo = 0
            else: fase_ciclo = 2
        elif fase_ciclo == 2:
            if is_cinque: fase_ciclo = 0
            else:
                cicli_falliti += 1
                fase_ciclo = 0
                invia(f"❌ Ciclo fallito {cicli_falliti}/8")
                if cicli_falliti >= 8:
                    stato = "SESSIONE"
                    sessioni_contate = 0
                    invia("⚠️ TRIGGER! Inizia SESSIONE (12 cicli).")

    elif stato == "SESSIONE":
        if fase_ciclo == 0:
            if is_cinque:
                invia(f"🎰 Ciclo {sessioni_contate + 1}/12 — PUNTA SUL 5!")
                fase_ciclo = 1
        elif fase_ciclo == 1:
            if is_cinque:
                invia("✅ VINTO al 1° colpo! 🎉")
                stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else:
                fase_ciclo = 2
                invia("⚠️ Perso 1° colpo — Rigiocalo!")
        elif fase_ciclo == 2:
            if is_cinque:
                invia("✅ VINTO al 2° colpo! 🎉")
                stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else:
                sessioni_contate += 1
                fase_ciclo = 0
                if sessioni_contate >= 12:
                    invia("🛑 Sessione chiusa (12 cicli esauriti).")
                    stato, cicli_falliti = "FILTRO", 0
                else:
                    invia(f"❌ Ciclo perso. Restano {12 - sessioni_contate} cicli.")

# --- MAIN LOOP ---
def bot_loop():
    global prev_spins, errori_consecutivi
    invia("🚀 Bot Crazy Time ONLINE\nMonitoraggio API attivo.")
    
    while True:
        curr = get_data()
        
        # Alert errori prolungati
        if errori_consecutivi == 10:
            invia("🚨 ATTENZIONE: 10 errori API consecutivi. Fonte instabile.")
        
        if curr is not None:
            if prev_spins is not None and curr != prev_spins:
                if curr < prev_spins:
                    process_spin("5")
                    for _ in range(curr): process_spin("non5")
                else:
                    for _ in range(curr - prev_spins): process_spin("non5")
            prev_spins = curr
            
        time.sleep(random.uniform(12, 18))

# --- SERVER FLASK ---
app = Flask(__name__)
@app.route('/')
def home(): return "OK", 200

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=PORT)).start()
    while True:
        try:
            bot_loop()
        except Exception as e:
            log.error(f"💥 Crash: {e}")
            time.sleep(30)
