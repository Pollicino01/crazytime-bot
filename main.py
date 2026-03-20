"""
BOT CRAZY TIME â€” Deploy Render.com | GitHub Ready
Monitora il gioco Crazy Time su Tracksino e invia segnali Telegram.
Versione: 4.0 | Cloudflare bypass + Anti-ban + Ultra-stabile 24/7

Variabili d'ambiente richieste:
  TELEGRAM_TOKEN  â†’  Token del bot Telegram (da @BotFather)
  CHANNEL_ID      â†’  ID o username del canale (es. @miocanale o -100xxxxxxxx)
"""

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
from keepalive import keepalive_loop

try:
    import cloudscraper
    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False

# â”€â”€ LOGGING â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("crazy-time-bot")

# â”€â”€ CONFIG â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
TOKEN      = os.environ.get("TELEGRAM_TOKEN", "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
PORT       = int(os.environ.get("PORT", 10000))

if not TOKEN or not CHANNEL_ID:
    raise RuntimeError("Imposta TELEGRAM_TOKEN e CHANNEL_ID nelle variabili d'ambiente")

POLL_MIN          = 12    # secondi minimi tra poll
POLL_MAX          = 18    # secondi massimi tra poll (jitter anti-ban)
MAX_CONSEC_ERRORS = 8     # errori consecutivi prima di pausa lunga
LONG_WAIT         = 90    # pausa lunga dopo troppi errori
MAX_RETRY_DELAY   = 120   # backoff massimo

TRACKSINO_URL = "https://tracksino.com/crazytime"

# â”€â”€ ANTI-BAN: POOL USER-AGENT (solo desktop â€” mobile potrebbe avere HTML diverso) â”€â”€
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

def _build_headers() -> dict:
    """
    Costruisce headers casuali per ogni richiesta (anti-ban).
    NOTA: Non includiamo brotli (br) in Accept-Encoding perchÃ© requests
    non lo decodifica nativamente e potrebbe corrompere l'HTML.
    Non includiamo Sec-Fetch-* perchÃ© possono causare risposte diverse.
    """
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": random.choice(ACCEPT_LANGUAGES),
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
        "DNT": "1",
    }

# â”€â”€ SESSIONI: CLOUDSCRAPER (primario) + REQUESTS (fallback) â”€â”€
SESSION_ROTATE_EVERY = 40  # rinnova la sessione ogni N richieste

_cs_session      = None   # cloudscraper session
_req_session     = requests.Session()
_session_counter = 0

BROWSERS = [
    {"browser": "chrome",  "platform": "windows", "mobile": False},
    {"browser": "chrome",  "platform": "darwin",  "mobile": False},
    {"browser": "firefox", "platform": "windows", "mobile": False},
    {"browser": "firefox", "platform": "linux",   "mobile": False},
]

def _make_cloudscraper():
    """Crea un'istanza cloudscraper con browser fingerprint casuale."""
    if not CLOUDSCRAPER_AVAILABLE:
        return None
    try:
        browser = random.choice(BROWSERS)
        scraper = cloudscraper.create_scraper(
            browser=browser,
            delay=random.randint(3, 7),
        )
        return scraper
    except Exception as e:
        log.warning("Impossibile creare cloudscraper: %s", e)
        return None

def _get_scraper():
    """
    Restituisce il scraper attivo, rinnovandolo periodicamente.
    PrioritÃ : cloudscraper â†’ requests.Session
    """
    global _cs_session, _req_session, _session_counter
    _session_counter += 1

    if _session_counter >= SESSION_ROTATE_EVERY:
        log.info("ðŸ”„ Rotazione sessione (anti-ban, ciclo %d)", _session_counter)
        if _cs_session is not None:
            try:
                _cs_session.close()
            except Exception:
                pass
        _cs_session = _make_cloudscraper()
        _req_session = requests.Session()
        _session_counter = 0

    if _cs_session is None:
        _cs_session = _make_cloudscraper()

    return _cs_session if _cs_session is not None else _req_session

