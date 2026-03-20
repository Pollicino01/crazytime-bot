import os
import time
import re
import requests
import telebot
from flask import Flask
from threading import Thread

# ── CREDENZIALI ─────────────────────────────────────────────
TOKEN      = "8754079194:AAEOU2e5HsWnUW1af_vOhEhf7LXU8KciHOM"
CHANNEL_ID = "@pollicino01"
PORT       = int(os.environ.get("PORT", 10000))

# PARAMETRI LOGICA
SOGLIA_FALLIMENTI = 6  
MAX_SESSIONI      = 12 
POLL_INTERVAL     = 15 

bot = telebot.TeleBot(TOKEN)

# ── STATO DEL SISTEMA ───────────────────────────────────────
stato            = "FILTRO"   
fase_ciclo       = 0          
cicli_falliti    = 0          
sessioni_giocate = 0          
prev_spins_since = None

# ── FUNZIONI UTILITY ────────────────────────────────────────
def invia(msg):
    try:
        bot.send_message(CHANNEL_ID, msg, parse_mode="Markdown")
    except Exception as e:
        print(f"❌ Errore Invio: {e}")

def reset_totale():
    global stato, fase_ciclo, cicli_falliti, sessioni_giocate
    stato = "FILTRO"
    fase_ciclo = 0
    cicli_falliti = 0
    sessioni_giocate = 0

# ── LOGICA CORE ─────────────────────────────────────────────
def process_spin(tipo_numero):
    global stato, fase_ciclo, cicli_falliti, sessioni_giocate
    
    if stato == "FILTRO":
        if fase_ciclo == 0:
            if tipo_numero == "5": fase_ciclo = 1
        elif fase_ciclo == 1:
            if tipo_numero == "5": 
                cicli_falliti = 0
                fase_ciclo = 0
            else: fase_ciclo = 2
        elif fase_ciclo == 2:
            if tipo_numero == "5": 
                cicli_falliti = 0
                fase_ciclo = 0
            else:
                cicli_falliti += 1
                fase_ciclo = 0
                if cicli_falliti >= SOGLIA_FALLIMENTI:
                    stato = "SESSIONE"
                    sessioni_giocate = 0
                    invia(f"🚨 **TRIGGER ATTIVATO!**\nIl Ciclo Base è fallito {SOGLIA_FALLIMENTI} volte.\nInizio **SESSIONE** (12 cicli).")

    elif stato == "SESSIONE":
        if fase_ciclo == 0:
            if tipo_numero == "5":
                sessioni_giocate += 1
                invia(f"🎰 **Ciclo {sessioni_giocate}/{MAX_SESSIONI}**\n👉 Punta sul **5** per 2 colpi!")
                fase_ciclo = 1
        elif fase_ciclo == 1:
            if tipo_numero == "5":
                invia("✅ **VINTO al 1° colpo!**\nTorno in FILTRO.")
                reset_totale()
            else: fase_ciclo = 2
        elif fase_ciclo == 2:
            if tipo_numero == "5":
                invia("✅ **VINTO al 2° colpo!**\nTorno in FILTRO.")
                reset_totale()
            else:
                fase_ciclo = 0
                if sessioni_giocate >= MAX_SESSIONI:
                    invia(f"🛑 **Limite raggiunto.** Reset in FILTRO.")
                    reset_totale()
                else:
                    invia(f"❌ Ciclo perso. Restano {MAX_SESSIONI - sessioni_giocate} tentativi.")

# ── SCRAPING ────────────────────────────────────────────────
def get_n5_spins_since():
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get("https://tracksino.com/crazytime", headers=headers, timeout=15)
        n5_match = re.search(r'n5:\{spins_since:(\d+)', r.text)
        if n5_match:
            return int(n5_match.group(1))
        return None
    except:
        return None

# ── COMANDI ─────────────────────────────────────────────────
@bot.message_handler(commands=['status'])
def send_status(message):
    bot.reply_to(message, f"📊 Stato: {stato}\nFallimenti: {cicli_falliti}/{SOGLIA_FALLIMENTI}\nSessione: {sessioni_giocate}/{MAX_SESSIONI}")

# ── SERVER E AVVIO ──────────────────────────────────────────
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Online", 200

def run_flask():
    app.run(host='0.0.0.0', port=PORT)

def run_telebot():
    try:
        bot.remove_webhook()
        time.sleep(2)
        print("🤖 Polling avviato...")
        bot.infinity_polling(timeout=20, long_polling_timeout=10)
    except Exception as e:
        print(f"Errore Polling: {e}")

if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    Thread(target=run_telebot, daemon=True).start()
    
    # Invia un solo messaggio all'avvio
    invia("✅ **Sistema Avviato.** Monitoraggio @pollicino01 attivo.")
    
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
            time.sleep(POLL_INTERVAL)
        except Exception as e:
            print(f"Errore loop: {e}")
            time.sleep(10)
