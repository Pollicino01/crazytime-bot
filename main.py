"""
BOT CRAZY TIME v7.5 — Deploy Render.com
Logica a Doppio Contatore Differenziale (1 vs 5)
Monitora il gioco Crazy Time e invia segnali Telegram.

Sorgenti dati (cascata automatica):
  1. Tracksino HTML — parser Nuxt 2 IIFE + Nuxt 3 __NUXT_DATA__ + regex dirette
  2. Tracksino JSON API interna
  3. Cztime.io API (tracker Evolution ufficiale)
  4. Fallback con ricerca testuale estesa

Proxy: hardcoded + override da variabile d'ambiente PROXY_LIST
"""

import os
import re
import time
import json
import random
import logging
import requests
import telebot
from typing import Optional, List, Dict
from flask import Flask
from threading import Thread

# Gestione opzionale del keepalive
try:
    from keepalive import keepalive_loop
except ImportError:
    def keepalive_loop():
        pass

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
TARGET_NUMBER = "5"
HEARTBEAT_NUMBER = "1"

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

# ── URL SORGENTI ──────────────────────────────────────────────
TRACKSINO_PAGE   = "https://tracksino.com/crazytime"
TRACKSINO_API    = "https://tracksino.com/api/history/crazytime"
TRACKSINO_STATS  = "https://tracksino.com/api/stats/crazytime"

# cztime.io è un tracker Evolution indipendente con API pubblica
CZTIME_RESULTS   = "https://cztime.io/api/results"
CZTIME_HISTORY   = "https://cztime.io/api/history?limit=100"

# ── PROXY POOL — hardcoded + override da env ──────────────────
_DEFAULT_PROXIES = [
    "191.96.254.138:6185:gnrzyqfs:3lbaq4efyfv5",
    "198.23.239.134:6540:gnrzyqfs:3lbaq4efyfv5",
    "198.105.121.200:6462:gnrzyqfs:3lbaq4efyfv5",
    "216.10.27.159:6837:gnrzyqfs:3lbaq4efyfv5",
]

def _parse_proxy_string(entry: str) -> Optional[dict]:
    """Converte 'ip:porta:user:pass' o 'ip:porta' in dizionario proxy."""
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
    """Carica i proxy. Priorità: env PROXY_LIST > lista hardcoded."""
    env_list = os.environ.get("PROXY_LIST", "").strip()
    source   = env_list if env_list else ",".join(_DEFAULT_PROXIES)

    pool = []
    for entry in source.split(","):
        p = _parse_proxy_string(entry)
        if p:
            pool.append(p)

    if pool:
        log.info("📡 Proxy pool: %d proxy caricati", len(pool))
    else:
        log.warning("⚠️ Nessun proxy valido — connessione diretta")
    return pool

PROXY_POOL:  List[dict] = []
_proxy_idx:  int        = 0

def _init_proxies():
    global PROXY_POOL
    PROXY_POOL = _load_proxy_pool()

def _next_proxy() -> Optional[dict]:
    """Round-robin sul pool di proxy."""
    global _proxy_idx
    if not PROXY_POOL:
        return None
    p = PROXY_POOL[_proxy_idx % len(PROXY_POOL)]
    _proxy_idx += 1
    return p

# ── USER-AGENT POOL ───────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

ACCEPT_LANGUAGES = ["en-US,en;q=0.9", "en-GB,en;q=0.9,en;q=0.8", "en-US,en;q=0.9,it;q=0.8"]

def _headers_html(referer: Optional[str] = None) -> dict:
    h = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": random.choice(ACCEPT_LANGUAGES),
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "no-cache",
        "DNT": "1",
    }
    if referer: h["Referer"] = referer
    return h

def _headers_json(referer: Optional[str] = None) -> dict:
    h = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": random.choice(ACCEPT_LANGUAGES),
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }
    if referer: h["Referer"] = referer
    return h

# ── SESSIONI CLOUDSCRAPER ─────────────────────────────────────
SESSION_ROTATE_EVERY = 35
_cs_session          = None
_req_session         = requests.Session()
_session_counter     = 0

BROWSERS = [{"browser": "chrome", "platform": "windows", "mobile": False}, {"browser": "firefox", "platform": "windows", "mobile": False}]

def _new_cloudscraper(proxy: Optional[dict] = None):
    if not CLOUDSCRAPER_AVAILABLE: return None
    try:
        s = cloudscraper.create_scraper(browser=random.choice(BROWSERS), delay=random.randint(3, 8))
        if proxy: s.proxies.update(proxy)
        return s
    except Exception as e:
        log.warning("Cloudscraper init fallito: %s", e)
        return None

