"""
BOT CRAZY TIME v7.0 — Deploy Render.com
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
from typing import Optional, List
from flask import Flask
from threading import Thread
from keepalive import keepalive_loop

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
    """
    Carica i proxy.
    Priorità: variabile d'ambiente PROXY_LIST > lista hardcoded.
    """
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
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
]

ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-GB,en;q=0.9,en;q=0.8",
    "en-US,en;q=0.9,it;q=0.8",
]


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
    if referer:
        h["Referer"] = referer
    return h


def _headers_json(referer: Optional[str] = None) -> dict:
    h = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": random.choice(ACCEPT_LANGUAGES),
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
        "DNT": "1",
    }
    if referer:
        h["Referer"] = referer
    return h


# ── SESSIONI CLOUDSCRAPER ─────────────────────────────────────
SESSION_ROTATE_EVERY = 35
_cs_session          = None
_req_session         = requests.Session()
_session_counter     = 0

BROWSERS = [
    {"browser": "chrome",  "platform": "windows", "mobile": False},
    {"browser": "chrome",  "platform": "darwin",  "mobile": False},
    {"browser": "firefox", "platform": "windows", "mobile": False},
    {"browser": "firefox", "platform": "linux",   "mobile": False},
]


def _new_cloudscraper(proxy: Optional[dict] = None):
    if not CLOUDSCRAPER_AVAILABLE:
        return None
    try:
        s = cloudscraper.create_scraper(
            browser=random.choice(BROWSERS),
            delay=random.randint(3, 8),
        )
        if proxy:
            s.proxies.update(proxy)
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
            if _cs_session:
                _cs_session.close()
        except Exception:
            pass
        _cs_session      = _new_cloudscraper(proxy)
        _req_session     = requests.Session()
        if proxy:
            _req_session.proxies.update(proxy)
        _session_counter = 0

    if _cs_session is None:
        _cs_session = _new_cloudscraper(proxy)

    return _cs_session if _cs_session else _req_session


def _init_sessions():
    global _cs_session
    _cs_session = _new_cloudscraper(_next_proxy())
    if _cs_session:
        log.info("✅ Cloudscraper attivo — bypass Cloudflare abilitato")
    else:
        log.warning("⚠️ Cloudscraper non disponibile — uso requests standard")


# ── TELEGRAM ──────────────────────────────────────────────────
bot = telebot.TeleBot(TOKEN, parse_mode=None)


def invia(msg: str) -> bool:
    for tentativo in range(3):
        try:
            bot.send_message(CHANNEL_ID, msg)
            log.info("📤 Telegram OK: %s", msg[:80])
            return True
        except Exception as e:
            log.warning("⚠️ Telegram errore (tentativo %d/3): %s", tentativo + 1, e)
            if tentativo < 2:
                time.sleep(5 * (tentativo + 1))
    log.error("❌ Impossibile inviare messaggio Telegram dopo 3 tentativi")
    return False


# ── VALIDAZIONE VALORE ────────────────────────────────────────

def _valid_spins(val: Optional[int]) -> Optional[int]:
    """Scarta valori non validi (None, negativi)."""
    if val is None or val < 0:
        return None
    return val


# ═══════════════════════════════════════════════════════════════
# SORGENTE 1 — TRACKSINO HTML (Nuxt 2 + Nuxt 3 + regex dirette)
# ═══════════════════════════════════════════════════════════════

def _extract_from_nuxt2_iife(html: str) -> Optional[int]:
    """
    Parser per Nuxt 2: window.__NUXT__=(function(a,b,...){...})(val1,val2,...)
    Trova n5.spins_since e risolve il token attraverso la mappa degli argomenti.
    """
    m = re.search(r'\bn5\s*:\s*\{[^}]*spins_since\s*:\s*(-?\w+)', html)
    if not m:
        return None
    token = m.group(1).strip()

    if re.match(r'^-?\d+$', token):
        return int(token)
    if token in ("null", "undefined", "void"):
        return None

    pm = re.search(r'window\.__NUXT__=\(function\(([^)]{5,})\)', html)
    if not pm:
        return None
    params = [p.strip() for p in pm.group(1).split(",") if p.strip()]

    nuxt_pos   = html.find("window.__NUXT__=(")
    body_start = html.find("{", nuxt_pos)
    if nuxt_pos == -1 or body_start == -1:
        return None

    depth = 0
    body_end = body_start
    for i in range(body_start, min(len(html), body_start + 700_000)):
        c = html[i]
        if   c == "{": depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                body_end = i
                break

    sc = html.find("</script>", body_end)
    if sc == -1:
        sc = body_end + 5000
    seg = html[body_end:sc].strip()

    if not seg.startswith("}("):
        return None
    inner = seg[2:]
    for suf in ("))", ");", ")"):
        if inner.endswith(suf):
            inner = inner[:-len(suf)]
            break

    args = _js_split(inner)
    mapping = {params[i]: args[i] for i in range(min(len(params), len(args)))}

    raw = mapping.get(token, token).strip()
    if raw in ("null", "undefined", "void 0"):
        return None
    try:
        return int(float(raw.strip("\"'")))
    except (ValueError, TypeError):
        return None


def _js_split(s: str) -> list:
    """Split di argomenti JS rispettando stringhe e parentesi."""
    args, cur, depth, in_str, sc = [], [], 0, False, None
    i = 0
    while i < len(s):
        c = s[i]
        if in_str:
            cur.append(c)
            if c == sc and (i == 0 or s[i-1] != "\\"):
                in_str = False
        elif c in ('"', "'", "`"):
            in_str, sc = True, c
            cur.append(c)
        elif c in ("(", "[", "{"):
            depth += 1; cur.append(c)
        elif c in (")", "]", "}"):
            depth -= 1; cur.append(c)
        elif c == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []; i += 1; continue
        else:
            cur.append(c)
        i += 1
    if cur:
        args.append("".join(cur).strip())
    return args


def _extract_from_nuxt3_data(html: str) -> Optional[int]:
    """
    Parser per Nuxt 3: <script id="__NUXT_DATA__" type="application/json">[...]</script>
    Cerca il valore di spins_since per il numero 5 nell'array piatto.
    """
    m = re.search(
        r'<script[^>]+id=["\']__NUXT_DATA__["\'][^>]*>([\s\S]*?)</script>',
        html, re.IGNORECASE
    )
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except (ValueError, TypeError):
        return None

    if not isinstance(data, list):
        return None

    for i, v in enumerate(data):
        if v != "spins_since":
            continue
        if i + 1 < len(data):
            candidate = data[i + 1]
            if isinstance(candidate, int) and candidate >= 0:
                ctx = data[max(0, i-20):i]
                if "5" in ctx or 5 in ctx:
                    return candidate

    for i, v in enumerate(data):
        if v == "spins_since" and i + 1 < len(data):
            nxt = data[i + 1]
            if isinstance(nxt, int) and 0 <= nxt < 10000:
                return nxt

    return None


def _extract_direct_patterns(html: str) -> Optional[int]:
    """
    Pattern diretti che funzionano indipendentemente dal formato Nuxt.
    Cerca spins_since vicino a "5" in qualsiasi formato JSON/JS.
    """
    m = re.search(r'"5"\s*:\s*\{[^}]{0,200}?"spins_since"\s*:\s*(\d+)', html)
    if m:
        return int(m.group(1))

    m = re.search(r'n5\s*:\s*\{[^}]{0,300}?spins_since\s*:\s*(\d+)', html)
    if m:
        val = int(m.group(1))
        return val if val >= 0 else None

    m = re.search(
        r'\{[^}]{0,500}(?:"slot"\s*:\s*"5"|"result"\s*:\s*"5")[^}]{0,500}'
        r'"spins_since"\s*:\s*(\d+)',
        html, re.DOTALL
    )
    if m:
        return int(m.group(1))

    m = re.search(r'["\']5["\']\s*[,:].*?spins_since["\']?\s*:\s*(\d+)', html, re.DOTALL)
    if m:
        val = int(m.group(1))
        if val < 10000:
            return val

    return None


def get_n5_from_tracksino_html() -> Optional[int]:
    """
    Scarica la pagina Tracksino con cloudscraper (bypass Cloudflare) e proxy.
    Prova 3 parser in sequenza: Nuxt 2 IIFE → Nuxt 3 __NUXT_DATA__ → regex dirette.
    """
    try:
        time.sleep(random.uniform(0.4, 1.2))
        proxy   = _next_proxy()
        scraper = _get_scraper(proxy)
        r       = scraper.get(
            TRACKSINO_PAGE,
            headers=_headers_html(),
            timeout=30,
        )

        if r.status_code == 403:
            log.warning("🚫 Tracksino HTML 403 — pausa 30s")
            time.sleep(30)
            return None
        if r.status_code == 429:
            log.warning("🚫 Tracksino HTML 429 — pausa 60s")
            time.sleep(60)
            return None
        if r.status_code != 200:
            log.warning("Tracksino HTML HTTP %d", r.status_code)
            return None

        html = r.text
        log.debug("Tracksino HTML: %d bytes ricevuti", len(html))

        val = _extract_from_nuxt2_iife(html)
        if val is not None and val >= 0:
            log.info("📊 Tracksino NUXT2 spins_since_5 = %d", val)
            return val

        val = _extract_from_nuxt3_data(html)
        if val is not None and val >= 0:
            log.info("📊 Tracksino NUXT3 spins_since_5 = %d", val)
            return val

        val = _extract_direct_patterns(html)
        if val is not None and val >= 0:
            log.info("📊 Tracksino REGEX spins_since_5 = %d", val)
            return val

        log.warning("⚠️ Tracksino HTML: nessun pattern ha trovato il valore")
        return None

    except requests.exceptions.ConnectionError:
        log.warning("❌ Errore connessione Tracksino HTML")
        return None
    except requests.exceptions.Timeout:
        log.warning("⏱️ Timeout Tracksino HTML")
        return None
    except Exception as e:
        log.exception("Errore inatteso Tracksino HTML: %s", e)
        return None


# ═══════════════════════════════════════════════════════════════
# SORGENTE 2 — TRACKSINO JSON API
# ═══════════════════════════════════════════════════════════════

def _count_5_from_results(results: list) -> Optional[int]:
    """
    Data una lista di spin in ordine cronologico inverso (più recente prima),
    conta quanti spin consecutivi NON sono stati un 5
    prima del primo 5 incontrato.
    """
    if not results:
        return None
    spins = 0
    for item in results:
        outcome = str(
            item.get("result") or item.get("outcome") or item.get("slot")
            or item.get("spin_result") or item.get("value") or ""
        ).strip()
        if outcome in ("5", "5x", "5X"):
            return spins
        spins += 1
    return spins


def get_n5_from_tracksino_api() -> Optional[int]:
    """
    Prova due endpoint API di Tracksino (storia + stats).
    """
    proxy   = _next_proxy()
    session = requests.Session()
    if proxy:
        session.proxies.update(proxy)

    endpoints = [
        (TRACKSINO_API,   {"limit": 100, "page": 1}),
        (TRACKSINO_STATS, {}),
    ]

    for url, params in endpoints:
        try:
            time.sleep(random.uniform(0.2, 0.6))
            r = session.get(
                url,
                headers=_headers_json(referer=TRACKSINO_PAGE),
                params=params,
                timeout=20,
            )
            if r.status_code != 200:
                log.debug("Tracksino API %s → HTTP %d", url, r.status_code)
                continue

            data = r.json()

            if isinstance(data, dict):
                n5 = data.get("n5") or data.get("5") or {}
                if isinstance(n5, dict):
                    val = n5.get("spins_since")
                    if isinstance(val, int) and val >= 0:
                        log.info("📊 Tracksino API (stats) spins_since_5 = %d", val)
                        return val

                results = data.get("data") or data.get("results") or data.get("history")
                if isinstance(results, list):
                    val = _count_5_from_results(results)
                    if val is not None:
                        log.info("📊 Tracksino API spins_since_5 = %d", val)
                        return val

            elif isinstance(data, list):
                val = _count_5_from_results(data)
                if val is not None:
                    log.info("📊 Tracksino API spins_since_5 = %d", val)
                    return val

        except Exception as e:
            log.debug("Tracksino API %s errore: %s", url, e)
            continue

    return None


# ═══════════════════════════════════════════════════════════════
# SORGENTE 3 — CZTIME.IO (tracker Evolution indipendente)
# ═══════════════════════════════════════════════════════════════

def get_n5_from_cztime() -> Optional[int]:
    """
    cztime.io è un tracker pubblico di Evolution Crazy Time.
    Prova i suoi endpoint API.
    """
    proxy   = _next_proxy()
    session = requests.Session()
    if proxy:
        session.proxies.update(proxy)

    endpoints = [CZTIME_HISTORY, CZTIME_RESULTS]

    for url in endpoints:
        try:
            time.sleep(random.uniform(0.2, 0.5))
            r = session.get(
                url,
                headers=_headers_json(referer="https://cztime.io/"),
                timeout=15,
            )
            if r.status_code != 200:
                log.debug("cztime %s → HTTP %d", url, r.status_code)
                continue

            data = r.json()

            if isinstance(data, dict):
                results = (
                    data.get("results") or data.get("data")
                    or data.get("history") or data.get("items")
                )
                if isinstance(results, list):
                    val = _count_5_from_results(results)
                    if val is not None:
                        log.info("📊 cztime.io spins_since_5 = %d", val)
                        return val

                n5 = data.get("n5") or data.get("five") or data.get("5") or {}
                if isinstance(n5, dict):
                    val = n5.get("spins_since") or n5.get("since") or n5.get("count")
                    if isinstance(val, int) and val >= 0:
                        log.info("📊 cztime.io (stats) spins_since_5 = %d", val)
                        return val

            elif isinstance(data, list):
                val = _count_5_from_results(data)
                if val is not None:
                    log.info("📊 cztime.io spins_since_5 = %d", val)
                    return val

        except Exception as e:
            log.debug("cztime %s errore: %s", url, e)
            continue

    return None


# ═══════════════════════════════════════════════════════════════
# SORGENTE UNIFICATA — cascata automatica
# ═══════════════════════════════════════════════════════════════

_sorgente_attiva = "tracksino_html"


def get_n5_spins_since() -> Optional[int]:
    """
    Ordine di priorità:
      1. Tracksino HTML  (NUXT2 + NUXT3 + regex — più completo)
      2. Tracksino API   (JSON endpoint interno)
      3. cztime.io       (tracker Evolution indipendente)
    """
    global _sorgente_attiva

    val = _valid_spins(get_n5_from_tracksino_html())
    if val is not None:
        if _sorgente_attiva != "tracksino_html":
            log.info("✅ Tornato a sorgente: tracksino_html")
        _sorgente_attiva = "tracksino_html"
        return val

    log.info("⚠️ Tracksino HTML fallita — provo API interna")
    val = _valid_spins(get_n5_from_tracksino_api())
    if val is not None:
        if _sorgente_attiva != "tracksino_api":
            log.info("✅ Fonte attiva: tracksino_api")
        _sorgente_attiva = "tracksino_api"
        return val

    log.info("⚠️ Tracksino API fallita — provo cztime.io")
    val = _valid_spins(get_n5_from_cztime())
    if val is not None:
        if _sorgente_attiva != "cztime":
            log.info("✅ Fonte attiva: cztime.io")
        _sorgente_attiva = "cztime"
        return val

    log.error("❌ Tutte le sorgenti hanno fallito in questo ciclo")
    return None


# ═══════════════════════════════════════════════════════════════
# SORGENTE N1 — spins_since_1 (contatore differenziale)
# ═══════════════════════════════════════════════════════════════

def _extract_n1_from_html(html: str) -> Optional[int]:
    """
    Estrae spins_since per il numero 1 dalla pagina HTML di Tracksino.
    Usa gli stessi pattern di n5 ma adattati al numero 1.
    """
    # Pattern A: "1":{"spins_since":NUMERO}
    m = re.search(r'"1"\s*:\s*\{[^}]{0,200}?"spins_since"\s*:\s*(\d+)', html)
    if m:
        return int(m.group(1))

    # Pattern B: n1:{spins_since:NUMERO} (Nuxt 2 IIFE)
    m = re.search(r'\bn1\s*:\s*\{[^}]{0,300}?spins_since\s*:\s*(\d+)', html)
    if m:
        val = int(m.group(1))
        return val if val >= 0 else None

    # Pattern C: slot/result "1" seguito da spins_since
    m = re.search(
        r'\{[^}]{0,500}(?:"slot"\s*:\s*"1"|"result"\s*:\s*"1")[^}]{0,500}'
        r'"spins_since"\s*:\s*(\d+)',
        html, re.DOTALL
    )
    if m:
        return int(m.group(1))

    return None


def get_n1_from_tracksino_html() -> Optional[int]:
    """Scarica la pagina Tracksino ed estrae spins_since per il numero 1."""
    try:
        time.sleep(random.uniform(0.2, 0.6))
        proxy   = _next_proxy()
        scraper = _get_scraper(proxy)
        r       = scraper.get(
            TRACKSINO_PAGE,
            headers=_headers_html(),
            timeout=30,
        )
        if r.status_code != 200:
            log.debug("Tracksino HTML n1 HTTP %d", r.status_code)
            return None
        val = _extract_n1_from_html(r.text)
        if val is not None and val >= 0:
            log.info("📊 Tracksino HTML spins_since_1 = %d", val)
        return val
    except Exception as e:
        log.debug("Errore Tracksino HTML n1: %s", e)
        return None


def get_n1_from_tracksino_api() -> Optional[int]:
    """
    Legge spins_since per il numero 1 dall'endpoint stats di Tracksino.
    Lo stesso endpoint già usato per n5 restituisce tutti i numeri.
    """
    proxy   = _next_proxy()
    session = requests.Session()
    if proxy:
        session.proxies.update(proxy)

    endpoints = [
        (TRACKSINO_API,   {"limit": 100, "page": 1}),
        (TRACKSINO_STATS, {}),
    ]

    for url, params in endpoints:
        try:
            time.sleep(random.uniform(0.1, 0.4))
            r = session.get(
                url,
                headers=_headers_json(referer=TRACKSINO_PAGE),
                params=params,
                timeout=20,
            )
            if r.status_code != 200:
                continue
            data = r.json()

            if isinstance(data, dict):
                # Struttura stats: {"n1": {"spins_since": X}}
                n1 = data.get("n1") or data.get("1") or {}
                if isinstance(n1, dict):
                    val = n1.get("spins_since")
                    if isinstance(val, int) and val >= 0:
                        log.info("📊 Tracksino API (stats) spins_since_1 = %d", val)
                        return val

                # Struttura lista: conta spin dall'ultimo 1
                results = data.get("data") or data.get("results") or data.get("history")
                if isinstance(results, list):
                    spins = 0
                    for item in results:
                        outcome = str(
                            item.get("result") or item.get("outcome") or item.get("slot")
                            or item.get("spin_result") or item.get("value") or ""
                        ).strip()
                        if outcome in ("1", "1x", "1X"):
                            log.info("📊 Tracksino API spins_since_1 = %d", spins)
                            return spins
                        spins += 1

            elif isinstance(data, list):
                spins = 0
                for item in data:
                    outcome = str(
                        item.get("result") or item.get("outcome") or item.get("slot")
                        or item.get("spin_result") or item.get("value") or ""
                    ).strip()
                    if outcome in ("1", "1x", "1X"):
                        log.info("📊 Tracksino API spins_since_1 = %d", spins)
                        return spins
                    spins += 1

        except Exception as e:
            log.debug("Tracksino API n1 %s errore: %s", url, e)
            continue

    return None


def get_n1_spins_since() -> Optional[int]:
    """
    Cascata per spins_since_1:
      1. Tracksino API (stats endpoint — più diretto)
      2. Tracksino HTML (fallback)
    """
    val = _valid_spins(get_n1_from_tracksino_api())
    if val is not None:
        return val

    val = _valid_spins(get_n1_from_tracksino_html())
    return val


# ═══════════════════════════════════════════════════════════════
# MACCHINA A STATI
# ═══════════════════════════════════════════════════════════════

stato:              str          = "FILTRO"
fase_ciclo:         int          = 0
cicli_falliti:      int          = 0
sessioni_contate:   int          = 0
prev_spins_since_5: Optional[int] = None
prev_spins_since_1: Optional[int] = None

# ── LOGICA BOT SILENZIOSO ──────────────────────────────────────
#
# FILTRO — conta fallimenti internamente, nessun messaggio singolo:
#   fase 0 : attende il primo 5  → fase 1
#   fase 1 : vede 5 → reset+silenzio (vittoria 1° colpo)
#             vede X → fase 2
#   fase 2 : vede 5 → reset+silenzio (vittoria 2° colpo)
#             vede X → fase 3
#   fase 3 : vede 5 → reset+silenzio (vittoria 3° colpo)
#             vede X → ciclo fallito (+1 fallimento, torna fase 0)
#                       se fallimenti < 8 → silenzio
#                       se fallimenti = 8 → TRIGGER e passa a SESSIONE
#
# SESSIONE — max 9 cicli, segnala quando puntare e l'esito:
#   fase 0 : attende 5 → avvisa di puntare, fase 1
#   fase 1 : vede 5 → ✅ VINTO (1° colpo), chiude sessione
#             vede X → fase 2
#   fase 2 : vede 5 → ✅ VINTO (2° colpo), chiude sessione
#             vede X → fase 3
#   fase 3 : vede 5 → ✅ VINTO (3° colpo), chiude sessione
#             vede X → ciclo perso, sessioni_contate +1
#                       se >= 9 → 🛑 Limite raggiunto, chiude sessione
#                       else    → attende prossimo 5

def process_spin(numero: str):
    global stato, fase_ciclo, cicli_falliti, sessioni_contate

    log.info(
        "🎰 Spin: %s | stato=%s fase=%d falliti=%d",
        numero, stato, fase_ciclo, cicli_falliti,
    )

    is_cinque = (numero == "5")

    # ── FILTRO (bot silenzioso) ────────────────────────────────
    if stato == "FILTRO":
        if fase_ciclo == 0:
            if is_cinque:
                fase_ciclo = 1

        elif fase_ciclo == 1:
            if is_cinque:
                cicli_falliti = 0
                fase_ciclo    = 0
                log.info("✔ Vittoria 1° colpo (FILTRO) — fallimenti azzerati")
            else:
                fase_ciclo = 2

        elif fase_ciclo == 2:
            if is_cinque:
                cicli_falliti = 0
                fase_ciclo    = 0
                log.info("✔ Vittoria 2° colpo (FILTRO) — fallimenti azzerati")
            else:
                fase_ciclo = 3

        elif fase_ciclo == 3:
            if is_cinque:
                cicli_falliti = 0
                fase_ciclo    = 0
                log.info("✔ Vittoria 3° colpo (FILTRO) — fallimenti azzerati")
            else:
                cicli_falliti += 1
                fase_ciclo     = 0
                log.info("✘ Ciclo fallito — totale fallimenti: %d/8", cicli_falliti)

                if cicli_falliti >= 8:
                    stato            = "SESSIONE"
                    sessioni_contate = 0
                    invia(
                        "⚠️ TRIGGER: Raggiunti 8 fallimenti consecutivi. "
                        "Inizio sessione operativa (Max 9 cicli)."
                    )

    # ── SESSIONE (max 9 cicli, 3 colpi per ciclo) ─────────────
    elif stato == "SESSIONE":
        if fase_ciclo == 0:
            if is_cinque:
                invia(
                    f"🎯 Sessione — ciclo {sessioni_contate + 1}/9\n"
                    f"Punta sul prossimo 5!"
                )
                fase_ciclo = 1

        elif fase_ciclo == 1:
            if is_cinque:
                invia("✅ VINTO al 1° colpo!")
                stato         = "FILTRO"
                cicli_falliti = 0
                fase_ciclo    = 0
            else:
                fase_ciclo = 2

        elif fase_ciclo == 2:
            if is_cinque:
                invia("✅ VINTO al 2° colpo!")
                stato         = "FILTRO"
                cicli_falliti = 0
                fase_ciclo    = 0
            else:
                fase_ciclo = 3

        elif fase_ciclo == 3:
            if is_cinque:
                invia("✅ VINTO al 3° colpo!")
                stato         = "FILTRO"
                cicli_falliti = 0
                fase_ciclo    = 0
            else:
                sessioni_contate += 1
                fase_ciclo        = 0
                if sessioni_contate >= 9:
                    invia("🛑 Limite raggiunto: 9 cicli esauriti senza vittoria. Sessione chiusa.")
                    stato         = "FILTRO"
                    cicli_falliti = 0


# ═══════════════════════════════════════════════════════════════
# FLASK (keepalive + monitoring)
# ═══════════════════════════════════════════════════════════════

flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Bot Crazy Time v6 attivo", 200


@flask_app.route("/ping")
def ping():
    return "pong", 200


@flask_app.route("/healthz")
def healthz():
    return json.dumps({"status": "ok"}), 200, {"Content-Type": "application/json"}


@flask_app.route("/status")
def status_route():
    return (
        json.dumps({
            "stato":             stato,
            "fase_ciclo":        fase_ciclo,
            "cicli_falliti":     cicli_falliti,
            "sessioni_contate":  sessioni_contate,
            "prev_spins_since_5": prev_spins_since_5,
            "prev_spins_since_1": prev_spins_since_1,
            "sorgente":          _sorgente_attiva,
            "proxy_count":       len(PROXY_POOL),
        }),
        200,
        {"Content-Type": "application/json"},
    )


def run_flask():
    import logging as pylog
    pylog.getLogger("werkzeug").setLevel(pylog.WARNING)
    flask_app.run(host="0.0.0.0", port=PORT, use_reloader=False)


# ═══════════════════════════════════════════════════════════════
# BOT LOOP
# ═══════════════════════════════════════════════════════════════

def bot_loop():
    global prev_spins_since_5, prev_spins_since_1
    errori_consecutivi = 0
    retry_delay        = float(POLL_MIN)

    log.info("🚀 Bot avviato | proxy: %d | cloudscraper: %s",
             len(PROXY_POOL), "sì" if CLOUDSCRAPER_AVAILABLE else "no")
    invia(
        "🚀 Bot Crazy Time v7 ONLINE!\n"
        "🔕 Modalità silenziosa attiva.\n"
        "Riceverai messaggi SOLO al trigger (8 fallimenti) e durante la sessione operativa.\n"
        "📡 Sorgenti: Tracksino HTML → API → cztime.io\n"
        f"🔐 Proxy attivi: {len(PROXY_POOL)}\n"
        f"⏱️ Polling ogni {POLL_MIN}-{POLL_MAX}s | Anti-ban attivo\n"
        "🔢 Doppio contatore differenziale (1+5) attivo"
    )

    while True:
        try:
            curr_5 = get_n5_spins_since()
            curr_1 = get_n1_spins_since()

            if curr_5 is None:
                errori_consecutivi += 1
                log.warning("⏳ Lettura fallita (%d/%d)", errori_consecutivi, MAX_CONSEC_ERRORS)
                if errori_consecutivi >= MAX_CONSEC_ERRORS:
                    invia(
                        f"⚠️ {MAX_CONSEC_ERRORS} errori consecutivi.\n"
                        f"Riprovo tra {LONG_WAIT}s."
                    )
                    time.sleep(LONG_WAIT)
                    errori_consecutivi = 0
                    retry_delay        = float(POLL_MIN)
                else:
                    retry_delay = min(retry_delay * 1.5, MAX_RETRY_DELAY)
                    time.sleep(retry_delay)
                continue

            errori_consecutivi = 0
            retry_delay        = float(POLL_MIN)

            log.info("📊 spins_since_5=%d spins_since_1=%s (prec5:%s prec1:%s) [%s]",
                     curr_5, curr_1, prev_spins_since_5, prev_spins_since_1, _sorgente_attiva)

            if prev_spins_since_5 is not None:

                # ── CASO SPECIALE: 5 consecutivo (doppio/triplo) ─────────────
                # curr_5 è ancora 0 (l'ultimo spin era un 5) ma curr_1 è salito
                # → un nuovo spin è avvenuto e l'esito è ancora 5.
                # Senza questo controllo il bot vedrebbe 0==0 e non rileverebbe nulla.
                if (curr_5 == 0
                        and prev_spins_since_5 == 0
                        and curr_1 is not None
                        and prev_spins_since_1 is not None
                        and curr_1 > prev_spins_since_1):
                    delta_1 = curr_1 - prev_spins_since_1
                    # delta_1 spin avvenuti dall'ultimo ciclo:
                    # i primi (delta_1 - 1) erano non-5, l'ultimo era un 5
                    for _ in range(delta_1 - 1):
                        process_spin("non5")
                    process_spin("5")
                    log.info("🎯 5 consecutivo rilevato via Δ contatore_1=%d", delta_1)

                # ── CASO NORMALE: il contatore del 5 è cambiato ──────────────
                elif curr_5 != prev_spins_since_5:
                    if curr_5 < prev_spins_since_5:
                        # Il 5 è uscito: counter si è azzerato/ridotto
                        process_spin("5")
                        for _ in range(curr_5):
                            process_spin("non5")
                    else:
                        for _ in range(curr_5 - prev_spins_since_5):
                            process_spin("non5")

            prev_spins_since_5 = curr_5
            prev_spins_since_1 = curr_1

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

    Thread(target=run_flask,      daemon=True).start()
    Thread(target=keepalive_loop, daemon=True).start()

    log.info("🌐 Flask avviato su porta %d", PORT)

    while True:
        try:
            bot_loop()
        except KeyboardInterrupt:
            log.info("⛔ Bot fermato dall'utente")
            break
        except Exception as e:
            log.exception("💥 Crash critico: %s — riavvio tra 30s", e)
            try:
                invia(f"💥 Crash: {e}\nRiavvio automatico tra 30s...")
            except Exception:
                pass
            time.sleep(30)
