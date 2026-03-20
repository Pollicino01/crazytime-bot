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
log = logging.getLogger("crazy-time-v6")

# --- CONFIGURAZIONE ---
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
errori_totali = 0

# --- PROVIDER DI DATI (Multi-Source) ---

def fetch_casinoscores():
    """Fonte 1: CasinoScores API"""
    try:
        url = "https://api.casinoscores.com/svc-evolution-game-events/api/events/crazytime/summary"
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            val = r.json().get('stats', {}).get('n5', {}).get('spins_since')
            return int(val) if val is not None else None
    except: return None

def fetch_crazytime_games():
    """Fonte 2: CrazyTime.games (Fallback)"""
    try:
        url = "https://crazytime.games/api/stats"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            # Esempio di parsing per questa API specifica
            return int(r.json().get('n5_spins_since'))
    except: return None

def get_data_resilient():
    """Orchestratore: prova tutte le fonti disponibili."""
    for func in [fetch_casinoscores, fetch_crazytime_games]:
        val = func()
        if val is not None:
            return val
    return None

# --- LOGICA DI GIOCO ---
def invia(msg):
    try:
        bot.send_message(CHANNEL_ID, msg)
        log.info(f"📤 Inviato a Telegram: {msg[:30]}")
    except Exception as e:
        log.error(f"❌ Errore Telegram: {e}")

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
                cicli_falliti += 1
                fase_ciclo = 0
                invia(f"❌ Ciclo fallito {cicli_falliti}/8")
                if cicli_falliti >= 8:
                    stato = "SESSIONE"
                    sessioni_contate = 0
                    invia("⚠️ TRIGGER! Inizio SESSIONE (12 cicli).")

    elif stato == "SESSIONE":
        # Logica sessione (12 cicli / 2 colpi)
        if fase_ciclo == 0 and is_cinque:
            invia(f"🎰 Ciclo {sessioni_contate + 1}/12 — PUNTA SUL 5!")
            fase_ciclo = 1
        elif fase_ciclo == 1:
            if is_cinque:
                invia("✅ VINTO al 1° colpo! 🎉"); stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else:
                fase_ciclo = 2; invia("⚠️ Riprova (2° colpo)!")
        elif fase_ciclo == 2:
            if is_cinque:
                invia("✅ VINTO al 2° colpo! 🎉"); stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else:
                sessioni_contate += 1; fase_ciclo = 0
                if sessioni_contate >= 12:
                    invia("🛑 Fine sessione."); stato, cicli_falliti = "FILTRO", 0

# --- LOOP E SERVER ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Online", 200

def bot_loop():
    global prev_spins, errori_totali
    invia("🚀 Bot Crazy Time v6.0 Online!")
    while True:
        curr = get_data_resilient()
        if curr is None:
            errori_totali += 1
            if errori_totali == 10: invia("🚨 Tutte le fonti API sono giù!")
        else:
            errori_totali = 0
            if prev_spins is not None and curr != prev_spins:
                if curr < prev_spins:
                    process_spin("5")
                    for _ in range(curr): process_spin("non5")
                else:
                    for _ in range(curr - prev_spins): process_spin("non5")
            prev_spins = curr
        time.sleep(random.uniform(12, 18))

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=PORT)).start()
    while True:
        try: bot_loop()
        except Exception as e:
            log.error(f"Crash: {e}"); time.sleep(20)
