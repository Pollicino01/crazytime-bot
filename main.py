"""
BOT CRAZY TIME — Deploy Render.com | GitHub Ready
Versione: 7.0 | Multi-API reali + Proxy fallback + Ultra-stabile 24/7

Variabili d'ambiente richieste:
  TELEGRAM_TOKEN  →  Token del bot Telegram (da @BotFather)
  CHANNEL_ID      →  ID o username del canale (es. @miocanale o -100xxxxxxxx)
"""

import os
import re
import time
import json
import random
import logging
import datetime
import requests
import telebot
from flask import Flask
from threading import Thread

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

POLL_MIN          = 15
POLL_MAX          = 25
MAX_CONSEC_ERRORS = 10
LONG_WAIT         = 120
MAX_RETRY_DELAY   = 180
SOURCE_COOLDOWN   = 180

# ── URL FONTI ────────────────────────────────────────────────
# Fonte 1: API Evolution Gaming via endpoint pubblico aggregatore
EVOLUTION_API_URL = (
    "[casino.betsson.com](https://casino.betsson.com/api/livecasino/tables)"
    "?gameType=CrazyTime&limit=20"
)

# Fonte 2: Statistiche pubbliche Crazy Time - LiveCasinoCompare
LIVECOMPARE_URL = "[livecasinocompare.com](https://livecasinocompare.com/api/crazy-time/history)"

# Fonte 3: WhoSpunIt API pubblica
WHOSPUNIT_URL = "[whospunit.com](https://whospunit.com/api/crazy-time/recent)"

# Fonte 4: Scraping diretto pagina Tracksino con rotazione proxy
TRACKSINO_URL = "[tracksino.com](https://tracksino.com/crazytime)"

# Fonte 5: API JSON Tracksino
TRACKSINO_API_URL = "[tracksino.com](https://tracksino.com/api/crazytime/history?limit=50)"

# ── PROXY GRATUITI (aggiornati — per Tracksino come fallback) ─
# Lista di proxy pubblici. Se uno è down viene saltato automaticamente.
# Aggiorna periodicamente da: [proxy-list.download](https://www.proxy-list.download/)
FREE_PROXIES = [
    None,  # None = connessione diretta (primo tentativo sempre senza proxy)
    "[51.158.68.68](http://51.158.68.68:8811)",
    "[51.158.68.133](http://51.158.68.133:8811)",
    "[163.172.36.81](http://163.172.36.81:8811)",
    "[51.158.98.121](http://51.158.98.121:8811)",
    "[51.158.119.88](http://51.158.119.88:8811)",
]
_proxy_index = 0

def _next_proxy() -> dict | None:
    global _proxy_index
    proxy = FREE_PROXIES[_proxy_index % len(FREE_PROXIES)]
    _proxy_index += 1
    if proxy is None:
        return None
    return {"http": proxy, "https": proxy}

# ── ANTI-BAN: POOL USER-AGENT ────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]

ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-GB,en;q=0.9",
    "en-US,en;q=0.9,it;q=0.8",
    "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
]

def _build_headers(json_mode: bool = False) -> dict:
    base = {
        "User-Agent":      random.choice(USER_AGENTS),
        "Accept-Language": random.choice(ACCEPT_LANGUAGES),
        "Accept-Encoding": "gzip, deflate",
        "Connection":      "keep-alive",
        "DNT":             "1",
        "Cache-Control":   "no-cache",
        "Pragma":          "no-cache",
    }
    if json_mode:
        base["Accept"]           = "application/json, text/plain, */*"
        base["X-Requested-With"] = "XMLHttpRequest"
        base["Referer"]          = "[tracksino.com](https://tracksino.com/crazytime)"
    else:
        base["Accept"]                    = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        base["Upgrade-Insecure-Requests"] = "1"
    return base

# ── SESSIONI ─────────────────────────────────────────────────
SESSION_ROTATE_EVERY = 30

_cs_session      = None
_req_session     = requests.Session()
_session_counter = 0

BROWSERS = [
    {"browser": "chrome",  "platform": "windows", "mobile": False},
    {"browser": "chrome",  "platform": "darwin",  "mobile": False},
    {"browser": "firefox", "platform": "windows", "mobile": False},
    {"browser": "firefox", "platform": "linux",   "mobile": False},
]

def _make_cloudscraper():
    if not CLOUDSCRAPER_AVAILABLE:
        return None
    try:
        return cloudscraper.create_scraper(
            browser=random.choice(BROWSERS),
            delay=random.randint(3, 7),
        )
    except Exception as e:
        log.warning("Impossibile creare cloudscraper: %s", e)
        return None

