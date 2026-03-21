"""
keepalive.py — Evita lo sleep del piano free di Render.
Invia un ping al proprio URL ogni 14 minuti.
"""

import os
import time
import logging
import requests

log = logging.getLogger("keepalive")

RENDER_URL    = os.environ.get("RENDER_EXTERNAL_URL", "")
PING_INTERVAL = 14 * 60


def keepalive_loop():
    if not RENDER_URL:
        log.info("RENDER_EXTERNAL_URL non impostato — keepalive disabilitato")
        return

    log.info("🔄 Keepalive attivo → %s/ping ogni %dm", RENDER_URL, PING_INTERVAL // 60)

    while True:
        try:
            r = requests.get(f"{RENDER_URL}/ping", timeout=10)
            log.info("🏓 Keepalive ping: %d", r.status_code)
        except Exception as e:
            log.warning("⚠️ Keepalive ping fallito: %s", e)
        time.sleep(PING_INTERVAL)
