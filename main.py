"""
BOT CRAZY TIME v6.1 — Deploy Render.com
Logica: 5 Cicli di Fallimento -> Sessione 12 Cicli.
Reset totale dei fallimenti se il 5 esce al 1° o 2° colpo (Vittoria Ciclo Base).
"""

import os
import re
import time
import json
import random
import logging
import requests
import telebot
from typing import Optional, List
from flask import Flask
from threading import Thread

# Tentativo import keepalive (opzionale se hai il file keepalive.py)
try:
    from keepalive import keepalive_loop
    KEEPALIVE_AVAILABLE = True
except ImportError:
    KEEPALIVE_AVAILABLE = False

try:
    import cloudscraper
    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False

# ── LOGGING ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("crazy-time-bot")

# ── CONFIG ────────────────────────────────────────────────────
TOKEN      = os.environ.get("TELEGRAM_TOKEN", "8754079194:AAEOU2e5HsWnUW1af_vOhEhf7LXU8KciHOM")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@pollicino01")
PORT       = int(os.environ.get("PORT", 10000))

if not TOKEN or not CHANNEL_ID:
    raise RuntimeError("Imposta TELEGRAM_TOKEN e CHANNEL_ID nelle variabili d'ambiente")

POLL_MIN          = 13
POLL_MAX          = 19
MAX_CONSEC_ERRORS = 8
LONG_WAIT         = 90
MAX_RETRY_DELAY   = 120
TRIGGER_FALLIMENTI = 5  # <--- Aggiornato a 5 come richiesto

# ── URL SORGENTI ──────────────────────────────────────────────
TRACKSINO_PAGE   = "https://tracksino.com/crazytime"
TRACKSINO_API    = "https://tracksino.com/api/history/crazytime"
TRACKSINO_STATS  = "https://tracksino.com/api/stats/crazytime"
CZTIME_RESULTS   = "https://cztime.io/api/results"
CZTIME_HISTORY   = "https://cztime.io/api/history?limit=100"

# ── PROXY POOL ────────────────────────────────────────────────
_DEFAULT_PROXIES = [
    "191.96.254.138:6185:gnrzyqfs:3lbaq4efyfv5",
    "198.23.239.134:6540:gnrzyqfs:3lbaq4efyfv5",
    "198.105.121.200:6462:gnrzyqfs:3lbaq4efyfv5",
    "216.10.27.159:6837:gnrzyqfs:3lbaq4efyfv5",
]

def _parse_proxy_string(entry: str) -> Optional[dict]:
    parts = entry.strip().split(":")
    if len(parts) == 4:
        host, port, user, pw = parts
        url = f"http://{user}:{pw}@{host}:{port}"
    elif len(parts) == 2:
        host, port = parts
        url = f"http://{host}:{port}"
    else:
        return None
    return {"http": url, "https": url}

def _load_proxy_pool() -> List[dict]:
    env_list = os.environ.get("PROXY_LIST", "").strip()
    source   = env_list if env_list else ",".join(_DEFAULT_PROXIES)
    pool = []
    for entry in source.split(","):
        p = _parse_proxy_string(entry)
        if p: pool.append(p)
    return pool

PROXY_POOL:  List[dict] = []
_proxy_idx:  int        = 0

def _init_proxies():
    global PROXY_POOL
    PROXY_POOL = _load_proxy_pool()

def _next_proxy() -> Optional[dict]:
    global _proxy_idx
    if not PROXY_POOL: return None
    p = PROXY_POOL[_proxy_idx % len(PROXY_POOL)]
    _proxy_idx += 1
    return p

# ── HEADERS ───────────────────────────────────────────────────
USER_AGENTS = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"]