def _init_sessions():
    """Inizializza le sessioni all'avvio."""
    global _cs_session
    _cs_session = _make_cloudscraper()
    if _cs_session:
        log.info("âœ… Cloudscraper attivo â€” Cloudflare bypass abilitato")
    else:
        log.warning("âš ï¸ Cloudscraper non disponibile â€” uso requests standard")

# â”€â”€ TELEGRAM â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
bot = telebot.TeleBot(TOKEN, parse_mode=None)

def invia(msg: str) -> bool:
    """Invia messaggio Telegram con retry automatico."""
    for tentativo in range(3):
        try:
            bot.send_message(CHANNEL_ID, msg)
            log.info("ðŸ“¤ Telegram: %s", msg[:80])
            return True
        except Exception as e:
            log.warning("âš ï¸ Telegram errore (tentativo %d/3): %s", tentativo + 1, e)
            if tentativo < 2:
                time.sleep(5 * (tentativo + 1))
    log.error("âŒ Impossibile inviare messaggio Telegram dopo 3 tentativi")
    return False

# â”€â”€ STATO MACCHINA â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
stato            = "FILTRO"
fase_ciclo       = 0
cicli_falliti    = 0
sessioni_contate = 0
prev_spins_since = None

# â”€â”€ SCRAPING TRACKSINO (NUXT PARSER ROBUSTO) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _parse_nuxt_args(html: str) -> dict:
    """
    Estrae la mappa {param: valore} dall'espressione NUXT IIFE.
    Strategia robusta in 4 step:
      1. Estrai i parametri formali dalla dichiarazione function
      2. Trova la fine del body con conteggio parentesi graffe
      3. Trova la fine del tag <script> per delimitare gli args
      4. Estrai e splitta gli args rispettando le virgolette
    """
    # Step 1: parametri formali da (function(a,b,c,...){
    pm = re.search(r'window\.__NUXT__=\(function\(([^)]+)\)', html)
    if not pm:
        return {}
    params = [p.strip() for p in pm.group(1).split(",") if p.strip()]

    # Step 2: individua la fine del body con bracket counting
    nuxt_pos = html.find("window.__NUXT__=(")
    if nuxt_pos == -1:
        return {}
    body_start = html.find("{", nuxt_pos)
    if body_start == -1:
        return {}

    depth    = 0
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

    # Step 3: la sezione args Ã¨ tra body_end e il prossimo </script>
    script_close = html.find("</script>", body_end)
    if script_close == -1:
        script_close = body_end + 4000
    args_section = html[body_end:script_close]

    # Formato: }(ARG0,ARG1,...,ARGN))
    # Rimuoviamo la `}(` iniziale e il `))` (o `);` o simile) finale
    args_section = args_section.strip()
    if not args_section.startswith("}("):
        return {}
    inner = args_section[2:]  # rimuove '}('

    # Rimuovi il suffisso )) o ); dalla fine
    for suffix in ("))", ");", ")"):
        if inner.endswith(suffix):
            inner = inner[: -len(suffix)]
            break

    if not inner:
        return {}

    # Step 4: split rispettando le virgolette (i valori non hanno parens)
    args = _split_args(inner)
    return {params[i]: args[i] for i in range(min(len(params), len(args)))}


def _split_args(s: str) -> list:
    """
    Divide una stringa di argomenti JavaScript per virgola,
    rispettando stringhe quotate e parentesi.
    """
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
            if c == str_char and (i == 0 or s[i-1] != "\\"):
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
    """Risolve un token NUXT nel valore reale."""
    token = token.strip()
    if token == "void 0":
        return "null"
    if re.match(r'^-?\d+(\.\d+)?$', token):
        return token
    return mapping.get(token, token)


