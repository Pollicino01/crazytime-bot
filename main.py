"""
BOT CRAZY TIME — Deploy Render.com | GitHub Ready
Monitora il gioco Crazy Time su CasinoScores (primario) e Tracksino (fallback).
Versione: 5.0 | Proxy rotanti + Cloudflare bypass + Anti-ban + Ultra-stabile 24/7

Variabili d'ambiente richieste:
  TELEGRAM_TOKEN      →  Token del bot Telegram (da @BotFather)
  CHANNEL_ID          →  ID o username del canale (es. @miocanale o -100xxxxxxxx)

Variabili proxy opzionali (almeno una delle due forme):
  PROXY_LIST          →  Lista proxy separata da virgola:
                          "ip:porta:user:pass,ip:porta:user:pass,..."
  PROXY_HOST          →  Host/IP proxy singolo
  PROXY_PORT          →  Porta proxy singolo
  PROXY_USER          →  Username proxy
  PROXY_PASS          →  Password proxy
"""

import os
import re
import time
import json
import random
import logging
import requests
import telebot
from typing import Optional
from flask import Flask
from threading import Thread
from keepalive import keepalive_loop

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

# ── CONFIG ───────────────────────────────────────────────────
TOKEN      = os.environ.get("TELEGRAM_TOKEN", "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
PORT       = int(os.environ.get("PORT", 10000))

if not TOKEN or not CHANNEL_ID:
    raise RuntimeError("Imposta TELEGRAM_TOKEN e CHANNEL_ID nelle variabili d'ambiente")

POLL_MIN          = 12
POLL_MAX          = 18
MAX_CONSEC_ERRORS = 8
LONG_WAIT         = 90
MAX_RETRY_DELAY   = 120

TRACKSINO_URL     = "https://tracksino.com/crazytime"
CASINOSCORES_URL  = "https://casinoscores.com/api/1/evolution-crazy-time/latest-results"
CASINOSCORES_HEADERS_URL = "https://casinoscores.com"

# ── PROXY MANAGER ────────────────────────────────────────────

def _load_proxy_list() -> list:
    """
    Carica i proxy dalle variabili d'ambiente.
    Supporta PROXY_LIST (multi-proxy) o PROXY_HOST/PORT/USER/PASS (singolo).
    Formato PROXY_LIST: "ip:porta:user:pass,ip:porta:user:pass,..."
    """
    proxies = []

    proxy_list_env = os.environ.get("PROXY_LIST", "").strip()
    if proxy_list_env:
        for entry in proxy_list_env.split(","):
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split(":")
            if len(parts) == 4:
                host, port, user, pw = parts
                proxies.append({
                    "http":  f"http://{user}:{pw}@{host}:{port}",
                    "https": f"http://{user}:{pw}@{host}:{port}",
                })
            elif len(parts) == 2:
                host, port = parts
                proxies.append({
                    "http":  f"http://{host}:{port}",
                    "https": f"http://{host}:{port}",
                })
        log.info("📡 Caricati %d proxy da PROXY_LIST", len(proxies))
        return proxies

    host = os.environ.get("PROXY_HOST", "").strip()
    port = os.environ.get("PROXY_PORT", "").strip()
    user = os.environ.get("PROXY_USER", "").strip()
    pw   = os.environ.get("PROXY_PASS", "").strip()

    if host and port:
        if user and pw:
            proxy_url = f"http://{user}:{pw}@{host}:{port}"
        else:
            proxy_url = f"http://{host}:{port}"
        proxies.append({"http": proxy_url, "https": proxy_url})
        log.info("📡 Proxy singolo caricato: %s:%s", host, port)

    return proxies


PROXY_POOL: list = []
_proxy_index: int = 0


def _init_proxies():
    global PROXY_POOL
    PROXY_POOL = _load_proxy_list()
    if PROXY_POOL:
        log.info("✅ Pool proxy attivo — %d proxy disponibili", len(PROXY_POOL))
    else:
        log.info("ℹ️ Nessun proxy configurato — connessione diretta")


def _next_proxy() -> Optional[dict]:
    """Restituisce il prossimo proxy in rotazione round-robin."""
    global _proxy_index
    if not PROXY_POOL:
        return None
    proxy = PROXY_POOL[_proxy_index % len(PROXY_POOL)]
    _proxy_index += 1
    return proxy


# ── ANTI-BAN: POOL USER-AGENT ─────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
]

ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-GB,en;q=0.9",
    "en-US,en;q=0.9,it;q=0.8",
    "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
]


