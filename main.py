import os
import time
import re
import json
import telebot
from flask import Flask
from threading import Thread
from curl_cffi import requests  # Simulazione browser avanzata

# ── CONFIGURAZIONE ──────────────────────────────────────────
TOKEN      = os.environ.get("TELEGRAM_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
PORT       = int(os.environ.get("PORT", 10000))

TRACKSINO_URL = "https://tracksino.com"
POLL_INTERVAL = 20  # Aumentato per evitare ban per troppe richieste

if not TOKEN or not CHANNEL_ID:
    print("❌ ERRORE: Variabili d'ambiente mancanti!")
    exit(1)

bot = telebot.TeleBot(TOKEN)

# ── STATO ───────────────────────────────────────────────────
stato            = "FILTRO"
fase_ciclo       = 0
cicli_falliti    = 0
sessioni_contate = 0
prev_spins_since = None

def invia(msg):
    try:
        bot.send_message(CHANNEL_ID, msg)
        print(f"📤 Telegram inviato: {msg}")
    except Exception as e:
        print(f"❌ Errore Telegram: {e}")

# ── SCRAPING ANTI-BAN ───────────────────────────────────────
def get_n5_spins_since():
    try:
        # Usiamo impersonate="chrome110" per bypassare Cloudflare
        r = requests.get(
            TRACKSINO_URL, 
            impersonate="chrome110", 
            timeout=20
        )
        
        if r.status_code != 200:
            print(f"⚠️ Errore HTTP {r.status_code} su Tracksino")
            return None

        # Estrazione dati Nuxt
        pattern = r'window\.__NUXT__=\(function\((.*?)\)\{return (.*?)\}\((.*?)\)\)'
        match = re.search(pattern, r.text, re.DOTALL)
        if not match:
            print("⚠️ Struttura Nuxt non rilevata (possibile blocco JS)")
            return None

        params_raw = match.group(1).split(',')
        body = match.group(2)
        args_raw = match.group(3)

        args = json.loads(f"[{args_raw}]")
        mapping = {p.strip(): a for p, a in zip(params_raw, args)}
        
        n5_match = re.search(r'n5:\{spins_since:([a-zA-Z0-9_$]+)', body)
        if not n5_match: return None

        ref = n5_match.group(1)
        val = mapping.get(ref) if not ref.isdigit() else int(ref)
        
        return int(val) if val is not None else None
    except Exception as e:
        print(f"❌ Errore durante lo scraping: {e}")
        return None

# ── LOGICA ──────────────────────────────────────────────────
def process_spin(numero):
    global stato, fase_ciclo, cicli_falliti, sessioni_contate
    print(f"DEBUG Logic: spin={numero} | stato={stato} | falliti={cicli_falliti}")

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
                invia("✅ VINTO al 1° colpo!")
                stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else:
                fase_ciclo = 2
                invia("⚠️ Perso 1° colpo")
        elif fase_ciclo == 2:
            if numero == "5":
                invia("✅ VINTO al 2° colpo!")
                stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else:
                sessioni_contate += 1
                fase_ciclo = 0
                if sessioni_contate >= 12:
                    invia("🛑 Sessione chiusa senza vittoria.")
                    stato, cicli_falliti = "FILTRO", 0
                else:
                    invia(f"❌ Ciclo perso. Restano {12 - sessioni_contate} cicli.")

# ── SERVER ──────────────────────────────────────────────────
flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "✅ Bot Online con curl_cffi", 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT)

# ── LOOP ────────────────────────────────────────────────────
def bot_loop():
    global prev_spins_since
    invia("🚀 Monitoraggio Anti-Ban avviato!")

    while True:
        curr = get_n5_spins_since()
        
        if curr is not None:
            print(f"📊 n5 spins_since = {curr}")
            if prev_spins_since is not None and curr != prev_spins_since:
                if curr < prev_spins_since:
                    process_spin("5")
                    for _ in range(curr): process_spin("non5")
                else:
                    for _ in range(curr - prev_spins_since): process_spin("non5")
            prev_spins_since = curr
        else:
            print("⏳ Dati non disponibili in questo ciclo...")

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    while True:
        try:
            bot_loop()
        except Exception as e:
            print(f"💥 Errore critico nel loop: {e}")
            time.sleep(30)