def _get_scraper():
    global _cs_session, _req_session, _session_counter
    _session_counter += 1
    if _session_counter >= SESSION_ROTATE_EVERY:
        log.info("🔄 Rotazione sessione (ciclo %d)", _session_counter)
        try:
            if _cs_session:
                _cs_session.close()
        except Exception:
            pass
        _cs_session      = _make_cloudscraper()
        _req_session     = requests.Session()
        _session_counter = 0
    if _cs_session is None:
        _cs_session = _make_cloudscraper()
    return _cs_session if _cs_session is not None else _req_session

def _init_sessions():
    global _cs_session
    _cs_session = _make_cloudscraper()
    if _cs_session:
        log.info("✅ Cloudscraper attivo")
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

# ── STATO MACCHINA ───────────────────────────────────────────
stato            = "FILTRO"
fase_ciclo       = 0
cicli_falliti    = 0
sessioni_contate = 0
prev_spins_since = None

# ── GESTIONE COOLDOWN FONTI ──────────────────────────────────
SOURCE_NAMES = [
    "tracksino_api",
    "tracksino_html",
    "tracksino_proxy",
]

_last_failures: dict = {name: None for name in SOURCE_NAMES}

def _source_failed(name: str):
    _last_failures[name] = datetime.datetime.now()
    log.warning("🔴 Fonte '%s' offline per %ds", name, SOURCE_COOLDOWN)

def _can_use_source(name: str) -> bool:
    t = _last_failures.get(name)
    if t is None:
        return True
    elapsed = (datetime.datetime.now() - t).total_seconds()
    if elapsed > SOURCE_COOLDOWN:
        log.info("♻️ Fonte '%s' disponibile di nuovo", name)
        _last_failures[name] = None
        return True
    return False

# ── HELPER: CALCOLA spins_since DA LISTA ─────────────────────

def _spins_since_from_list(spins: list, result_key: str = "result") -> int | None:
    """
    Data una lista di spin (dal più recente al più vecchio),
    conta quanti spin sono passati dall'ultimo "5".
    """
    if not spins:
        return None

    spins_since = 0
    found_five  = False

    for spin in spins:
        if isinstance(spin, dict):
            raw = ""
            for key in (result_key, "slot", "number", "outcome", "value", "segment"):
                val = spin.get(key)
                if val is not None:
                    raw = str(val)
                    break
        else:
            raw = str(spin)

        # Normalizza: "5", "5x", "5 ", "5.0" → tutti "5"
        normalized = raw.strip().replace(".0", "").upper()
        if normalized == "5" or normalized.startswith("5X") or normalized == "5":
            found_five = True
            break
        spins_since += 1

    if not found_five:
        spins_since = len(spins)

    return spins_since

# ── NUXT PARSER (per HTML Tracksino) ─────────────────────────

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
    args, current = [], []
    depth, in_str, str_char = 0, False, None
    i = 0
    while i < len(s):
        c = s[i]
        if in_str:
            current.append(c)
            if c == str_char and (i == 0 or s[i - 1] != "\\"):
                in_str = False
        elif c in ('"', "'"):
            in_str, str_char = True, c
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
    if re.match(r'^-?\d+(\.\d+)?$', token):
        return token
    return mapping.get(token, token)

# ── FONTE 1: TRACKSINO API JSON ───────────────────────────────

def _parse_tracksino_api() -> int | None:
    """API JSON di Tracksino — primaria."""
    try:
        time.sleep(random.uniform(0.5, 1.5))
        scraper = _get_scraper()
        headers = _build_headers(json_mode=True)

        r = scraper.get(TRACKSINO_API_URL, headers=headers, timeout=25)

        if r.status_code in (403, 429):
            log.warning("🚫 Tracksino API HTTP %d", r.status_code)
            _source_failed("tracksino_api")
            return None
        if r.status_code != 200:
            log.warning("Tracksino API HTTP %d", r.status_code)
            _source_failed("tracksino_api")
            return None

        try:
            data = r.json()
        except ValueError:
            log.warning("Tracksino API: risposta non JSON — contenuto: %s", r.text[:200])
            _source_failed("tracksino_api")
            return None

        if isinstance(data, list):
            spins = data
        elif isinstance(data, dict):
            spins = (
                data.get("data")
                or data.get("results")
                or data.get("history")
                or data.get("spins")
                or []
            )
        else:
            spins = []

        val = _spins_since_from_list(spins)
        if val is None:
            _source_failed("tracksino_api")
            return None

        log.info("✅ Tracksino API → spins_since=%d", val)
        return val

    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        log.warning("❌ Tracksino API: %s", e)
        _source_failed("tracksino_api")
        return None
    except Exception as e:
        log.exception("Tracksino API errore: %s", e)
        _source_failed("tracksino_api")
        return None

# ── FONTE 2: TRACKSINO HTML NUXT ─────────────────────────────