def get_n5_spins_since() -> int | None:
    """
    Legge n5.spins_since dalla pagina Tracksino con:
    - Cloudscraper (bypass Cloudflare JS challenge) come metodo primario
    - requests.Session come fallback
    - Headers casuali (anti-ban)
    - Jitter random nella richiesta
    - Parser NUXT ultra-robusto con bracket counting
    """
    try:
        time.sleep(random.uniform(0.3, 1.2))  # jitter anti-ban

        scraper = _get_scraper()
        headers = _build_headers()
        r       = scraper.get(TRACKSINO_URL, headers=headers, timeout=30)

        if r.status_code == 403:
            log.warning("ðŸš« HTTP 403 â€” possibile ban temporaneo, pausa 30s")
            time.sleep(30)
            return None
        if r.status_code == 429:
            log.warning("ðŸš« HTTP 429 â€” rate limit, pausa 60s")
            time.sleep(60)
            return None
        if r.status_code != 200:
            log.warning("Tracksino HTTP %d", r.status_code)
            return None

        html = r.text

        # Step 1: trova il token di n5.spins_since direttamente nell'HTML
        n5_match = re.search(r'n5\s*:\s*\{spins_since\s*:\s*(\w+)', html)
        if not n5_match:
            log.warning("n5.spins_since non trovato nell'HTML")
            return None

        token = n5_match.group(1)

        # Se Ã¨ giÃ  un numero letterale, restituiscilo direttamente
        if re.match(r'^\d+$', token):
            log.debug("n5.spins_since = %s (letterale)", token)
            return int(token)

        if token in ("null", "undefined", "void"):
            return None

        # Step 2: risolvi il token attraverso la mappa NUXT
        mapping = _parse_nuxt_args(html)
        if not mapping:
            log.warning("Impossibile estrarre la mappa NUXT args")
            return None

        raw_val = _resolve_nuxt_value(token, mapping)
        log.debug("n5.spins_since token=%s â†’ val=%s", token, raw_val)

        if raw_val in ("null", "void 0", "undefined"):
            return None

        return int(float(raw_val.strip("\"'")))

    except requests.exceptions.ConnectionError:
        log.warning("âŒ Errore di connessione a Tracksino")
        return None
    except requests.exceptions.Timeout:
        log.warning("â±ï¸ Timeout connessione a Tracksino (25s)")
        return None
    except Exception as e:
        log.exception("Errore scraping: %s", e)
        return None

# â”€â”€ MACCHINA A STATI â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def process_spin(numero: str):
    global stato, fase_ciclo, cicli_falliti, sessioni_contate

    log.info("ðŸŽ° Spin: %s | stato=%s fase=%d falliti=%d", numero, stato, fase_ciclo, cicli_falliti)

    is_cinque = (numero == "5")

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
                invia(f"âŒ Ciclo Base fallito {cicli_falliti}/8")
                if cicli_falliti >= 8:
                    stato = "SESSIONE"
                    sessioni_contate = 0
                    invia(
                        "âš ï¸ TRIGGER ATTIVATO!\n"
                        "Inizia SESSIONE â€” 12 cicli disponibili.\n"
                        "Attendi il prossimo 5 per iniziare a puntare."
                    )

    elif stato == "SESSIONE":
        if fase_ciclo == 0:
            if is_cinque:
                invia(f"ðŸŽ° Sessione ciclo {sessioni_contate + 1}/12 â€” Punta sul prossimo 5!")
                fase_ciclo = 1

        elif fase_ciclo == 1:
            if is_cinque:
                invia("âœ… VINTO al 1Â° colpo! Sessione terminata con profitto. ðŸŽ‰")
                stato = "FILTRO"
                cicli_falliti = 0
                fase_ciclo = 0
            else:
                fase_ciclo = 2
                invia("âš ï¸ Perso 1Â° colpo â€” Punta ancora sul prossimo 5")

        elif fase_ciclo == 2:
            if is_cinque:
                invia("âœ… VINTO al 2Â° colpo! Sessione terminata con profitto. ðŸŽ‰")
                stato = "FILTRO"
                cicli_falliti = 0
                fase_ciclo = 0
            else:
                sessioni_contate += 1
                fase_ciclo = 0
                rimanenti = 12 - sessioni_contate
                if sessioni_contate >= 12:
                    invia("ðŸ›‘ 12 cicli esauriti senza vittoria. Sessione chiusa.")
                    stato = "FILTRO"
                    cicli_falliti = 0
                else:
                    invia(f"âŒ Ciclo perso. Restano {rimanenti} cicli in sessione.")