def _headers_html():
    return {"User-Agent": random.choice(USER_AGENTS), "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

def _headers_json(referer=None):
    h = {"User-Agent": random.choice(USER_AGENTS), "Accept": "application/json"}
    if referer: h["Referer"] = referer
    return h

# ── SESSIONI ──────────────────────────────────────────────────
_cs_session = None
_req_session = requests.Session()

def _get_scraper(proxy=None):
    global _cs_session
    if _cs_session is None and CLOUDSCRAPER_AVAILABLE:
        _cs_session = cloudscraper.create_scraper(browser='chrome')
    if _cs_session and proxy: _cs_session.proxies.update(proxy)
    return _cs_session if _cs_session else _req_session

# ── TELEGRAM ──────────────────────────────────────────────────
bot = telebot.TeleBot(TOKEN)

def invia(msg: str):
    try:
        bot.send_message(CHANNEL_ID, msg)
        log.info("📤 Telegram: %s", msg.replace('\n', ' '))
    except Exception as e:
        log.error("❌ Errore Telegram: %s", e)

# ── PARSERS ───────────────────────────────────────────────────
def _count_5_from_results(results: list) -> Optional[int]:
    if not results: return None
    spins = 0
    for item in results:
        outcome = str(item.get("result") or item.get("outcome") or item.get("slot") or "").strip()
        if outcome in ("5", "5x", "5X"): return spins
        spins += 1
    return spins

def get_n5_from_tracksino_html() -> Optional[int]:
    try:
        proxy = _next_proxy()
        scraper = _get_scraper(proxy)
        r = scraper.get(TRACKSINO_PAGE, headers=_headers_html(), timeout=25)
        if r.status_code != 200: return None
        html = r.text
        m = re.search(r'"5"\s*:\s*\{[^}]{0,200}?"spins_since"\s*:\s*(\d+)', html)
        if m: return int(m.group(1))
        m = re.search(r'n5\s*:\s*\{[^}]{0,300}?spins_since\s*:\s*(\d+)', html)
        if m: return int(m.group(1))
        return None
    except: return None

def get_n5_from_tracksino_api() -> Optional[int]:
    try:
        r = requests.get(TRACKSINO_STATS, headers=_headers_json(TRACKSINO_PAGE), timeout=15)
        data = r.json()
        n5 = data.get("n5") or data.get("5") or {}
        val = n5.get("spins_since")
        return val if isinstance(val, int) else None
    except: return None

def get_n5_from_cztime() -> Optional[int]:
    try:
        r = requests.get(CZTIME_RESULTS, headers=_headers_json("https://cztime.io/"), timeout=15)
        data = r.json()
        res = data.get("results") or data.get("data")
        return _count_5_from_results(res) if isinstance(res, list) else None
    except: return None

def get_n5_spins_since() -> Optional[int]:
    val = get_n5_from_tracksino_html()
    if val is not None: return val
    val = get_n5_from_tracksino_api()
    if val is not None: return val
    return get_n5_from_cztime()

# ── MACCHINA A STATI (Logica Pulita) ──────────────────────────
stato:            str          = "FILTRO"
fase_ciclo:       int          = 0
cicli_falliti:    int          = 0
sessioni_contate: int          = 0
prev_spins_since: Optional[int] = None

def reset_to_filter():
    global stato, fase_ciclo, cicli_falliti
    stato = "FILTRO"
    cicli_falliti = 0
    fase_ciclo = 0

def process_spin(numero: str):
    global stato, fase_ciclo, cicli_falliti, sessioni_contate

    is_cinque = (numero == "5")

    if stato == "FILTRO":
        if fase_ciclo == 0:
            if is_cinque:
                fase_ciclo = 1
                log.info("🎯 FILTRO: Trovato primo 5. Osservazione avviata.")

        elif fase_ciclo == 1:
            if is_cinque:
                # VINTO al 1° colpo: Reset totale fallimenti e attesa nuovo 5
                cicli_falliti = 0
                fase_ciclo = 0
                log.info("✅ FILTRO: 5 uscito al 1° colpo. Reset fallimenti.")
            else:
                fase_ciclo = 2

        elif fase_ciclo == 2:
            if is_cinque:
                # VINTO al 2° colpo: Reset totale fallimenti e attesa nuovo 5
                cicli_falliti = 0
                fase_ciclo = 0
                log.info("✅ FILTRO: 5 uscito al 2° colpo. Reset fallimenti.")
            else:
                # FALLIMENTO: 2 colpi senza 5
                cicli_falliti += 1
                fase_ciclo = 0
                invia(f"❌ Ciclo Base fallito {cicli_falliti}/{TRIGGER_FALLIMENTI}")
                
                if cicli_falliti >= TRIGGER_FALLIMENTI:
                    stato = "SESSIONE"
                    sessioni_contate = 0
                    invia(f"⚠️ TRIGGER {TRIGGER_FALLIMENTI}/{TRIGGER_FALLIMENTI} ATTIVATO!\n🔥 Inizia SESSIONE (12 cicli).\nAttendi il prossimo 5 per puntare.")

    elif stato == "SESSIONE":
        if fase_ciclo == 0:
            if is_cinque:
                sessioni_contate += 1
                invia(f"🎰 Ciclo {sessioni_contate}/12 — PUNTA su 5!")
                fase_ciclo = 1

        elif fase_ciclo == 1:
            if is_cinque:
                invia("✅ VINTO al 1° colpo! Profitto incassato. 🎉")
                reset_to_filter()
            else:
                fase_ciclo = 2
                invia("⚠️ 1° colpo perso — Punta ancora su 5")

        elif fase_ciclo == 2:
            if is_cinque:
                invia("✅ VINTO al 2° colpo! Profitto incassato. 🎉")
                reset_to_filter()
            else:
                fase_ciclo = 0
                if sessioni_contate >= 12:
                    invia("🛑 Limite 12 sessioni raggiunto. Stop temporaneo.")
                    reset_to_filter()
                else:
                    invia(f"❌ Ciclo {sessioni_contate}/12 perso. Aspetto il prossimo 5.")

# ── FLASK & LOOP ──────────────────────────────────────────────
flask_app = Flask(__name__)
@flask_app.route("/")
def home(): return "Bot Crazy Time v6.1 Active", 200

def bot_loop():
    global prev_spins_since
    log.info("🚀 Bot avviato con trigger a %d fallimenti", TRIGGER_FALLIMENTI)
    invia(f"🚀 Bot Online!\nTrigger: {TRIGGER_FALLIMENTI} fallimenti\nSessione: 12 cicli")

    while True:
        try:
            curr = get_n5_spins_since()
            if curr is not None:
                if prev_spins_since is not None and curr != prev_spins_since:
                    if curr < prev_spins_since:
                        process_spin("5")
                        for _ in range(curr): process_spin("non5")
                    else:
                        for _ in range(curr - prev_spins_since): process_spin("non5")
                prev_spins_since = curr
        except Exception as e:
            log.error("Loop error: %s", e)
        time.sleep(random.uniform(POLL_MIN, POLL_MAX))

if __name__ == "__main__":
    _init_proxies()
    Thread(target=lambda: flask_app.run(host="0.0.0.0", port=PORT), daemon=True).start()
    if KEEPALIVE_AVAILABLE: Thread(target=keepalive_loop, daemon=True).start()
    bot_loop()