def _build_headers(referer: Optional[str] = None) -> dict:
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


def _build_json_headers(referer: Optional[str] = None) -> dict:
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


# ── SESSIONI ──────────────────────────────────────────────────
SESSION_ROTATE_EVERY = 40

_cs_session: Optional[object] = None
_req_session = requests.Session()
_session_counter = 0

BROWSERS = [
    {"browser": "chrome",  "platform": "windows", "mobile": False},
    {"browser": "chrome",  "platform": "darwin",  "mobile": False},
    {"browser": "firefox", "platform": "windows", "mobile": False},
    {"browser": "firefox", "platform": "linux",   "mobile": False},
]


def _make_cloudscraper(proxy: Optional[dict] = None):
    if not CLOUDSCRAPER_AVAILABLE:
        return None
    try:
        browser = random.choice(BROWSERS)
        scraper = cloudscraper.create_scraper(
            browser=browser,
            delay=random.randint(3, 7),
        )
        if proxy:
            scraper.proxies.update(proxy)
        return scraper
    except Exception as e:
        log.warning("Impossibile creare cloudscraper: %s", e)
        return None


def _get_scraper(proxy: Optional[dict] = None):
    global _cs_session, _req_session, _session_counter
    _session_counter += 1

    if _session_counter >= SESSION_ROTATE_EVERY:
        log.info("🔄 Rotazione sessione anti-ban (ciclo %d)", _session_counter)
        if _cs_session is not None:
            try:
                _cs_session.close()
            except Exception:
                pass
        _cs_session = _make_cloudscraper(proxy)
        _req_session = requests.Session()
        if proxy:
            _req_session.proxies.update(proxy)
        _session_counter = 0

    if _cs_session is None:
        _cs_session = _make_cloudscraper(proxy)

    return _cs_session if _cs_session is not None else _req_session


def _init_sessions():
    global _cs_session
    proxy = _next_proxy()
    _cs_session = _make_cloudscraper(proxy)
    if _cs_session:
        log.info("✅ Cloudscraper attivo — Cloudflare bypass abilitato")
    else:
        log.warning("⚠️ Cloudscraper non disponibile — uso requests standard")


# ── TELEGRAM ─────────────────────────────────────────────────
bot = telebot.TeleBot(TOKEN, parse_mode=None)


def invia(msg: str) -> bool:
    for tentativo in range(3):
        try:
            bot.send_message(CHANNEL_ID, msg)
            log.info("📤 Telegram: %s", msg[:80])
            return True
        except Exception as e:
            log.warning("⚠️ Telegram errore (tentativo %d/3): %s", tentativo + 1, e)
            if tentativo < 2:
                time.sleep(5 * (tentativo + 1))
    log.error("❌ Impossibile inviare messaggio Telegram dopo 3 tentativi")
    return False


# ── SORGENTE 1: CASINOSCORES.COM (API JSON — primaria) ────────

