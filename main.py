 html.find("</script>", body_end)
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
