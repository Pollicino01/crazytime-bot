import os
import time
import re
import requests
import telebot
import datetime
from flask import Flask
from threading import Thread

# ── CONFIGURAZIONE (DA VARIABILI D'AMBIENTE) ────────────────
TOKEN      = os.environ.get("TELEGRAM_TOKEN", "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
PORT       = int(os.environ.get("PORT", 10000))

# PARAMETRI LOGICA
SOGLIA_FALLIMENTI = 6  # Cicli base falliti necessari per attivarsi
MAX_SESSIONI      = 12 # Numero di cicli di gioco durante la sessione
POLL_INTERVAL     = 15 # Secondi tra una lettura e l'altra su Tracksino

if not TOKEN or not CHANNEL_ID:
    print("❌ ERRORE: Imposta TELEGRAM_TOKEN e CHANNEL_ID su Render!")

bot = telebot.TeleBot(TOKEN)

# ── STATO DEL SISTEMA ───────────────────────────────────────
stato            = "FILTRO"   # "FILTRO" o "SESSIONE"
fase_ciclo       = 0          # 0: Attesa '5', 1: Puntata 1, 2: Puntata 2
cicli_falliti    = 0          # Conta i fallimenti consecutivi nel filtro
sessioni_giocate = 0          # Conta i cicli nella sessione attiva
prev_spins_since = None

# ── FUNZIONI UTILITY ────────────────────────────────────────
def invia(msg):
    try:
        bot.send_message(CHANNEL_ID, msg, parse_mode="Markdown")
        print(f"📤 Telegram: {msg.replace('*','')}")
    except Exception as e:
        print(f"❌ Errore invio Telegram: {e}")

def reset_totale():
    global stato, fase_ciclo, cicli_falliti, sessioni_giocate
    stato = "FILTRO"
    fase_ciclo = 0
    cicli_falliti = 0
    sessioni_giocate = 0

# ── LOGICA CORE (MACCHINA A STATI) ──────────────────────────
def process_spin(tipo_numero):
    global stato, fase_ciclo, cicli_falliti, sessioni_giocate

    # --- FASE DI FILTRO (Studio Silenzioso) ---
    if stato == "FILTRO":
        if fase_ciclo == 0:
            if tipo_numero == "5":
                fase_ciclo = 1
        
        elif fase_ciclo == 1:
            if tipo_numero == "5": # Vinto al 1° colpo (Ciclo Base OK)
                cicli_falliti = 0 # Reset serie negativa
                fase_ciclo = 0
            else:
                fase_ciclo = 2
        
        elif fase_ciclo == 2:
            if tipo_numero == "5": # Vinto al 2° colpo (Ciclo Base OK)
                cicli_falliti = 0
                fase_ciclo = 0
            else: # CICLO BASE FALLITO
                cicli_falliti += 1
                fase_ciclo = 0
                print(f"📊 Filtro: {cicli_falliti}/{SOGLIA_FALLIMENTI} fallimenti accumulati.")
                
                if cicli_falliti >= SOGLIA_FALLIMENTI:
                    stato = "SESSIONE"
                    sessioni_giocate = 0
                    invia(f"🚨 **TRIGGER ATTIVATO!**\nIl Ciclo Base è fallito {SOGLIA_FALLIMENTI} volte di fila.\nInizio **SESSIONE DI GIOCO** (12 cicli).")

    # --- FASE DI SESSIONE (Segnali Telegram Attivi) ---
    elif stato == "SESSIONE":
        if fase_ciclo == 0:
            if tipo_numero == "5":
                sessioni_giocate += 1
                invia(f"🎰 **Ciclo {sessioni_giocate}/{MAX_SESSIONI}**\n👉 Punta sul **5** per i prossimi 2 colpi!")
                fase_ciclo = 1

        elif fase_ciclo == 1:
            if tipo_numero == "5": # VINTO AL 1° COLPO
                invia("✅ **VINTO al 1° colpo!**\nProfitto incassato. Torno in fase studio (FILTRO).")
                reset_totale()
            else:
                fase_ciclo = 2
        
        elif fase_ciclo == 2:
            if tipo_numero == "5": # VINTO AL 2° COLPO
                invia("✅ **VINTO al 2° colpo!**\nProfitto incassato. Torno in fase studio (FILTRO).")
                reset_totale()
            else: # CICLO DI SESSIONE PERSO
                fase_ciclo = 0
                if sessioni_giocate >= MAX_SESSIONI:
                    invia(f"🛑 **Limite {MAX_SESSIONI} sessioni raggiunto.**\nNessuna vincita trovata. Reset automatico in FILTRO.")
                    reset_totale()
                else:
                    invia(f"❌ Ciclo perso. Restano {MAX_SESSIONI - sessioni_giocate} tentativi.")

# ── SCRAPING TRACKSINO ──────────────────────────────────────
def get_n5_spins_since():
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        r = requests.get("https://tracksino.com/crazytime", headers=headers, timeout=15)
        if r.status_code != 200: return None

        # Estrazione diretta del valore n5 dal dump JSON di Nuxt
        n5_match = re.search(r'n5:\{spins_since:(\d+)', r.text)
        if n5_match:
            return int(n5_match.group(1))
        return None
    except Exception as e:
        print(f"❌ Errore scraping: {e}")
        return None

# ── COMANDI TELEGRAM ────────────────────────────────────────
@bot.message_handler(commands=['status'])
def send_status(message):
    global stato, cicli_falliti, sessioni_giocate
    msg = (f"📊 **STATO ATTUALE**\n\n"
           f"Stato: `{stato}`\n"
           f"Fallimenti Filtro: `{cicli_falliti}/{SOGLIA_FALLIMENTI}`\n"
           f"Cicli Sessione: `{sessioni_giocate}/{MAX_SESSIONI}`")
    bot.reply_to(message, msg, parse_mode="Markdown")

@bot.message_handler(commands=['reset'])
def manual_reset(message):
    reset_totale()
    bot.reply_to(message, "🔄 Reset manuale eseguito. Il bot torna in FILTRO.")

# ── LOOP PRINCIPALE ─────────────────────────────────────────
def bot_loop():
    global prev_spins_since
    print("🚀 Monitoraggio Tracksino avviato...")
    
    while True:
        curr = get_n5_spins_since()
        
        if curr is not None:
            if prev_spins_since is not None and curr != prev_spins_since:
                # Se curr è diminuito, significa che è uscito un 5
                if curr < prev_spins_since:
                    process_spin("5")
                    # Se curr > 0, ci sono stati altri spin non-5 nel frattempo
                    for _ in range(curr):
                        process_spin("non5")
                else:
                    # Se curr è aumentato, sono passati spin senza il 5
                    for _ in range(curr - prev_spins_since):
                        process_spin("non5")
            
            prev_spins_since = curr
        
        time.sleep(POLL_INTERVAL)

# ── SERVER FLASK & AVVIO ────────────────────────────────────
app = Flask(__name__)

@app.route('/')
def home(): return "Bot Online", 200

def run_flask():
    app.run(host='0.0.0.0', port=PORT)

def run_telebot():
    bot.infinity_polling()

if __name__ == "__main__":
    # Avvia Flask per Render
    Thread(target=run_flask, daemon=True).start()
    # Avvia Polling Comandi Telegram
    Thread(target=run_telebot, daemon=True).start()
    # Avvia Loop Logica
    bot_loop()
