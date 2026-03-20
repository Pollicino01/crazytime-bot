import os
import threading
from flask import Flask
import requests
import time
from typing import List

# 1. Configurazione Server Web per Render (Port Check)
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot Tracksino is active", 200

# 2. La tua classe Bot (senza modifiche alla logica)
class TracksinoStrategyBot:
    def __init__(self):
        self.api_key = os.getenv("RAPIDAPI_KEY")
        self.api_host = "tracksino.p.rapidapi.com"
        self.headers = {"X-RapidAPI-Key": self.api_key, "X-RapidAPI-Host": self.api_host}
        self.failed_cycles_count = 0
        self.is_session_active = False
        self.current_session_cycle = 0
        self.last_processed_spin_id = None

    def get_latest_spins(self) -> List[str]:
        url = f"https://{self.api_host}/live/crazytime"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            data = response.json()
            return [str(r) for r in data.get("last_results", [])]
        except Exception as e:
            print(f"Errore API: {e}")
            return []

    def process_logic(self):
        spins = self.get_latest_spins()
        if not spins: return
        current_spin_id = spins[0]
        if current_spin_id == self.last_processed_spin_id:
            return
        self.last_processed_spin_id = current_spin_id

        for i in range(len(spins) - 2):
            if spins[i+2] == "5":
                c1, c2 = spins[i+1], spins[i]
                win_in_cycle = (c1 == "5" or c2 == "5")
                if not self.is_session_active:
                    if not win_in_cycle:
                        self.failed_cycles_count += 1
                        print(f"Ciclo Base fallito: {self.failed_cycles_count}/8")
                    else:
                        self.failed_cycles_count = 0
                    if self.failed_cycles_count >= 8:
                        self.is_session_active = True
                        print("🚀 TRIGGER ATTIVATO")
                else:
                    self.current_session_cycle += 1
                    if win_in_cycle:
                        print(f"✅ VINTO al ciclo {self.current_session_cycle}!")
                        self.reset_bot()
                    elif self.current_session_cycle >= 12:
                        print("🛑 Limite raggiunto.")
                        self.reset_bot()
                break

    def reset_bot(self):
        self.failed_cycles_count = 0
        self.is_session_active = False
        self.current_session_cycle = 0

    def start(self):
        print("Bot in ascolto...")
        while True:
            self.process_logic()
            time.sleep(15)

# 3. Funzione per avviare il bot in un thread separato
def run_bot_thread():
    bot = TracksinoStrategyBot()
    bot.start()

if __name__ == "__main__":
    # Avvia il bot in background
    t = threading.Thread(target=run_bot_thread)
    t.daemon = True # Il thread si chiude se il processo principale muore
    t.start()
    
    # Avvia Flask sulla porta richiesta da Render
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