def _get_scraper(proxy: Optional[dict] = None):
    global _cs_session, _req_session, _session_counter
    _session_counter += 1
    if _session_counter >= SESSION_ROTATE_EVERY:
        log.info("🔄 Rotazione sessione (ciclo %d)", _session_counter)
        try:
            if _cs_session: _cs_session.close()
        except: pass
        _cs_session = _new_cloudscraper(proxy)
        _req_session = requests.Session()
        if proxy: _req_session.proxies.update(proxy)
        _session_counter = 0
    if _cs_session is None: _cs_session = _new_cloudscraper(proxy)
    return _cs_session if _cs_session else _req_session

def _init_sessions():
    global _cs_session
    _cs_session = _new_cloudscraper(_next_proxy())
    if _cs_session: log.info("✅ Cloudscraper attivo — bypass Cloudflare abilitato")

# ── TELEGRAM ──────────────────────────────────────────────────
bot = telebot.TeleBot(TOKEN, parse_mode=None)

def invia(msg: str) -> bool:
    for tentativo in range(3):
        try:
            bot.send_message(CHANNEL_ID, msg)
            log.info("📤 Telegram OK: %s", msg[:80].replace('\n', ' '))
            return True
        except Exception as e:
            log.warning("⚠️ Telegram errore (tentativo %d/3): %s", tentativo + 1, e)
            if tentativo < 2: time.sleep(5 * (tentativo + 1))
    return False

def _valid_spins(val: Optional[int]) -> Optional[int]:
    if val is None or val < 0: return None
    return val

# ═══════════════════════════════════════════════════════════════
# SORGENTE 1 — TRACKSINO HTML DOPPIO CONTATORE
# ═══════════════════════════════════════════════════════════════

def _extract_from_nuxt3_data(html: str) -> Dict[str, Optional[int]]:
    results = {HEARTBEAT_NUMBER: None, TARGET_NUMBER: None}
    m = re.search(r'<script[^>]+id=["\']__NUXT_DATA__["\'][^>]*>([\s\S]*?)</script>', html, re.IGNORECASE)
    if not m: return results
    try:
        data = json.loads(m.group(1))
        if not isinstance(data, list): return results
        
        for num in [HEARTBEAT_NUMBER, TARGET_NUMBER]:
            for i, v in enumerate(data):
                if v == "spins_since" and i + 1 < len(data):
                    candidate = data[i + 1]
                    if isinstance(candidate, int) and candidate >= 0:
                        ctx = data[max(0, i-20):i]
                        if num in ctx or int(num) in ctx:
                            results[num] = candidate
                            break
    except: pass
    return results

def _extract_direct_patterns(html: str) -> Dict[str, Optional[int]]:
    results = {HEARTBEAT_NUMBER: None, TARGET_NUMBER: None}
    for num in [HEARTBEAT_NUMBER, TARGET_NUMBER]:
        m = re.search(rf'"{num}"\s*:\s*\{{[^}}{{]{{0,200}}?"spins_since"\s*:\s*(\d+)', html)
        if m: results[num] = int(m.group(1))
        
        if results[num] is None:
            m = re.search(rf'n{num}\s*:\s*\{{[^}}{{]{{0,300}}?spins_since\s*:\s*(\d+)', html)
            if m: results[num] = int(m.group(1))
    return results

def get_stats_from_tracksino_html() -> Dict[str, Optional[int]]:
    try:
        time.sleep(random.uniform(0.4, 1.2))
        proxy   = _next_proxy()
        scraper = _get_scraper(proxy)
        r       = scraper.get(TRACKSINO_PAGE, headers=_headers_html(), timeout=30)

        if r.status_code != 200: return {HEARTBEAT_NUMBER: None, TARGET_NUMBER: None}
        html = r.text

        res = _extract_from_nuxt3_data(html)
        if res[HEARTBEAT_NUMBER] is not None and res[TARGET_NUMBER] is not None: 
            return res

        res_regex = _extract_direct_patterns(html)
        if res[HEARTBEAT_NUMBER] is None: res[HEARTBEAT_NUMBER] = res_regex[HEARTBEAT_NUMBER]
        if res[TARGET_NUMBER] is None: res[TARGET_NUMBER] = res_regex[TARGET_NUMBER]
        
        return res
    except: 
        return {HEARTBEAT_NUMBER: None, TARGET_NUMBER: None}

