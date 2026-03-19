Variabili d'ambiente richieste:
  TELEGRAM_TOKEN  →  7781765395:AAHanJK1rZKZrvwh_Stu54n-YVrS3X_iGeU (da @BotFather)
  CHANNEL_ID      →  @pollicino03 (es. @miocanale)
"""

import os
import time
import re
import requests
import telebot
from flask import Flask
from threading import Thread

# ── CONFIG (da variabili d'ambiente) ────────────────────────
TOKEN      = os.environ.get("TELEGRAM_TOKEN", "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
PORT       = int(os.environ.get("PORT", 10000))

TRACKSINO_URL = "https://tracksino.com/crazytime"
POLL_INTERVAL = 10   # secondi tra una lettura e l'altra

if not TOKEN or not CHANNEL_ID:
    raise RuntimeError("Imposta le variabili d'ambiente TELEGRAM_TOKEN e CHANNEL_ID")

bot = telebot.TeleBot(TOKEN)

# ── STATO ───────────────────────────────────────────────────
stato            = "FILTRO"
fase_ciclo       = 0
cicli_falliti    = 0
sessioni_contate = 0
prev_spins_since = None

# ── TELEGRAM ────────────────────────────────────────────────
def invia(msg):
    try:
        bot.send_message(CHANNEL_ID, msg)
        print("📤 Telegram:", msg)
    except Exception as e:
        print("❌ Errore Telegram:", e)

# ── SCRAPING TRACKSINO ──────────────────────────────────────
def get_n5_spins_since():
    """Legge n5 spins_since dalla pagina Tracksino (window.__NUXT__)."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        r = requests.get(TRACKSINO_URL, headers=headers, timeout=15)
        if r.status_code != 200:
            print(f"⚠️ Tracksino HTTP {r.status_code}")
            return None

        match = re.search(
            r'window\.__NUXT__=\(function\(([^)]+)\)\{return (.+)\}\(([^)]+)\)\)',
            r.text, re.DOTALL
        )
        if not match:
            print("⚠️ NUXT data non trovata")
            return None

        params  = [p.strip() for p in match.group(1).split(',')]
        body    = match.group(2)
        args    = match.group(3).split(',')
        mapping = {params[i]: args[i].strip() for i in range(min(len(params), len(args)))}

        n5_match = re.search(r'n5:\{spins_since:(\w+),', body)
        if not n5_match:
            print("⚠️ n5 spins_since non trovato nel NUXT")
            return None

        var = n5_match.group(1)
        val = mapping.get(var, var)
        return int(val)

    except Exception as e:
        print(f"❌ Errore scraping: {e}")
        return None

# ── MACCHINA A STATI ─────────────────────────────────────────
def process_spin(numero):
    global stato, fase_ciclo, cicli_falliti, sessioni_contate

    print(f"🎰 Spin: {numero} | stato={stato} fase={fase_ciclo} falliti={cicli_falliti}")

    if stato == "FILTRO":
        if fase_ciclo == 0:
            if numero == "5":
                fase_ciclo = 1

        elif fase_ciclo == 1:
            if numero == "5":
                cicli_falliti = 0
                fase_ciclo = 0
            else:
                fase_ciclo = 2

        elif fase_ciclo == 2:
            if numero == "5":
                cicli_falliti = 0
                fase_ciclo = 0
            else:
                cicli_falliti += 1
                fase_ciclo = 0
                invia(f"❌ Ciclo Base fallito {cicli_falliti}/8")
                if cicli_falliti >= 8:
                    stato = "SESSIONE"
                    sessioni_contate = 0
                    invia("⚠️ TRIGGER ATTIVATO! Inizia SESSIONE — 12 cicli disponibili.")

    elif stato == "SESSIONE":
        if fase_ciclo == 0:
            if numero == "5":
                invia(f"🎰 Sessione ciclo {sessioni_contate + 1}/12 — Punta sul prossimo 5!")
                fase_ciclo = 1

        elif fase_ciclo == 1:
            if numero == "5":
                invia("✅ VINTO al 1° colpo! Sessione terminata con profitto.")
                stato = "FILTRO"
                cicli_falliti = 0
                fase_ciclo = 0
            else:
                fase_ciclo = 2
                invia("⚠️ Perso 1° colpo — Punta ancora sul prossimo 5")

        elif fase_ciclo == 2:
            if numero == "5":
                invia("✅ VINTO al 2° colpo! Sessione terminata con profitto.")
                stato = "FILTRO"
                cicli_falliti = 0
                fase_ciclo = 0
            else:
                sessioni_contate += 1
                fase_ciclo = 0
                rimanenti = 12 - sessioni_contate
                if sessioni_contate >= 12:
                    invia("🛑 12 cicli esauriti senza vittoria. Sessione chiusa.")
                    stato = "FILTRO"
                    cicli_falliti = 0
                else:
                    invia(f"❌ Ciclo perso. Restano {rimanenti} cicli in sessione.")

# ── FLASK KEEPALIVE ──────────────────────────────────────────
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "✅ Bot Crazy Time attivo", 200

@flask_app.route('/ping')
def ping():
    return "pong", 200

@flask_app.route('/healthz')
def healthz():
    return "ok", 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT)

# ── BOT LOOP ─────────────────────────────────────────────────
def bot_loop():
    global prev_spins_since
    errori_consecutivi = 0

    print("🚀 Bot Crazy Time avviato")
    invia("🚀 Bot Crazy Time ONLINE!\nMonitoraggio n5 attivo via Tracksino.")

    while True:
        try:
            curr = get_n5_spins_since()

            if curr is None:
                errori_consecutivi += 1
                print(f"⏳ Lettura fallita ({errori_consecutivi} consecutivi)...")
                if errori_consecutivi >= 10:
                    print("⚠️ 10 errori di fila, attendo 60s")
                    time.sleep(60)
                    errori_consecutivi = 0
                else:
                    time.sleep(POLL_INTERVAL)
                continue

            errori_consecutivi = 0
            print(f"📊 n5 spins_since = {curr} (precedente: {prev_spins_since})")

            if prev_spins_since is not None and curr != prev_spins_since:
                if curr < prev_spins_since:
                    process_spin("5")
                    for _ in range(curr):
                        process_spin("non5")
                else:
                    for _ in range(curr - prev_spins_since):
                        process_spin("non5")

            prev_spins_since = curr

        except Exception as e:
            print(f"❌ Errore nel loop: {e}")
            time.sleep(POLL_INTERVAL)

        time.sleep(POLL_INTERVAL)

# ── AVVIO ────────────────────────────────────────────────────
if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()

    while True:
        try:
            bot_loop()
        except Exception as e:
            print(f"💥 Crash: {e} — riavvio tra 30s")
            time.sleep(30)