def get_n5_from_casinoscores() -> Optional[int]:
    """
    Legge il contatore spins_since per il 5 da CasinoScores.com.
    Endpoint: /api/1/evolution-crazy-time/latest-results
    Risposta: lista di risultati in ordine cronologico inverso.
    Conta quanti spin consecutivi dall'inizio NON sono stati 5
    (ovvero quanti spin sono trascorsi dall'ultimo 5).
    """
    try:
        time.sleep(random.uniform(0.2, 0.8))
        proxy = _next_proxy()

        session = requests.Session()
        if proxy:
            session.proxies.update(proxy)

        headers = _build_json_headers(referer=CASINOSCORES_HEADERS_URL)
        params  = {"limit": 100}

        r = session.get(
            CASINOSCORES_URL,
            headers=headers,
            params=params,
            timeout=20,
        )

        if r.status_code == 403:
            log.warning("🚫 CasinoScores HTTP 403")
            return None
        if r.status_code == 429:
            log.warning("🚫 CasinoScores HTTP 429 — rate limit")
            time.sleep(30)
            return None
        if r.status_code != 200:
            log.warning("CasinoScores HTTP %d", r.status_code)
            return None

        data = r.json()

        # La risposta può essere {"results": [...]} oppure direttamente [...]
        if isinstance(data, dict):
            results = data.get("results", data.get("data", []))
        elif isinstance(data, list):
            results = data
        else:
            log.warning("CasinoScores: formato risposta sconosciuto")
            return None

        if not results:
            log.warning("CasinoScores: nessun risultato ricevuto")
            return None

        # Conta quanti spin consecutivi dall'inizio non sono stati 5
        spins_since = 0
        for item in results:
            # Il campo del risultato può chiamarsi "result", "outcome", "slot", ecc.
            outcome = (
                item.get("result")
                or item.get("outcome")
                or item.get("slot")
                or item.get("value")
                or ""
            )
            outcome_str = str(outcome).strip()

            # Normalizza: "5" è il 5x, può apparire anche come "5x" o 5 (int)
            if outcome_str in ("5", "5x", "5X"):
                break
            spins_since += 1

        log.debug("CasinoScores spins_since 5 = %d", spins_since)
        return spins_since

    except requests.exceptions.ConnectionError:
        log.warning("❌ Errore connessione a CasinoScores")
        return None
    except requests.exceptions.Timeout:
        log.warning("⏱️ Timeout connessione a CasinoScores")
        return None
    except (ValueError, KeyError) as e:
        log.warning("⚠️ Errore parsing CasinoScores: %s", e)
        return None
    except Exception as e:
        log.exception("Errore inatteso CasinoScores: %s", e)
        return None


# ── SORGENTE 2: TRACKSINO.COM (HTML NUXT — fallback) ──────────