# ═══════════════════════════════════════════════════════════════
# SORGENTE 2 & 3 — API FALLBACK
# ═══════════════════════════════════════════════════════════════

def _count_target_from_results(results: list, target: str) -> Optional[int]:
    if not results: return None
    spins = 0
    for item in results:
        outcome = str(item.get("result") or item.get("outcome") or item.get("slot") or item.get("value") or "").strip()
        if outcome in (target, f"{target}x", f"{target}X"): return spins
        spins += 1
    return spins

def get_stats_from_api() -> Dict[str, Optional[int]]:
    proxy = _next_proxy()
    session = requests.Session()
    if proxy: session.proxies.update(proxy)
    
    endpoints = [(TRACKSINO_API, {"limit": 100, "page": 1}), (CZTIME_HISTORY, {})]
    
    for url, params in endpoints:
        try:
            r = session.get(url, headers=_headers_json(), params=params, timeout=20)
            if r.status_code != 200: continue
            data = r.json()
            
            results = data.get("data") or data.get("results") or data.get("history") if isinstance(data, dict) else data
            if isinstance(results, list):
                c1 = _count_target_from_results(results, HEARTBEAT_NUMBER)
                c_target = _count_target_from_results(results, TARGET_NUMBER)
                if c1 is not None and c_target is not None:
                    return {HEARTBEAT_NUMBER: c1, TARGET_NUMBER: c_target}
        except: continue
    return {HEARTBEAT_NUMBER: None, TARGET_NUMBER: None}

def get_unified_stats() -> Dict[str, Optional[int]]:
    global _sorgente_attiva
    res = get_stats_from_tracksino_html()
    if res[HEARTBEAT_NUMBER] is not None and res[TARGET_NUMBER] is not None:
        _sorgente_attiva = "tracksino_html"
        return res
        
    res_api = get_stats_from_api()
    if res_api[HEARTBEAT_NUMBER] is not None and res_api[TARGET_NUMBER] is not None:
        _sorgente_attiva = "api"
        return res_api
        
    return {HEARTBEAT_NUMBER: None, TARGET_NUMBER: None}

# ═══════════════════════════════════════════════════════════════
# MACCHINA A STATI
# ═══════════════════════════════════════════════════════════════

stato:            str = "FILTRO"
fase_ciclo:       int = 0
cicli_falliti:    int = 0
sessioni_contate: int = 0
_sorgente_attiva: str = "init"

def process_spin(numero: str):
    global stato, fase_ciclo, cicli_falliti, sessioni_contate
    log.info("🎰 Spin elaborato: %s | stato=%s fase=%d falliti=%d", numero, stato, fase_ciclo, cicli_falliti)
    is_target = (numero == TARGET_NUMBER)

    if stato == "FILTRO":
        if fase_ciclo == 0:
            if is_target: fase_ciclo = 1
        elif fase_ciclo == 1:
            if is_target: cicli_falliti, fase_ciclo = 0, 0
            else: fase_ciclo = 2
        elif fase_ciclo == 2:
            if is_target: cicli_falliti, fase_ciclo = 0, 0
            else: fase_ciclo = 3
        elif fase_ciclo == 3:
            if is_target: cicli_falliti, fase_ciclo = 0, 0
            else:
                cicli_falliti += 1
                fase_ciclo = 0
                log.info("✘ Ciclo fallito — totale fallimenti: %d/8", cicli_falliti)
                if cicli_falliti >= 8:
                    stato, sessioni_contate = "SESSIONE", 0
                    invia(f"⚠️ TRIGGER: Raggiunti 8 fallimenti consecutivi. Inizio sessione operativa (Max 9 cicli).")

    elif stato == "SESSIONE":
        if fase_ciclo == 0:
            if is_target:
                invia(f"🎯 Sessione — ciclo {sessioni_contate + 1}/9\nPunta sul prossimo {TARGET_NUMBER}!")
                fase_ciclo = 1
        elif fase_ciclo == 1:
            if is_target: invia("✅ VINTO al 1° colpo!"); stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else: fase_ciclo = 2
        elif fase_ciclo == 2:
            if is_target: invia("✅ VINTO al 2° colpo!"); stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else: fase_ciclo = 3
        elif fase_ciclo == 3:
            if is_target: invia("✅ VINTO al 3° colpo!"); stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else:
                sessioni_contate += 1
                fase_ciclo = 0
                if sessioni_contate >= 9:
                    invia("🛑 Limite raggiunto: 9 cicli esauriti senza vittoria. Sessione chiusa.")
                    stato, cicli_falliti = "FILTRO", 0

