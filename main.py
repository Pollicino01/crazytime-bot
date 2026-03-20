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

# LOGICA (LA TUA)
SOGLIA_FALLIMENTI = 6  
MAX_SESSIONI      = 12 
POLL_INTERVAL     = 15 # Lettura ogni 15 secondi

bot = telebot.TeleBot(TOKEN)

# ── STATO DEL SISTEMA ───────────────────────────────────────
stato            = "FILTRO"   
fase_ciclo       = 0          
cicli_falliti    = 0          
sessioni_giocate = 0          
prev_spins_since = None

def invia(msg):
    try:
        bot.send_message(CHANNEL_ID, msg, parse_mode="Markdown")
    except Exception as e:
        print(f"❌ Errore Telegram: {e}")

def reset_totale():
    global stato, fase_ciclo, cicli_falliti, sessioni_giocate
    stato = "FILTRO"
    fase_ciclo = 0
    cicli_falliti = 0
    sessioni_giocate = 0

# ── LOGICA CORE (Filtro 6 / Sessione 12) ────────────────────
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
                print(f"📊 [FILTRO] Ciclo fallito: {cicli_falliti}/{SOGLIA_FALLIMENTI}")
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
                invia("✅ **VINTO al 1° colpo!**\nProfitto preso. Torno in FILTRO.")
                reset_totale()
            else: fase_ciclo = 2
        elif fase_ciclo == 2:
            if tipo_numero == "5":
                invia("✅ **VINTO al 2° colpo!**\nProfitto preso. Torno in FILTRO.")
                reset_totale()
            else:
                fase_ciclo = 0
                if sessioni_giocate >= MAX_SESSIONI:
                    invia(f"🛑 **Limite 12 sessioni raggiunto.**\nReset automatico in FILTRO.")
                    reset_totale()
                else:
                    invia(f"❌ Ciclo perso. Restano {MAX_SESSIONI - sessioni_giocate} tentativi.")

# ── TRACKER API (STABILISSIMO) ──────────────────────────────
def get_data_ultra():
    """Usa un endpoint alternativo più stabile di Tracksino"""
    try:
        # Headers per simulare browser reale ed evitare blocchi
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://tracksino.com/"
        }
        # Tracker alternativo che legge i dati grezzi
        r = requests.get("https://tracksino.com/crazytime", headers=headers, timeout=10)
        
        # Estrazione ultra-precisa con Regex
        match = re.search(r'n5:\{spins_since:(\d+)', r.text)
        if match:
            return int(match.group(1))
        return None
    except:
        return None

# ── COMANDI E MONITORAGGIO ──────────────────────────────────
@bot.message_handler(commands=['status'])
def send_status(message):
    bot.reply_to(message, f"📈 **STATUS 24/7**\nStato: {stato}\nFiltro: {cicli_falliti}/{SOGLIA_FALLIMENTI}\nSessione: {sessioni_giocate}/{MAX_SESSIONI}\nUltimo dato: {prev_spins_since}")

# ── AVVIO ───────────────────────────────────────────────────
app = Flask(__name__)
@app.route('/')
def home(): return "<h1>Bot 24/7 Online</h1>", 200

def run_flask(): app.run(host='0.0.0.0', port=PORT)
def run_telebot():
    bot.remove_webhook()
    time.sleep(2)
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    Thread(target=run_telebot, daemon=True).start()
    
    invia("⚡ **Bot Ultra-Stabile Online.**\nMonitoraggio 24/7 attivato su @pollicino01")
    
    while True:
        try:
            curr = get_data_ultra()
            if curr is not None:
                if prev_spins_since is None:
                    prev_spins_since = curr
                    print(f"✅ Avvio: spins_since = {curr}")
                elif curr != prev_spins_since:
                    # Rilevato cambio spin
                    diff = curr - prev_spins_since
                    if curr < prev_spins_since:
                        # È uscito il 5
                        process_spin("5")
                        for _ in range(curr): process_spin("non5")
                    else:
                        # Sono passati altri numeri
                        for _ in range(diff): process_spin("non5")
                    prev_spins_since = curr
                else:
                    print(f"⏳ In attesa di nuovi spin... (Attuale: {curr})")
            else:
                print("⚠️ Errore lettura dati (riprovo...)")
            
            time.sleep(POLL_INTERVAL)
            
        except Exception as e:
            print(f"💥 Errore Loop: {e}")
            time.sleep(30)
