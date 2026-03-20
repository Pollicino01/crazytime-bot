import os
import time
import re
import requests
import telebot
import json
from flask import Flask
from threading import Thread

# ── CONFIGURAZIONE (Legge da Render Environment Variables) ──
TOKEN      = os.environ.get("TELEGRAM_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
PORT       = int(os.environ.get("PORT", 10000))

TRACKSINO_URL = "https://tracksino.com"
POLL_INTERVAL = 15 

if not TOKEN or not CHANNEL_ID:
    print("❌ ERRORE: Imposta TELEGRAM_TOKEN e CHANNEL_ID su Render!")
    exit(1)

bot = telebot.TeleBot(TOKEN)

# ── STATO DEL SISTEMA ───────────────────────────────────────
stato            = "FILTRO"
fase_ciclo       = 0
cicli_falliti    = 0
sessioni_contate = 0
prev_spins_since = None

# ── INVIO MESSAGGI ──────────────────────────────────────────
def invia(msg):
    try:
        bot.send_message(CHANNEL_ID, msg)
        print(f"📤 Telegram: {msg}")
    except Exception as e:
        print(f"❌ Errore Telegram: {e}")

# ── SCRAPING AVANZATO (ROBUSTO) ─────────────────────────────
def get_n5_spins_since():
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }
        r = requests.get(TRACKSINO_URL, headers=headers, timeout=15)
        if r.status_code != 200: return None

        pattern = r'window\.__NUXT__=\(function\((.*?)\)\{return (.*?)\}\((.*?)\)\)'
        match = re.search(pattern, r.text, re.DOTALL)
        if not match: return None

        params_raw = match.group(1).split(',')
        body = match.group(2)
        args_raw = match.group(3)

        try:
            args = json.loads(f"[{args_raw}]")
        except: return None

        mapping = {p.strip(): a for p, a in zip(params_raw, args)}
        
        n5_match = re.search(r'n5:\{spins_since:([a-zA-Z0-9_$]+)', body)
        if not n5_match: return None

        ref = n5_match.group(1)
        if ref.isdigit(): return int(ref)
        
        val = mapping.get(ref)
        return int(val) if val is not None else None
    except: return None

# ── LOGICA DI GIOCO ─────────────────────────────────────────
def process_spin(numero):
    global stato, fase_ciclo, cicli_falliti, sessioni_contate

    if stato == "FILTRO":
        if fase_ciclo == 0:
            if numero == "5": fase_ciclo = 1
        elif fase_ciclo == 1:
            if numero == "5": (fase_ciclo, cicli_falliti) = (0, 0)
            else: fase_ciclo = 2
        elif fase_ciclo == 2:
            if numero == "5": (fase_ciclo, cicli_falliti) = (0, 0)
            else:
                cicli_falliti += 1
                fase_ciclo = 0
                invia(f"❌ Ciclo Base fallito {cicli_falliti}/8")
                if cicli_falliti >= 8:
                    stato, sessioni_contate = "SESSIONE", 0
                    invia("⚠️ TRIGGER ATTIVATO! Inizia SESSIONE — 12 cicli disponibili.")

    elif stato == "SESSIONE":
        if fase_ciclo == 0:
            if numero == "5":
                invia(f"🎰 Sessione ciclo {sessioni_contate + 1}/12 — Punta sul prossimo 5!")
                fase_ciclo = 1
        elif fase_ciclo == 1:
            if numero == "5":
                invia("✅ VINTO al 1° colpo! Sessione terminata.")
                stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else:
                fase_ciclo = 2
                invia("⚠️ Perso 1° colpo — Punta ancora sul prossimo 5")
        elif fase_ciclo == 2:
            if numero == "5":
                invia("✅ VINTO al 2° colpo! Sessione terminata.")
                stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else:
                sessioni_contate += 1
                fase_ciclo = 0
                if sessioni_contate >= 12:
                    invia("🛑 12 cicli esauriti. Sessione chiusa.")
                    stato, cicli_falliti = "FILTRO", 0
                else:
                    invia(f"❌ Ciclo perso. Restano {12 - sessioni_contate} cicli.")

# ── WEB SERVER PER RENDER ───────────────────────────────────
flask_app = Flask(__name__)

@flask_app.route('/')
def home(): return "✅ Bot Online", 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT)

# ── LOOP PRINCIPALE ─────────────────────────────────────────
def bot_loop():
    global prev_spins_since
    print("🚀 Monitoraggio in corso...")
    invia("🚀 Bot Crazy Time ONLINE!")

    while True:
        curr = get_n5_spins_since()
        if curr is not None:
            if prev_spins_since is not None and curr != prev_spins_since:
                if curr < prev_spins_since:
                    process_spin("5")
                    for _ in range(curr): process_spin("non5")
                else:
                    for _ in range(curr - prev_spins_since): process_spin("non5")
            prev_spins_since = curr
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    while True:
        try:
            bot_loop()
        except Exception as e:
            print(f"💥 Errore critico: {e}")
            time.sleep(30)
            
