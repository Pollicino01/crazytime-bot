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

# ── CONFIGURAZIONE LOGGING ──────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("crazy-time-bot")

# ── CREDENZIALI ──────────────────────────────────────────────
TELEGRAM_TOKEN = "8754079194:AAEOU2e5HsWnUW1af_vOhEhf7LXU8KciHOM"
CHAT_ID        = "670873588"
PORT           = int(os.environ.get("PORT", 10000))
TRACKSINO_URL  = "https://tracksino.com/crazytime"

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ── STATO DEL GIOCO (LOGICA FILTRO 8 / SESSIONE 12) ──────────
stato            = "FILTRO"      # "FILTRO" o "SESSIONE"
fase_ciclo       = 0             # 0: attesa primo 5, 1: attesa esito 1° colpo, 2: attesa esito 2° colpo
cicli_falliti    = 0             # contatore per arrivare a 8 nel Filtro
sessioni_contate = 0             # contatore per arrivare a 12 nella Sessione
prev_spins_since = None

def invia(msg):
    try:
        bot.send_message(CHAT_ID, msg)
        log.info(f"📤 Telegram: {msg[:30]}...")
    except Exception as e:
        log.error(f"Errore Telegram: {e}")

# ── LOGICA DI ANALISI DEGLI SPIN ─────────────────────────────
def process_spin(tipo):
    global stato, fase_ciclo, cicli_falliti, sessioni_contate
    is_cinque = (tipo == "5")

    if stato == "FILTRO":
        if fase_ciclo == 0 and is_cinque: 
            fase_ciclo = 1
        elif fase_ciclo == 1:
            if is_cinque: fase_ciclo = 0 # reset se esce subito un altro 5
            else: fase_ciclo = 2
        elif fase_ciclo == 2:
            if is_cinque: fase_ciclo = 0 # reset se esce al secondo
            else:
                # CICLO FALLITO (non è uscito il 5 per 2 colpi dopo il primo 5)
                cicli_falliti += 1
                fase_ciclo = 0
                invia(f"❌ Ciclo Base fallito {cicli_falliti}/8")
                if cicli_falliti >= 8:
                    stato = "SESSIONE"
                    sessioni_contate = 0
                    invia("⚠️ TRIGGER ATTIVATO!\nInizia SESSIONE di 12 cicli.\nAttendi il prossimo 5 per puntare.")

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
                invia("⚠️ Perso 1° colpo — Punta ancora sul prossimo 5")
        elif fase_ciclo == 2:
            if is_cinque:
                invia("✅ VINTO al 2° colpo! 🎉")
                stato, cicli_falliti, fase_ciclo = "FILTRO", 0, 0
            else:
                sessioni_contate += 1
                fase_ciclo = 0
                if sessioni_contate >= 12:
                    invia("🛑 12 cicli esauriti senza vincita. Reset a Filtro.")
                    stato, cicli_falliti = "FILTRO", 0
                else:
                    invia(f"❌ Ciclo perso. Rest