# â”€â”€ FLASK KEEPALIVE (richiesto da Render) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot Crazy Time attivo", 200

@flask_app.route("/ping")
def ping():
    return "pong", 200

@flask_app.route("/healthz")
def healthz():
    return json.dumps({"status": "ok"}), 200, {"Content-Type": "application/json"}

@flask_app.route("/status")
def status_route():
    return json.dumps({
        "stato": stato,
        "fase_ciclo": fase_ciclo,
        "cicli_falliti": cicli_falliti,
        "sessioni_contate": sessioni_contate,
        "prev_spins_since": prev_spins_since,
    }), 200, {"Content-Type": "application/json"}

def run_flask():
    import logging as pylog
    pylog.getLogger("werkzeug").setLevel(pylog.WARNING)
    flask_app.run(host="0.0.0.0", port=PORT, use_reloader=False)

# â”€â”€ BOT LOOP ULTRA-STABILE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def bot_loop():
    global prev_spins_since
    errori_consecutivi = 0
    retry_delay        = float(POLL_MIN)

    log.info("ðŸš€ Bot Crazy Time avviato â€” polling ogni %d-%ds", POLL_MIN, POLL_MAX)
    invia(
        "ðŸš€ Bot Crazy Time ONLINE!\n"
        "ðŸ“¡ Monitoraggio n5 attivo via Tracksino.\n"
        f"ðŸ” Polling ogni {POLL_MIN}-{POLL_MAX}s | Anti-ban attivo"
    )

    while True:
        try:
            curr = get_n5_spins_since()

            if curr is None:
                errori_consecutivi += 1
                log.warning(
                    "â³ Lettura fallita (%d/%d consecutivi)",
                    errori_consecutivi,
                    MAX_CONSEC_ERRORS,
                )
                if errori_consecutivi >= MAX_CONSEC_ERRORS:
                    log.error("ðŸ”´ Troppe letture fallite â€” attendo %ds", LONG_WAIT)
                    invia(
                        f"âš ï¸ Problema connessione Tracksino "
                        f"({MAX_CONSEC_ERRORS} errori consecutivi).\n"
                        f"Riprovo tra {LONG_WAIT}s."
                    )
                    time.sleep(LONG_WAIT)
                    errori_consecutivi = 0
                    retry_delay = float(POLL_MIN)
                else:
                    retry_delay = min(retry_delay * 1.5, MAX_RETRY_DELAY)
                    time.sleep(retry_delay)
                continue

            # Lettura OK â€” reset contatori
            errori_consecutivi = 0
            retry_delay        = float(POLL_MIN)

            log.info("ðŸ“Š n5 spins_since = %d (precedente: %s)", curr, prev_spins_since)

            if prev_spins_since is not None and curr != prev_spins_since:
                if curr < prev_spins_since:
                    # Il 5 Ã¨ uscito: counter si Ã¨ azzerato/ridotto
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
            log.exception("âŒ Errore inatteso nel loop: %s", e)

        # Jitter casuale nell'intervallo (anti-ban)
        time.sleep(random.uniform(POLL_MIN, POLL_MAX))

# â”€â”€ AVVIO â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if __name__ == "__main__":
    _init_sessions()
    Thread(target=run_flask, daemon=True).start()
    log.info("ðŸŒ Flask keepalive avviato su porta %d", PORT)
    Thread(target=keepalive_loop, daemon=True).start()

    while True:
        try:
            bot_loop()
        except KeyboardInterrupt:
            log.info("â›” Bot fermato")
            break
        except Exception as e:
            log.exception("ðŸ’¥ Crash critico: %s â€” riavvio tra 30s", e)
            try:
                invia(f"ðŸ’¥ Crash: {e}\nRiavvio automatico tra 30s...")
            except Exception:
                pass
            time.sleep(30)
