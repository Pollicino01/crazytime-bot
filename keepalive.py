import os
import time
import logging
import requests

log = logging.getLogger("keepalive")

def keepalive_loop():
    port = int(os.environ.get("PORT", 10000))
    url  = f"http://localhost:{port}/ping"
    while True:
        try:
            r = requests.get(url, timeout=10)
            log.debug("♻️ Keepalive ping → %d", r.status_code)
        except Exception as e:
            log.warning("⚠️ Keepalive ping fallito: %s", e)
        time.sleep(300)