# ═══════════════════════════════════════════════════════════════
# FLASK (keepalive + monitoring)
# ═══════════════════════════════════════════════════════════════

flask_app = Flask(__name__)

@flask_app.route("/")
def home(): return "Bot Crazy Time v7.5 Differenziale attivo", 200

@flask_app.route("/ping")
def ping(): return "pong", 200

def run_flask():
    import logging as pylog
    pylog.getLogger("werkzeug").setLevel(pylog.WARNING)
    flask_app.run(host="0.0.0.0", port=PORT, use_reloader=False)

# ═══════════════════════════════════════════════════════════════
# BOT LOOP — LOGICA DIFFERENZIALE
# ═══════════════════════════════════════════════════════════════

def bot_loop():
    prev_1 = None
    prev_target = None
    errori_consecutivi = 0
    retry_delay = float(POLL_MIN)

    log.info("🚀 Bot avviato | proxy: %d | cloudscraper: %s", len(PROXY_POOL), "sì" if CLOUDSCRAPER_AVAILABLE else "no")
    invia(
        "🚀 Bot Crazy Time v7.5 ONLINE!\n"
        "🔕 Modalità silenziosa attiva. Logica DIFFERENZIALE abilitata per eliminare i falsi negativi sui doppi.\n"
        "Riceverai messaggi SOLO al trigger (8 fallimenti) e durante la sessione operativa.\n"
        "📡 Sorgenti: Tracksino HTML → API → cztime.io"
    )

    while True:
        try:
            stats = get_unified_stats()
            curr_1 = _valid_spins(stats[HEARTBEAT_NUMBER])
            curr_target = _valid_spins(stats[TARGET_NUMBER])

            if curr_1 is None or curr_target is None:
                errori_consecutivi += 1
                log.warning("⏳ Lettura fallita (%d/%d)", errori_consecutivi, MAX_CONSEC_ERRORS)
                if errori_consecutivi >= MAX_CONSEC_ERRORS:
                    time.sleep(LONG_WAIT)
                    errori_consecutivi = 0
                    retry_delay = float(POLL_MIN)
                else:
                    retry_delay = min(retry_delay * 1.5, MAX_RETRY_DELAY)
                    time.sleep(retry_delay)
                continue

            errori_consecutivi = 0
            retry_delay = float(POLL_MIN)

            log.info("📊 heartbeat(1)=%d | target(5)=%d [%s]", curr_1, curr_target, _sorgente_attiva)

            if prev_1 is not None and prev_target is not None:
                
                # Caso 1: È uscito il target normale (il contatore si azzera)
                if curr_target < prev_target:
                    process_spin(TARGET_NUMBER)
                    # Gestisce eventuali giri extra persi tra una lettura e l'altra
                    for _ in range(curr_target): process_spin("non_target")
                
                # Caso 2: LOGICA DIFFERENZIALE (Il target resta a 0, ma l'1 sale = DOPPIO TARGET)
                elif curr_target == 0 and prev_target == 0 and curr_1 > prev_1:
                    delta = curr_1 - prev_1
                    log.info("💎 Rilevato DOPPIO/TRIPLO consecutivo (%s)! Differenziale: %d", TARGET_NUMBER, delta)
                    for _ in range(delta): process_spin(TARGET_NUMBER)
                
                # Caso 3: È uscito un numero diverso dal target
                elif curr_target > prev_target:
                    for _ in range(curr_target - prev_target): process_spin("non_target")

            prev_1, prev_target = curr_1, curr_target

        except Exception as e:
            errori_consecutivi += 1
            log.exception("❌ Errore inatteso nel loop: %s", e)

        time.sleep(random.uniform(POLL_MIN, POLL_MAX))

# ═══════════════════════════════════════════════════════════════
# AVVIO
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    _init_proxies()
    _init_sessions()

    Thread(target=run_flask, daemon=True).start()
    Thread(target=keepalive_loop, daemon=True).start()

    log.info("🌐 Server avviato su porta %d", PORT)

    while True:
        try:
            bot_loop()
        except KeyboardInterrupt:
            log.info("⛔ Bot fermato dall'utente")
            break
        except Exception as e:
            log.exception("💥 Crash critico: %s — riavvio tra 30s", e)
            try: invia(f"💥 Crash: {e}\nRiavvio automatico tra 30s...")
            except: pass
            time.sleep(30)
