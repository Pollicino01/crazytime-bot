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

# --- CREDENZIALI ---
TELEGRAM_TOKEN = "8754079194:AAEOU2e5HsWnUW1af_vOhEhf7LXU8KciHOM"
CHAT_ID        = "670873588"
PORT           = int(os.environ.get("PORT", 10000))

# --- CONFIG ---
TRACKSINO_URL = "https://tracksino.com/crazytime"

def _get_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8",
        "Referer": "https://tracksino.com/crazytime",
        "Origin": "https://tracksino.com"
    }

bot = telebot.TeleBot(TELEGRAM_TOKEN)

def invia(msg):
    try:
        bot.send_message(CHAT_ID, msg)
        log.info("📤 Messaggio inviato a Telegram")
    except Exception as e:
        log.error(f"Errore Telegram: {e}")

# --- PARSER NUXT ---
def _parse_nuxt_args(html):
    try:
        pm = re.search(r'window\.__NUXT__=\(function\(([^)]+)\)', html)
        if not pm: return {}
        params = [p.strip() for p in pm.group(1).split(",")]
        args_match = re.search(r'}\((.*)\)\)', html[html.find("window.__NUXT__"):])
        if not args_match: return {}
        args = [a.strip().strip('"').strip("'") for a in args_match.group(1).split(",")]
        return {params[i]: args[i] for i in range(min(len(params), len(args)))}
    except: return {}

# --- ESTRAZIONE DATI ---
def get_n5_spins_since():
    session = requests.Session()
    headers = _get_headers()
    try:
        # Carica prima la home per ottenere i cookie di sessione
        r = session.get(TRACKSINO_URL, headers=headers, timeout=20)
        if r.status_code != 200: return None
        html = r.text

        # 1. TENTATIVO JSON (Payload)
        build_match = re.search(r'"buildId"\s*:\s*"([^"]+)"', html)
        if build_match:
            b_id = build_match.group(1)
            p_url = f"https://tracksino.com/_nuxt/payloads/{b_id}/crazytime/payload.json"
            res_p = session.get(p_url, headers=headers, timeout=10)
            if res_p.status_code == 200:
                data = res_p.json()
                # Ricerca profonda del valore n5
                def find_n5(obj):
                    if isinstance(obj, dict):
                        if 'n5' in obj and 'spins_since' in obj['n5']: return obj['n5']['spins_since']
                        for v in obj.values():
                            res = find_n5(v)
                            if res is not None: return res
                    elif isinstance(obj, list):
                        for i in obj:
                            res = find_n5(i)
                            if res is not None: return res
                    return None
                
                val = find_n5(data)
                if val is not None:
                    log.info(f"🎯 [API JSON] n5: {val}")
                    return int(val)

        # 2. FALLBACK HTML (Se il JSON fallisce o è bloccato)
        log.info("🔄 Fallback su Parser HTML attivo...")
        n5_match = re.search(r'n5\s*:\s*\{spins_since\s*:\s*(\w+)', html)
        if n5_match:
            token = n5_match.group(1)
            if token.isdigit(): return int(token)
            mapping = _parse_nuxt_args(html)
            raw = mapping.get(token)
            if raw: return int(float(raw))
        return None
    except Exception as e:
        log.error(f"Errore: {e}")
        return None

# --- LOGICA GIOCO ---
stato, fase_ciclo, cicli_falliti, sessioni_contate, prev_spins = "FILTRO", 0, 0, 0, None

def process_spin(tipo):
    global stato, fase_ciclo, cicli_falliti, sessioni_contate
    is_cinque = (tipo == "5")
    if stato == "FILTRO":
        if fase_ciclo == 0 and is_cinque: fase_ciclo = 1
        elif fase_ciclo == 1: fase_ciclo = 0 if is_cinque else 2
        elif fase_ciclo == 2:
            if is_cinque: fase_ciclo = 0
            else:
                cicli_falliti += 1; fase_ciclo = 0
                invia(f"❌ Ciclo fallito {cicli_falliti}/8")
                if cicli_falliti >= 8:
                    stato, sessioni_contate = "SESSIONE", 0
                    invia("⚠️ TRIGGER ATTIVATO! Inizia SESSIONE (12 cicli).")
    elif stato == "SESSIONE":
        if fase_ciclo == 0 and is_cinque:
            invia(f"🎰 Ciclo {sessioni_contate + 1}/12 - PUNTA ORA!"); fase_ciclo = 1
        elif fase_ciclo == 1:
            if is_cinque: invia("✅ VINTO!"); stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else: fase_ciclo = 2; invia("⚠️ Perso 1° colpo")
        elif fase_ciclo == 2:
            if is_cinque: invia("✅ VINTO al 2°!"); stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else:
                sessioni_contate += 1; fase_ciclo = 0
                if sessioni_contate >= 12: invia("🛑 Sessione chiusa."); stato, cicli_falliti = "FILTRO", 0
                else: invia(f"❌ Ciclo perso. Restano {12-sessioni_contate}")

# --- SERVER ---
app = Flask(__name__)
@app.route('/')
def h(): return "Bot Online", 200

def bot_loop():
    global prev_spins
    invia("🚀 Bot Avviato con successo!")
    while True:
        curr = get_n5_spins_since()
        if curr is not None:
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
    bot_loop()
