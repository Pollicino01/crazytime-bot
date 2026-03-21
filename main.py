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
from keepalive import keepalive_loop

try:
    import cloudscraper
    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False

# ── LOGGING ──────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("casino-bot")

# ── CONFIG ───────────────────────────────────────────────────
TOKEN      = os.environ.get("TELEGRAM_TOKEN", "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
PORT       = int(os.environ.get("PORT", 10000))

# URL Target per CasinoScore
TARGET_URL = "https://casinoscore.com/crazytime/"

# Proxy estratti dallo screenshot dell'utente
PROXIES_LIST = [
    "http://gnrzyqfs:3lbaq4efyfv5@191.96.254.138:6185",
    "http://gnrzyqfs:3lbaq4efyfv5@198.23.239.134:6540",
    "http://gnrzyqfs:3lbaq4efyfv5@198.105.121.200:6462",
    "http://gnrzyqfs:3lbaq4efyfv5@216.10.27.159:6837"
]

def get_random_proxy():
    p = random.choice(PROXIES_LIST)
    return {"http": p, "https": p}

def _build_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8",
        "Connection": "keep-alive"
    }

# ── TELEGRAM ────────────────────────────────────────────────
bot = telebot.TeleBot(TOKEN)

def invia(msg):
    try:
        bot.send_message(CHANNEL_ID, msg)
        log.info(f"📤 Telegram: {msg[:50]}")
    except Exception as e:
        log.error(f"❌ Errore Telegram: {e}")

# ── LOGICA DI GIOCO (FILTRO/SESSIONE) ───────────────────────
stato = "FILTRO"
fase_ciclo = 0
cicli_falliti = 0
sessioni_contate = 0
prev_spins_since = None

def process_spin(numero):
    global stato, fase_ciclo, cicli_falliti, sessioni_contate
    is_cinque = (numero == "5")
    
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
                invia(f"❌ Ciclo Base fallito {cicli_falliti}/8")
                if cicli_falliti >= 8:
                    stato = "SESSIONE"
                    sessioni_contate = 0
                    invia("⚠️ TRIGGER ATTIVATO! Inizia SESSIONE - Attendi il prossimo 5.")

    elif stato == "SESSIONE":
        if fase_ciclo == 0 and is_cinque:
            invia(f"🎰 Sessione {sessioni_contate + 1}/12 — PUNTA sul prossimo 5!")
            fase_ciclo = 1
        elif fase_ciclo == 1:
            if is_cinque:
                invia("✅ VINTO al 1° colpo! 🎉")
                stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else:
                fase_ciclo = 2
                invia("⚠️ Perso 1° colpo — Punta ancora.")
        elif fase_ciclo == 2:
            if is_cinque:
                invia("✅ VINTO al 2° colpo! 🎉")
                stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else:
                sessioni_contate += 1
                fase_ciclo = 0
                if sessioni_contate >= 12:
                    invia("🛑 Sessione esaurita senza vittoria.")
                    stato, cicli_falliti = "FILTRO", 0
                else:
                    invia(f"❌ Ciclo perso. Restano {12 - sessioni_contate} cicli.")

# ── SCRAPER ──────────────────────────────────────────────────
def get_data():
    try:
        proxy = get_random_proxy()
        if CLOUDSCRAPER_AVAILABLE:
            s = cloudscraper.create_scraper()
            r = s.get(TARGET_URL, headers=_build_headers(), proxies=proxy, timeout=20)
        else:
            r = requests.get(TARGET_URL, headers=_build_headers(), proxies=proxy, timeout=20)
        
        if r.status_code == 200:
            # Estrazione n5.spins_since
            m = re.search(r'n5\s*:\s*\{\s*spins_since\s*:\s*(\d+)', r.text)
            if m: return int(m.group(1))
    except:
        pass
    return None

def bot_loop():
    global prev_spins_since
    log.info("🚀 Bot avviato su CasinoScore")
    invia("🚀 Bot Online!\n📡 Monitoraggio con rotazione Proxy attivo.")
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
        time.sleep(random.uniform(15, 22))

# ── FLASK SERVER ─────────────────────────────────────────────
app = Flask(__name__)
@app.route("/")
def home(): return "Bot Operativo", 200
@app.route("/ping")
def ping(): return "pong", 200

if __name__ == "__main__":
    # Avvio dei thread
    Thread(target=lambda: app.run(host="0.0.0.0", port=PORT, use_reloader=False), daemon=True).start()
    Thread(target=keepalive_loop, daemon=True).start()
    bot_loop()
