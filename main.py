import time
import requests
import telebot
from flask import Flask
from threading import Thread

# ---------------- TELEGRAM ----------------

TOKEN = "8754079194:AAEOU2e5HsWnUW1af_vOhEhf7LXU8KciHOM"
CHANNEL_ID = "@pollicino01"

bot = telebot.TeleBot(TOKEN)

def invia(msg):
    try:
        bot.send_message(CHANNEL_ID, msg)
        print("Telegram:", msg)
    except Exception as e:
        print("Errore Telegram:", e)

# ---------------- API RISULTATI ----------------

API_URL = "https://api.tracksino.com/crazytime/latest"

def get_last_result():

    try:
        r = requests.get(API_URL, timeout=10)

        if r.status_code == 200:

            data = r.json()

            numero = str(data["result"])
            gid = data["id"]

            return numero, gid

    except Exception as e:

        print("Errore API:", e)

    return None, None


# ---------------- STATO BOT ----------------

stato = "FILTRO"
cicli_falliti = 0
sessioni = 0
fase = 0
ultimo_id = None

# ---------------- SERVER RENDER ----------------

app = Flask('')

@app.route('/')
def home():
    return "Crazy Time Bot Online"

def run():
    app.run(host="0.0.0.0", port=10000)

Thread(target=run).start()

# ---------------- AVVIO ----------------

print("BOT AVVIATO")
invia("🚀 Bot Crazy Time ONLINE")

while True:

    numero, gid = get_last_result()

    if numero and gid != ultimo_id:

        ultimo_id = gid
        print("Numero:", numero)

        # -------- FILTRO --------

        if stato == "FILTRO":

            if fase == 0 and numero == "5":
                fase = 1

            elif fase == 1:

                if numero == "5":
                    fase = 0
                    cicli_falliti = 0

                else:
                    fase = 2

            elif fase == 2:

                if numero == "5":

                    fase = 0
                    cicli_falliti = 0

                else:

                    fase = 0
                    cicli_falliti += 1

                    invia(f"❌ Ciclo Base fallito {cicli_falliti}/8")

                    if cicli_falliti >= 8:

                        stato = "SESSIONE"
                        sessioni = 0

                        invia("⚠️ TRIGGER ATTIVATO - PREPARARSI A PUNTARE")

        # -------- SESSIONE --------

        elif stato == "SESSIONE":

            if fase == 0 and numero == "5":

                fase = 1
                invia(f"🎰 Ciclo {sessioni+1}/12 - PUNTARE")

            elif fase == 1:

                if numero == "5":

                    invia("💰 CASSA - VINTO")
                    stato = "FILTRO"
                    fase = 0
                    cicli_falliti = 0

                else:

                    fase = 2
                    invia("⚠️ Perso colpo 1 - Puntata 2")

            elif fase == 2:

                if numero == "5":

                    invia("💰 CASSA AL SECONDO COLPO")
                    stato = "FILTRO"
                    fase = 0
                    cicli_falliti = 0

                else:

                    sessioni += 1
                    fase = 0

                    if sessioni >= 12:

                        invia("🛑 Limite 12 sessioni raggiunto")
                        stato = "FILTRO"
                        cicli_falliti = 0

                    else:

                        invia(f"❌ Ciclo perso - restano {12-sessioni}")

    time.sleep(10)