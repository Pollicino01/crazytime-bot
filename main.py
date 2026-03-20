import os
import time
import re
import requests
import telebot
from flask import Flask
from threading import Thread

# ── CREDENZIALI INSERITE ────────────────────────────────────
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
        print(f"📤 Telegram inviato: {msg[:30]}...")
    except Exception as e:
        print(f"❌ Errore Telegram (Verifica se il bot è ADMIN): {e}")

def reset_totale():
    global stato, fase_ciclo, cicli_falliti, sessioni_giocate
    stato = "FILTRO"
    fase_ciclo = 0
    cicli_falliti = 0
    sessioni_giocate = 0

# ── LOGICA CORE (MACCHINA A STATI) ──────────────────────────
def process_spin(tipo_numero):
    global stato, fase_ciclo, cicli_falliti, sessioni_giocate

    if stato == "FILTRO":
        if fase_ciclo == 0:
            if tipo_numero == "5":
                fase_ciclo = 1
        
        elif fase_ciclo == 1:
            if tipo_numero == "5":
                cicli_falliti = 0 
                fase_ciclo = 0
            else:
                fase_ciclo = 2
        
        elif fase_ciclo == 2:
            if tipo_numero == "5":
                cicli_falliti = 0
                fase_ciclo = 0
            else:
                cicli_falliti += 1
                fase_ciclo = 0
                print(f"📊 Filtro: {cicli_falliti}/{SOGLIA_FALLIMENTI}")
                
                if cicli_falliti >= SOGLIA_FALLIMENTI:
                    stato = "SESSIONE"
                    sessioni_giocate = 0
                    invia(f"🚨 **TRIGGER ATTIVATO!**\nIl Ciclo Base è fallito {SOGLIA_FALLIMENTI} volte.\nInizio **SESSIONE DI GIOCO** (12 cicli).")

    elif stato == "SESSIONE":
        if fase_ciclo == 0:
            if tipo_numero == "5":
                sessioni_giocate += 1
                invia(f"🎰 **Ciclo {sessioni_giocate}/{MAX_SESSIONI}**\n👉 Punta sul **5** per i prossimi 2 colpi!")
                fase_ciclo = 1

        elif fase_ciclo == 1:
            if tipo_numero == "5":
                invia("✅ **VINTO al 1° colpo!**\nTorno in fase studio (FILTRO).")
                reset_totale()
            else:
                fase_ciclo = 2
        
        elif fase_ciclo == 2:
            if tipo_numero == "5":
                invia("✅ **VINTO al 2° colpo!**\nTorno in fase studio (FILTRO).")
                reset_totale()
            else:
                fase_ciclo = 0
                if sessioni_giocate >= MAX_SESSIONI:
                    invia(f"🛑 **Limite {MAX_SESSIONI} raggiunto.**\nReset automatico in FILTRO.")
                    reset_totale()
                else:
                    invia(f"❌ Ciclo perso. Restano {MAX_SESSIONI - sessioni_giocate} tentativi.")

# ── SCRAPING TRACKSINO ──────────────────────────────────────
def get_n5_spins_since():
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        }
        r = requests.get("https://tracksino.com/crazytime", headers=headers, timeout=15)
        if r.status_code != 200: return None
        n5_match = re.search(r'n5:\{spins_since:(\d+)', r.text)
        return int(n5_match.group(1)) if n5_match else None
    except Exception as e:
        print(f"❌ Errore scraping: {e}")
        return None

# ── COMANDI TELEGRAM ────────────────────────────────────────
@bot.message_handler(commands=['status'])
def send_status(message):
    global stato, cicli_falliti, sessioni_giocate
    msg = (f"📊 **STATO BOT**\n\n"
           f"Stato: `{stato}`\n"
           f"Fallimenti Filtro: `{cicli_falliti}/{SOGLIA_FALLIMENTI}`\n"
           f"Cicli Sessione: `{sessioni_giocate}/{MAX_SESSIONI}`")
    bot.reply_to(message, msg, parse_mode="Markdown")

@bot.message_handler(commands=['reset'])
def manual_reset(message):
    reset_totale()
    bot.reply_to(message, "🔄 Reset eseguito. Torno in FILTRO.")

# ── LOOP E SERVER ───────────────────────────────────────────
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Crazy Time is Running", 200

def run_flask(): app.run(host='0.0.0.0', port=PORT)
def run_telebot(): bot.infinity_polling()

if __name__ == "__main__":
    # Avvio Servizi
    Thread(target=run_flask, daemon=True).start()
    Thread(target=run_telebot, daemon=True).start()
    
    print("🚀 Bot avviato con successo!")
    invia("🚀 **Bot Crazy Time Online!**\nLogica: Filtro 6 / Sessione 12\nMonitoraggio avviato su @pollicino01")
    
    # Loop di monitoraggio
    while True:
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
