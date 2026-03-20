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

# ── LOGGING ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("crazy-time-bot")

# ── CONFIGURAZIONE ───────────────────────────────────────────
# Il bot leggerà queste informazioni dalle "Environment Variables" di Render
TOKEN      = os.environ.get("TELEGRAM_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID") # Inserisci @pollicino01 su Render
PORT       = int(os.environ.get("PORT", 10000))

if not TOKEN or not CHANNEL_ID:
    log.error("❌ Errore: TELEGRAM_TOKEN o CHANNEL_ID non impostati su Render!")

bot = telebot.TeleBot(TOKEN)

# ── STATO DELLA LOGICA (8 FILTRO / 12 SESSIONE) ──────────────
stato            = "FILTRO"
fase_ciclo       = 0
cicli_falliti    = 0
sessioni_contate = 0
ultimo_timestamp = None 

def invia(msg):
    """Invia messaggi al canale Telegram"""
    try:
        bot.send_message(CHANNEL_ID, msg)
        log.info(f"📤 Telegram inviato: {msg[:40]}...")
    except Exception as e:
        log.error(f"⚠️ Errore invio Telegram: {e}")

# ── LOGICA DI ANALISI DEGLI SPIN ─────────────────────────────
def analizza_risultato(valore):
    global stato, fase_ciclo, cicli_falliti, sessioni_contate
    is_5 = (str(valore) == "5")

    if stato == "FILTRO":
        if fase_ciclo == 0 and is_5: 
            fase_ciclo = 1
        elif fase_ciclo == 1:
            if is_5: fase_ciclo = 0 # Reset se esce un altro 5 subito
            else: fase_ciclo = 2
        elif fase_ciclo == 2:
            if is_5: 
                fase_ciclo = 0
            else:
                # CICLO FALLITO
                cicli_falliti += 1
                fase_ciclo = 0
                invia(f"❌ Ciclo fallito {cicli_falliti}/8")
                if cicli_falliti >= 8:
                    stato, sessioni_contate = "SESSIONE", 0
                    invia("⚠️ TRIGGER! Inizia SESSIONE (12 cicli). Attendi il prossimo 5 per puntare.")

    elif stato == "SESSIONE":
        if fase_ciclo == 0 and is_5:
            invia(f"🎰 Ciclo {sessioni_contate + 1}/12 - PUNTA ORA SUL 5!")
            fase_ciclo = 1
        elif fase_ciclo == 1:
            if is_5:
                invia("✅ VINTO al 1° colpo! 🎉")
                stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else:
                fase_ciclo = 2
                invia("⚠️ Perso 1° colpo - Punta ancora sul 5")
        elif fase_ciclo == 2:
            if is_5:
                invia("✅ VINTO al 2° colpo! 🎉")
                stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else:
                sessioni_contate += 1
                fase_ciclo = 0
                if sessioni_contate >= 12:
                    invia("🛑 Sessione conclusa senza vincita. Reset a Filtro.")
                    stato, cicli_falliti = "FILTRO", 0
                else:
                    invia(f"❌ Ciclo perso. Restano {12-sessioni_contate} cicli nella sessione.")

# ── RECUPERO DATI (CASINOSCORES API) ─────────────────────────
def get_data():
    """Recupera gli ultimi spin da Casinoscores (più stabile di Tracksino)"""
    url = "https://api.casinoscores.com/svc-evolution-game-events/api/events/crazytime/recent?limit=3"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": "https://casinoscores.com"
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception as e:
        log.error(f"❌ Errore API: {e}")
        return None

# ── WEB SERVER (KEEPALIVE) ───────────────────────────────────
app = Flask(__name__)
@app.route('/')
def health(): return "BOT CRAZY TIME ONLINE", 200

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

# ── LOOP PRINCIPALE ──────────────────────────────────────────
def bot_loop():
    global ultimo_timestamp
    log.info("🚀 Monitoraggio avviato...")
    invia("🚀 Bot Crazy Time ONLINE\nSorgente: Casinoscores | Logica: 8/12")

    while True:
        dati = get_data()
        if dati and len(dati) > 0:
            ultimo_evento = dati[0]
            ts_attuale = ultimo_evento.get("id")
            risultato = str(ultimo_evento.get("result", ""))

            if ultimo_timestamp is not None and ts_attuale != ultimo_timestamp:
                log.info(f"🎰 Nuovo numero: {risultato}")
                analizza_risultato(risultato)
            
            ultimo_timestamp = ts_attuale
        
        # Attesa casuale per evitare blocchi
        time.sleep(random.uniform(10, 15))

if __name__ == "__main__":
    # Avvia Flask per mantenere vivo il servizio su Render
    Thread(target=run_flask, daemon=True).start()
    
    # Avvia il monitoraggio
    while True:
        try:
            bot_loop()
        except Exception as e:
            log.error(f"💥 Crash: {e}. Riavvio tra 20 secondi...")
            time.sleep(20)