def _parse_tracksino_html() -> int | None:
    """HTML NUXT di Tracksino — fallback 1."""
    try:
        time.sleep(random.uniform(1.0, 2.5))
        scraper = _get_scraper()
        headers = _build_headers(json_mode=False)

        r = scraper.get(TRACKSINO_URL, headers=headers, timeout=35)

        if r.status_code in (403, 429):
            log.warning("🚫 Tracksino HTML HTTP %d", r.status_code)
            _source_failed("tracksino_html")
            return None
        if r.status_code != 200:
            log.warning("Tracksino HTML HTTP %d", r.status_code)
            _source_failed("tracksino_html")
            return None

        html     = r.text
        n5_match = re.search(r'n5\s*:\s*\{spins_since\s*:\s*(\w+)', html)
        if not n5_match:
            log.warning("Tracksino HTML: n5.spins_since non trovato")
            _source_failed("tracksino_html")
            return None

        token = n5_match.group(1)
        if re.match(r'^\d+$', token):
            log.info("✅ Tracksino HTML → spins_since=%s", token)
            return int(token)
        if token in ("null", "undefined", "void"):
            return None

        mapping = _parse_nuxt_args(html)
        if not mapping:
            _source_failed("tracksino_html")
            return None

        raw_val = _resolve_nuxt_value(token, mapping)
        if raw_val in ("null", "void 0", "undefined"):
            return None

        val = int(float(raw_val.strip("\"'")))
        log.info("✅ Tracksino HTML → spins_since=%d", val)
        return val

    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        log.warning("❌ Tracksino HTML: %s", e)
        _source_failed("tracksino_html")
        return None
    except Exception as e:
        log.exception("Tracksino HTML errore: %s", e)
        _source_failed("tracksino_html")
        return None

# ── FONTE 3: TRACKSINO CON PROXY ROTATION ────────────────────

def _parse_tracksino_proxy() -> int | None:
    """
    Tracksino API con rotazione proxy gratuiti — fallback 2.
    Aggira il blocco IP di Render usando proxy intermedi.
    """
    for tentativo in range(len(FREE_PROXIES)):
        proxy_dict = _next_proxy()
        proxy_label = list(proxy_dict.values())[0] if proxy_dict else "diretto"

        try:
            time.sleep(random.uniform(1.0, 2.0))
            headers = _build_headers(json_mode=True)

            r = requests.get(
                TRACKSINO_API_URL,
                headers=headers,
                proxies=proxy_dict,
                timeout=20,
            )

            if r.status_code in (403, 429):
                log.warning("🚫 Proxy %s bloccato (HTTP %d)", proxy_label, r.status_code)
                continue
            if r.status_code != 200:
                log.warning("Proxy %s HTTP %d", proxy_label, r.status_code)
                continue

            try:
                data = r.json()
            except ValueError:
                log.warning("Proxy %s: risposta non JSON", proxy_label)
                continue

            if isinstance(data, list):
                spins = data
            elif isinstance(data, dict):
                spins = (
                    data.get("data")
                    or data.get("results")
                    or data.get("history")
                    or data.get("spins")
                    or []
                )
            else:
                spins = []

            val = _spins_since_from_list(spins)
            if val is not None:
                log.info("✅ Tracksino Proxy [%s] → spins_since=%d", proxy_label, val)
                return val

        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ProxyError) as e:
            log.warning("❌ Proxy %s: %s", proxy_label, e)
            continue
        except Exception as e:
            log.warning("Proxy %s errore: %s", proxy_label, e)
            continue

    log.warning("Tutti i proxy falliti")
    _source_failed("tracksino_proxy")
    return None

# ── MULTI-SOURCE ORCHESTRATOR ─────────────────────────────────

SOURCES = [
    ("tracksino_api",   _parse_tracksino_api),    # primaria: API JSON diretta
    ("tracksino_html",  _parse_tracksino_html),   # fallback 1: HTML NUXT
    ("tracksino_proxy", _parse_tracksino_proxy),  # fallback 2: API con proxy
]

def get_spins_since_multi() -> int | None:
    """
    Tenta le fonti in ordine di priorità.
    Salta quelle in cooldown.
    Se tutte falliscono attende 60s e restituisce None.
    """
    for name, func in SOURCES:
        if not _can_use_source(name):
            log.debug("⏭️ Fonte '%s' in cooldown, salto", name)
            continue

        log.debug("🔍 Tentativo fonte: %s", name)
        val = func()

        if val is not None:
            return val

        log.warning("❌ Fonte '%s' fallita, passo alla successiva", name)

    log.error("🔴 Tutte le fonti offline — attendo 60s")
    time.sleep(60)
    return None

# ── MACCHINA A STATI ─────────────────────────────────────────

