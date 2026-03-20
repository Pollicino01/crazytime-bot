import os
import time
import random
import logging
import requests
import telebot
import re
from flask import Flask
from threading import Thread

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("crazy-v7")

# --- CONFIGURAZIONE ---
TOKEN = "8754079194:AAEOU2e5HsWnUW1af_vOhEhf7LXU8KciHOM"
CHANNEL_ID = "@pollicino01"
PORT = int(os.environ.get("PORT", 10000))

bot = telebot.TeleBot(TOKEN)

# --- STATO ---
stato = "FILTRO"
fase_ciclo = 0
cicli_falliti = 0
sessioni_contate = 0
prev_spins = None

# --- PROVIDERS (Resilienza Totale) ---

def fetch_casinoscores():
    """Fonte 1: CasinoScores API"""
    try:
        url = "https://api.casinoscores.com/svc-evolution-game-events/api/events/crazytime/summary"
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            val = r.json().get('stats', {}).get('n5', {}).get('spins_since')
            return int(val) if val is not None else None
    except: return None

def fetch_tracksino_direct():
    """Fonte 2: Tracksino Scraper (Fallback di emergenza)"""
    try:
        url = "https://tracksino.com/crazytime"
        h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, headers=h, timeout=15)
        # Cerca il valore letterale n5 nell'HTML
        match = re.search(r'n5\s*:\s*\{spins_since\s*:\s*(\d+)', r.text)
        if match: return int(match.group(1))
    except: return None

def get_data_resilient():
    """Tenta tutte le fonti finché una non risponde."""
    for func in [fetch_casinoscores, fetch_tracksino_direct]:
        val = func()
        if val is not None: return val
    return None

# --- LOGICA DI GIOCO ---
def invia(msg):
    try:
        bot.send_message(CHANNEL_ID, msg)
        log.info(f"📤 Telegram: {msg[:30]}")
    except: log.error("❌ Telegram down")

def process_spin(tipo):
    global stato, fase_ciclo, cicli_falliti, sessioni_contate
    is_cinque = (tipo == "5")

    if stato == "FILTRO":
        if fase_ciclo == 0 and is_cinque: fase_ciclo = 1
        elif fase_ciclo == 1:
            if not is_cinque: fase_ciclo = 2
            else: fase_ciclo = 0
        elif fase_ciclo == 2:
            if is_cinque: fase_ciclo = 0
            else:
                cicli_falliti += 1; fase_ciclo = 0
                invia(f"❌ Ciclo fallito {cicli_falliti}/8")
                if cicli_falliti >= 8:
                    stato = "SESSIONE"; sessioni_contate = 0
                    invia("⚠️ TRIGGER! Inizio SESSIONE (12 cicli).")

    elif stato == "SESSIONE":
        if fase_ciclo == 0 and is_cinque:
            invia(f"🎰 Ciclo {sessioni_contate + 1}/12 — PUNTA SUL 5!")
            fase_ciclo = 1
        elif fase_ciclo == 1:
            if is_cinque:
                invia("✅ VINTO 1° colpo! 🎉"); stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else: fase_ciclo = 2; invia("⚠️ Riprova (2° colpo)!")
        elif fase_ciclo == 2:
            if is_cinque:
                invia("✅ VINTO 2° colpo! 🎉"); stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else:
                sessioni_contate += 1; fase_ciclo = 0
                if sessioni_contate >= 12:
                    invia("🛑 Fine sessione."); stato, cicli_falliti = "FILTRO", 0

# --- LOOP ---
def bot_loop():
    global prev_spins
    invia("🚀 Bot v7.0 ONLINE - Sistema Multi-Fonte Attivo")
    while True:
        curr = get_data_resilient()
        if curr is not None:
            if prev_spins is not None and curr != prev_spins:
                if curr < prev_spins:
                    process_spin("5")
                    for _ in range(curr): process_spin("non5")
                else:
                    for _ in range(curr - prev_spins): process_spin("non5")
            prev_spins = curr
        time.sleep(random.uniform(15, 25)) # Intervallo più lento per evitare ban

app = Flask(__name__)
@app.route('/')
def home(): return "OK", 200

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=PORT)).start()
    while True:
        try: bot_loop()
        except Exception as e:
            log.error(f"Crash: {e}"); time.sleep(30)
