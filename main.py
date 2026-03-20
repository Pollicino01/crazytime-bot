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

# Tentativo di import cloudscraper per bypass Cloudflare
try:
    import cloudscraper
    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False

# ── LOGGING ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("crazy-time-bot")

# ── CREDENZIALI & CONFIG ─────────────────────────────────────
# Inserite direttamente come richiesto
TELEGRAM_TOKEN = "8754079194:AAEOU2e5HsWnUW1af_vOhEhf7LXU8KciHOM"
CHAT_ID        = "670873588"
PORT           = int(os.environ.get("PORT", 10000))

TRACKSINO_URL  = "https://tracksino.com/crazytime"
POLL_MIN       = 12 
POLL_MAX       = 18

# ── ANTI-BAN: HEADERS ────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
]

def _build_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://tracksino.com/",
        "Connection": "keep-alive"
    }

def _get_scraper():
    if CLOUDSCRAPER_AVAILABLE:
        return cloudscraper.create_scraper(delay=random.randint(3, 6))
    return requests.Session()

# ── TELEGRAM ────────────────────────────────────────────────
bot = telebot.TeleBot(TELEGRAM_TOKEN)

def invia(msg):
    try:
        bot.send_message(CHAT_ID, msg)
        log.info(f"📤 Inviato a Telegram: {msg[:50]}...")
    except Exception as e:
        log.error(f"Errore Telegram: {e}")

# ── NUXT PARSER (FALLBACK ESTREMO) ──────────────────────────
def _parse_nuxt_args(html):
    try:
        pm = re.search(r'window\.__NUXT__=\(function\(([^)]+)\)', html)
        if not pm: return {}
        params = [p.strip() for p in pm.group(1).split(",")]
        
        nuxt_pos = html.find("window.__NUXT__=(")
        args_match = re.search(r'}\((.*)\)\)', html[nuxt_pos:nuxt_pos+600000])
        if not args_match: return {}
        
        args = [a.strip().strip('"').strip("'") for a in args_match.group(1).split(",")]
        return {params[i]: args[i] for i in range(min(len(params), len(args)))}
    except: return {}

# ── ESTRAZIONE DATI (API JSON + PARSER) ──────────────────────
def get_n5_spins_since():
    try:
        scraper = _get_scraper()
        headers = _build_headers()
        
        r = scraper.get(TRACKSINO_URL, headers=headers, timeout=25)
        if r.status_code != 200: 
            log.warning(f"Tracksino irraggiungibile (HTTP {r.status_code})")
            return None
        html = r.text

        # --- METODO 1: API PAYLOAD JSON (Ricerca Ricorsiva) ---
        build_match = re.search(r'"buildId"\s*:\s*"([^"]+)"', html)
        if build_match:
            build_id = build_match.group(1)
            payload_url = f"https://tracksino.com/_nuxt/payloads/{build_id}/crazytime/payload.json"
            
            res_payload = scraper.get(payload_url, headers=headers, timeout=15)
            if res_payload.status_code == 200:
                data = res_payload.json()
                
                # Cerca n5 in profondità nel JSON
                def find_n5(obj):
                    if isinstance(obj, dict):
                        if 'n5' in obj and isinstance(obj['n5'], dict):
                            return obj['n5'].get('spins_since')
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
                    log.info(f"🎯 [API JSON] n5 spins_since: {val}")
                    return int(val)

        # --- METODO 2: FALLBACK PARSER HTML ---
        log.info("🔄 API JSON non riuscita, uso Fallback Parser HTML...")
        n5_match = re.search(r'n5\s*:\s*\{spins_since\s*:\s*(\w+)', html)
        if n5_match:
            token = n5_match.group(1)
            if token.isdigit(): return int(token)
            
            mapping = _parse_nuxt_args(html)
            raw_val = mapping.get(token)
            if raw_val: return int(float(raw_val))

        return None
    except Exception as e:
        log.error(f"Errore estrazione: {e}")
        return None

# ── LOGICA GIOCO ─────────────────────────────────────────────
stato            = "FILTRO"
fase_ciclo       = 0
cicli_falliti    = 0
sessioni_contate = 0
prev_spins_since = None

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
                invia(f"❌ Ciclo Base fallito {cicli_falliti}/8")
                if cicli_falliti >= 8:
                    stato, sessioni_contate = "SESSIONE", 0
                    invia("⚠️ TRIGGER ATTIVATO!\nInizia SESSIONE di 12 cicli.\nAttendi il prossimo 5.")

    elif stato == "SESSIONE":
        if fase_ciclo == 0 and is_cinque:
            invia(f"🎰 Ciclo {sessioni_contate + 1}/12 — PUNTA SUL PROSSIMO 5!")
            fase_ciclo = 1
        elif fase_ciclo == 1:
            if is_cinque:
                invia("✅ VINTO al 1° colpo! 🎉")
                stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else:
                fase_ciclo = 2
                invia("⚠️ Perso 1° colpo — Riprova sul prossimo 5")
        elif fase_ciclo == 2:
            if is_cinque:
                invia("✅ VINTO al 2° colpo! 🎉")
                stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else:
                sessioni_contate += 1
                fase_ciclo = 0
                if sessioni_contate >= 12:
                    invia("🛑 12 cicli esauriti. Reset.")
                    stato, cicli_falliti = "FILTRO", 0
                else:
                    invia(f"❌ Ciclo perso. Restano {12-sessioni_contate} cicli.")

# ── WEB SERVER (KEEPALIVE) ───────────────────────────────────
app = Flask(__name__)
@app.route('/')
def health(): return "Bot Online", 200

def bot_loop():
    global prev_spins_since
    log.info("🚀 Monitoraggio avviato.")
    invia("🚀 Bot ONLINE\n📡 Monitoraggio n5 attivo.")
    
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
        time.sleep(random.uniform(POLL_MIN, POLL_MAX))

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=PORT, use_reloader=False)).start()
    bot_loop()