def _parse_nuxt_args(html: str) -> dict:
    pm = re.search(r'window\.__NUXT__=\(function\(([^)]+)\)', html)
    if not pm:
        return {}
    params = [p.strip() for p in pm.group(1).split(",") if p.strip()]

    nuxt_pos = html.find("window.__NUXT__=(")
    if nuxt_pos == -1:
        return {}
    body_start = html.find("{", nuxt_pos)
    if body_start == -1:
        return {}

    depth = 0
    body_end = body_start
    for i in range(body_start, min(len(html), body_start + 600_000)):
        c = html[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                body_end = i
                break

    script_close = html.find("</script>", body_end)
    if script_close == -1:
        script_close = body_end + 4000
    args_section = html[body_end:script_close].strip()

    if not args_section.startswith("}("):
        return {}
    inner = args_section[2:]

    for suffix in ("))", ");", ")"):
        if inner.endswith(suffix):
            inner = inner[: -len(suffix)]
            break

    if not inner:
        return {}

    args = _split_args(inner)
    return {params[i]: args[i] for i in range(min(len(params), len(args)))}


def _split_args(s: str) -> list:
    args = []
    current = []
    depth = 0
    in_str = False
    str_char = None
    i = 0
    while i < len(s):
        c = s[i]
        if in_str:
            current.append(c)
            if c == str_char and (i == 0 or s[i - 1] != "\\"):
                in_str = False
        elif c in ('"', "'"):
            in_str = True
            str_char = c
            current.append(c)
        elif c in ("(", "[", "{"):
            depth += 1
            current.append(c)
        elif c in (")", "]", "}"):
            depth -= 1
            current.append(c)
        elif c == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
            i += 1
            continue
        else:
            current.append(c)
        i += 1
    if current:
        args.append("".join(current).strip())
    return args


def _resolve_nuxt_value(token: str, mapping: dict) -> str:
    token = token.strip()
    if token == "void 0":
        return "null"
    if re.match(r"^-?\d+(\.\d+)?$", token):
        return token
    return mapping.get(token, token)


def get_n5_from_tracksino() -> Optional[int]:
    """
    Legge n5.spins_since dalla pagina Tracksino (parser NUXT).
    Fallback se CasinoScores non risponde.
    """
    try:
        time.sleep(random.uniform(0.3, 1.2))
        proxy = _next_proxy()
        scraper = _get_scraper(proxy)
        headers = _build_headers()
        r = scraper.get(TRACKSINO_URL, headers=headers, timeout=30)

        if r.status_code == 403:
            log.warning("🚫 Tracksino HTTP 403 — pausa 30s")
            time.sleep(30)
            return None
        if r.status_code == 429:
            log.warning("🚫 Tracksino HTTP 429 — pausa 60s")
            time.sleep(60)
            return None
        if r.status_code != 200:
            log.warning("Tracksino HTTP %d", r.status_code)
            return None

        html = r.text

        n5_match = re.search(r"n5\s*:\s*\{spins_since\s*:\s*(\w+)", html)
        if not n5_match:
            log.warning("n5.spins_since non trovato nell'HTML Tracksino")
            return None

        token = n5_match.group(1)

        if re.match(r"^\d+$", token):
            return int(token)

        if token in ("null", "undefined", "void"):
            return None

        mapping = _parse_nuxt_args(html)
        if not mapping:
            log.warning("Impossibile estrarre la mappa NUXT args")
            return None

        raw_val = _resolve_nuxt_value(token, mapping)

        if raw_val in ("null", "void 0", "undefined"):
            return None

        return int(float(raw_val.strip("\"'")))

    except requests.exceptions.ConnectionError:
        log.warning("❌ Errore connessione a Tracksino")
        return None
    except requests.exceptions.Timeout:
        log.warning("⏱️ Timeout connessione a Tracksino")
        return None
    except Exception as e:
        log.exception("Errore scraping Tracksino: %s", e)
        return None


# ── SORGENTE UNIFICATA ────────────────────────────────────────

_use_casinoscores = True   # flag per sapere quale sorgente sta funzionando


def get_n5_spins_since() -> Optional[int]:
    """
    Prova prima CasinoScores (API JSON), poi Tracksino (HTML scraping).
    Logga la sorgente attiva per monitoraggio.
    """
    global _use_casinoscores

    # Prova CasinoScores
    val = get_n5_from_casinoscores()
    if val is not None:
        if not _use_casinoscores:
            log.info("✅ Tornato a CasinoScores dopo fallback")
            _use_casinoscores = True
        return val

    # Fallback a Tracksino
    log.info("⚠️ CasinoScores non disponibile — fallback su Tracksino")
    _use_casinoscores = False
    return get_n5_from_tracksino()


# ── STATO MACCHINA ────────────────────────────────────────────
stato: str = "FILTRO"
fase_ciclo: int = 0
cicli_falliti: int = 0
sessioni_contate: int = 0
prev_spins_since: Optional[int] = None


def process_spin(numero: str):
    global stato, fase_ciclo, cicli_falliti, sessioni_contate

    log.info(
        "🎰 Spin: %s | stato=%s fase=%d falliti=%d",
        numero, stato, fase_ciclo, cicli_falliti,
    )

    is_cinque = numero == "5"

    if stato == "FILTRO":
        if fase_ciclo == 0:
            if is_cinque:
                fase_ciclo = 1

        elif fase_ciclo == 1:
            if is_cinque:
                cicli_falliti = 0
                fase_ciclo = 0
            else:
                fase_ciclo = 2

        elif fase_ciclo == 2:
            if is_cinque:
                cicli_falliti = 0
                fase_ciclo = 0
            else:
                cicli_falliti += 1
                fase_ciclo = 0
                invia(f"❌ Ciclo Base fallito {cicli_falliti}/8")
                if cicli_falliti >= 8:
                    stato = "SESSIONE"
                    sessioni_contate = 0
                    invia(
                        "⚠️ TRIGGER ATTIVATO!\n"
                        "Inizia SESSIONE — 12 cicli disponibili.\n"
                        "Attendi il prossimo 5 per iniziare a puntare."
                    )

    elif stato == "SESSIONE":
        if fase_ciclo == 0:
            if is_cinque:
                invia(
                    f"🎰 Sessione ciclo {sessioni_contate + 1}/12 — "
                    f"Punta sul prossimo 5!"
                )
                fase_ciclo = 1

        elif fase_ciclo == 1:
            if is_cinque:
                invia("✅ VINTO al 1° colpo! Sessione terminata con profitto. 🎉")
                stato = "FILTRO"
                cicli_falliti = 0
                fase_ciclo = 0
            else:
                fase_ciclo = 2
                invia("⚠️ Perso 1° colpo — Punta ancora sul prossimo 5")

        elif fase_ciclo == 2:
            if is_cinque:
                invia("✅ VINTO al 2° colpo! Sessione terminata con profitto. 🎉")
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


# ── FLASK KEEPALIVE ───────────────────────────────────────────
flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Bot Crazy Time attivo", 200


@flask_app.route("/ping")
def ping():
    return "pong", 200


@flask_app.route("/healthz")
def healthz():
    return (
        json.dumps({"status": "ok"}),
        200,
        {"Content-Type": "application/json"},
    )


@flask_app.route("/status")
def status_route():
    return (
        json.dumps({
            "stato": stato,
            "fase_ciclo": fase_ciclo,
            "cicli_falliti": cicli_falliti,
            "sessioni_contate": sessioni_contate,
            "prev_spins_since": prev_spins_since,
            "sorgente": "casinoscores" if _use_casinoscores else "tracksino",
            "proxy_count": len(PROXY_POOL),
        }),
        200,
        {"Content-Type": "application/json"},
    )


def run_flask():
    import logging as pylog
    pylog.getLogger("werkzeug").setLevel(pylog.WARNING)
    flask_app.run(host="0.0.0.0", port=PORT, use_reloader=False)


# ── BOT LOOP ULTRA-STABILE ────────────────────────────────────

def bot_loop():
    global prev_spins_since
    errori_consecutivi = 0
    retry_delay = float(POLL_MIN)

    log.info(
        "🚀 Bot Crazy Time avviato — polling ogni %d-%ds | proxy: %d",
        POLL_MIN, POLL_MAX, len(PROXY_POOL),
    )
    invia(
        "🚀 Bot Crazy Time ONLINE!\n"
        "📡 Sorgente primaria: CasinoScores.com\n"
        "🔁 Fallback: Tracksino.com\n"
        f"🔐 Proxy attivi: {len(PROXY_POOL)}\n"
        f"⏱️ Polling ogni {POLL_MIN}-{POLL_MAX}s | Anti-ban attivo"
    )

    while True:
        try:
            curr = get_n5_spins_since()

            if curr is None:
                errori_consecutivi += 1
                log.warning(
                    "⏳ Lettura fallita (%d/%d consecutivi)",
                    errori_consecutivi,
                    MAX_CONSEC_ERRORS,
                )
                if errori_consecutivi >= MAX_CONSEC_ERRORS:
                    log.error("🔴 Troppe letture fallite — attendo %ds", LONG_WAIT)
                    invia(
                        f"⚠️ Problema connessione ({MAX_CONSEC_ERRORS} errori).\n"
                        f"Riprovo tra {LONG_WAIT}s."
                    )
                    time.sleep(LONG_WAIT)
                    errori_consecutivi = 0
                    retry_delay = float(POLL_MIN)
                else:
                    retry_delay = min(retry_delay * 1.5, MAX_RETRY_DELAY)
                    time.sleep(retry_delay)
                continue

            errori_consecutivi = 0
            retry_delay = float(POLL_MIN)

            log.info(
                "📊 spins_since_5 = %d (precedente: %s)",
                curr, prev_spins_since,
            )

            if prev_spins_since is not None and curr != prev_spins_since:
                if curr < prev_spins_since:
                    # Il 5 è uscito: counter si è azzerato/ridotto
                    process_spin("5")
                    for _ in range(curr):
                        process_spin("non5")
                else:
                    # Spin non-5
                    for _ in range(curr - prev_spins_since):
                        process_spin("non5")

            prev_spins_since = curr

        except Exception as e:
            errori_consecutivi += 1
            log.exception("❌ Errore inatteso nel loop: %s", e)

        time.sleep(random.uniform(POLL_MIN, POLL_MAX))


# ── AVVIO ─────────────────────────────────────────────────────
if __name__ == "__main__":
    _init_proxies()
    _init_sessions()
    Thread(target=run_flask, daemon=True).start()
    log.info("🌐 Flask keepalive avviato su porta %d", PORT)
    Thread(target=keepalive_loop, daemon=True).start()

    while True:
        try:
            bot_loop()
        except KeyboardInterrupt:
            log.info("⛔ Bot fermato")
            break
        except Exception as e:
            log.exception("💥 Crash critico: %s — riavvio tra 30s", e)
            try:
                invia(f"💥 Crash: {e}\nRiavvio automatico tra 30s...")
            except Exception:
                pass
            time.sleep(30)
