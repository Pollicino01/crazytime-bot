import os
import re
import time
import json
import random
import logging
import requests
import telebot
from flask import Flask
from threading import Thread

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("crazy-time-bot")

# --- CREDENZIALI (Inserite direttamente per evitare errori) ---
TELEGRAM_TOKEN = "8754079194:AAEOU2e5HsWnUW1af_vOhEhf7LXU8KciHOM"
CHAT_ID        = "670873588"
PORT           = int(os.environ.get("PORT", 10000))
TRACKSINO_URL  = "https://tracksino.com/crazytime"

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- STATO MACCHINA ---
stato            = "FILTRO"
fase_ciclo       = 0
cicli_falliti    = 0
sessioni_contate = 0
prev_spins_since = None

def invia(msg):
    try:
        bot.send_message(CHAT_ID, msg)
        log.info(f"📤 Inviato: {msg[:30]}...")
    except Exception as e:
        log.error(f"Errore Telegram: {e}")

# --- LOGICA 8 FILTRO / 12 SESSIONE ---
def process_spin(tipo):
    global stato, fase_ciclo, cicli_falliti, sessioni_contate
    is_5 = (tipo == "5")

    if stato == "FILTRO":
        if fase_ciclo == 0 and is_5: 
            fase_ciclo = 1
        elif fase_ciclo == 1:
            fase_ciclo = 0 if is_5 else 2
        elif fase_ciclo == 2:
            if is_5: 
                fase_ciclo = 0
            else:
                cicli_falliti += 1
                fase_ciclo = 0
                invia(f"❌ Ciclo fallito {cicli_falliti}/8")
                if cicli_falliti >= 8:
                    stato, sessioni_contate = "SESSIONE", 0
                    invia("⚠️ TRIGGER! Inizia SESSIONE (12 cicli).")

    elif stato == "SESSIONE":
        if fase_ciclo == 0 and is_5:
            invia(f"🎰 Ciclo {sessioni_contate + 1}/12 - PUNTA ORA!")
            fase_ciclo = 1
        elif fase_ciclo == 1:
            if is_5:
                invia("✅ VINTO!")
                stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else:
                fase_ciclo = 2
                invia("⚠️ Perso 1° colpo")
        elif fase_ciclo == 2:
            if is_5:
                invia("✅ VINTO al 2°!")
                stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else:
                sessioni_contate += 1
                fase_ciclo = 0
                if sessioni_contate >= 12:
                    invia("🛑 Sessione chiusa.")
                    stato, cicli_falliti = "FILTRO", 0
                else:
                    invia(f"❌ Ciclo perso. Restano {12-sessioni_contate}")

# --- PARSER DATI ---
def get_data():
    try:
        h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0"}
        r = requests.get(f"{TRACKSINO_URL}?v={random.random()}", headers=h, timeout=15)
        if r.status_code != 200: return None
        
        # Estrazione sicura spins_since di n5
        match = re.search(r'n5\s*:\s*\{[^}]*spins_since\s*:\s*(\w+)', r.text)
        if match:
            t = match.group(1)
            if t.isdigit(): return int(t)
            v_match = re.search(f'"{t}":(\d+)', r.text)
            if v_match: return int(v_match.group(1))
        return None
    except: return None

# --- WEB SERVER PER RENDER ---
app = Flask(__name__)
@app.route('/')
def home(): return "BOT OK", 200

def loop():
    global prev_spins_since
    log.info("🚀 Monitoraggio avviato...")
    while True:
        curr = get_data()
        if curr is not None:
            if prev_spins_since is not None and curr != prev_spins_since:
                if curr < prev_spins_since:
                    process_spin("5")
                    for _ in range(curr): process_spin("non5")
                else:
                    for _ in range(curr - prev_spins_since): process_spin("non5")
            prev_spins_since = curr
        time.sleep(random.uniform(15, 25))

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=PORT)).start()
    loop()