def process_spin(numero: str):
    global stato, fase_ciclo, cicli_falliti, sessioni_contate

    log.info(
        "🎰 Spin: %s | stato=%s fase=%d falliti=%d",
        numero, stato, fase_ciclo, cicli_falliti,
    )

    is_cinque = (numero == "5")

    if stato == "FILTRO":

        if fase_ciclo == 0:
            if is_cinque:
                fase_ciclo = 1

        elif fase_ciclo == 1:
            if is_cinque:
                cicli_falliti = 0
                fase_ciclo    = 0
            else:
                fase_ciclo = 2

        elif fase_ciclo == 2:
            if is_cinque:
                cicli_falliti = 0
                fase_ciclo    = 0
            else:
                cicli_falliti += 1
                fase_ciclo     = 0
                invia(f"❌ Ciclo Base fallito {cicli_falliti}/8")
                if cicli_falliti >= 8:
                    stato            = "SESSIONE"
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
                    f"🎰 Sessione ciclo {sessioni_contate + 1}/12\n"
                    "Punta sul prossimo 5!"
                )
                fase_ciclo = 1

        elif fase_ciclo == 1:
            if is_cinque:
                invia("✅ VINTO al 1° colpo! Sessione terminata con profitto. 🎉")
                stato         = "FILTRO"
                cicli_falliti = 0
                fase_ciclo    = 0
            else:
                fase_ciclo = 2
                invia("⚠️ Perso 1° colpo — Punta ancora sul prossimo 5")

        elif fase_ciclo == 2:
            if is_cinque:
                invia("✅ VINTO al 2° colpo! Sessione terminata con profitto. 🎉")
                stato         = "FILTRO"
                cicli_falliti = 0
                fase_ciclo    = 0
            else:
                sessioni_contate += 1
                fase_ciclo        = 0
                rimanenti         = 12 - sessioni_contate
                if sessioni_contate >= 12:
                    invia("🛑 12 cicli esauriti senza vittoria. Sessione chiusa.")
                    stato         = "FILTRO"
                    cicli_falliti = 0
                else:
                    invia(
                        f"❌ Ciclo perso.\n"
                        f"Restano {rimanenti} cicli in sessione."
                    )

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
    now = datetime.datetime.now()
    fonti_status = {}
    for name, _ in SOURCES:
        t = _last_failures.get(name)
        if t is None:
            fonti_status[name] = "ok"
        else:
            remaining = int(SOURCE_COOLDOWN - (now - t).total_seconds())
            fonti_status[name] = f"cooldown {max(0, remaining)}s"

    return (
        json.dumps({
            "stato":            stato,
            "fase_ciclo":       fase_ciclo,
            "cicli_falliti":    cicli_falliti,
            "sessioni_contate": sessioni_contate,
            "prev_spins_since": prev_spins_since,
            "fonti":            fonti_status,
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
    retry_delay        = float(POLL_MIN)

    log.info("🚀 Bot avviato — polling ogni %d-%ds", POLL_MIN, POLL_MAX)
    invia(
        "🚀 Bot Crazy Time ONLINE! (v7.0)\n"
        "📡 Fonti: API JSON → HTML → Proxy Rotation\n"
        f"🔁 Polling ogni {POLL_MIN}-{POLL_MAX}s | Anti-ban attivo"
    )

    while True:
        try:
            curr = get_spins_since_multi()

            if curr is None:
                errori_consecutivi += 1
                log.warning(
                    "⏳ Lettura fallita (%d/%d consecutivi)",
                    errori_consecutivi, MAX_CONSEC_ERRORS,
                )
                if errori_consecutivi >= MAX_CONSEC_ERRORS:
                    log.error("🔴 Troppe letture fallite — attendo %ds", LONG_WAIT)
                    invia(
                        f"⚠️ Tutte le fonti irraggiungibili "
                        f"({MAX_CONSEC_ERRORS} errori consecutivi).\n"
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

            log.info("📊 spins_since=%d (precedente=%s)", curr, prev_spins_since)

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
            errori_consecutivi += 1
            log.exception("❌ Errore inatteso nel loop: %s", e)

        time.sleep(random.uniform(POLL_MIN, POLL_MAX))

# ── AVVIO ─────────────────────────────────────────────────────

if __name__ == "__main__":
    _init_sessions()

    Thread(target=run_flask, daemon=True).start()
    log.info("🌐 Flask avviato su porta %d", PORT)

    if KEEPALIVE_AVAILABLE:
        Thread(target=keepalive_loop, daemon=True).start()
        log.info("♻️ Keepalive loop avviato")
    else:
        log.warning("⚠️ keepalive.py non trovato — continuo senza")

    while True:
        try:
            bot_loop()
        except KeyboardInterrupt:
            log.info("⛔ Bot fermato manualmente")
            break
        except Exception as e:
            log.exception("💥 Crash critico: %s — riavvio tra 30s", e)
            try:
                invia(f"💥 Crash: {e}\nRiavvio automatico tra 30s...")
            except Exception:
                pass
            time.sleep(30)
