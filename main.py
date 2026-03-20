import os
import requests
import time
from typing import List, Optional

class TracksinoStrategyBot:
    def __init__(self):
        self.api_key = os.getenv("RAPIDAPI_KEY")
        self.api_host = "tracksino.p.rapidapi.com"
        self.headers = {"X-RapidAPI-Key": self.api_key, "X-RapidAPI-Host": self.api_host}
        
        # Stato del Motore di Gioco
        self.failed_cycles_count = 0      # Conteggio per il Filtro di Entrata (Target: 8)
        self.is_session_active = False   # Indica se siamo nei 12 cicli di gioco
        self.current_session_cycle = 0   # Conteggio dei 12 cicli attivi
        self.last_processed_spin_id = None

    def get_latest_spins(self) -> List[str]:
        """Recupera gli ultimi risultati reali da Tracksino."""
        url = f"https://{self.api_host}/live/crazytime"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            data = response.json()
            # Supponendo che 'last_results' sia una lista di stringhe/numeri (es. ["5", "1", "10", "5"])
            return [str(r) for r in data.get("last_results", [])]
        except Exception as e:
            print(f"Errore API: {e}")
            return []

    def process_logic(self):
        spins = self.get_latest_spins()
        if not spins: return

        # Evitiamo di processare la stessa ruotata più volte
        current_spin_id = spins[0]
        if current_spin_id == self.last_processed_spin_id:
            return
        self.last_processed_spin_id = current_spin_id

        # Analisi dei Cicli Base (Il 5 e i due colpi successivi)
        # Cerchiamo l'ultimo ciclo completato: [..., "5", Colpo1, Colpo2]
        for i in range(len(spins) - 2):
            if spins[i+2] == "5": # Trovato un "5" che ha avuto almeno 2 colpi successivi
                c1, c2 = spins[i+1], spins[i]
                win_in_cycle = (c1 == "5" or c2 == "5")

                if not self.is_session_active:
                    # FASE 1: IL FILTRO DI ENTRATA
                    if not win_in_cycle:
                        self.failed_cycles_count += 1
                        print(f"Ciclo Base fallito. Conteggio ritardo: {self.failed_cycles_count}/8")
                    else:
                        self.failed_cycles_count = 0 # Reset se il ciclo vince durante l'attesa
                    
                    if self.failed_cycles_count >= 8:
                        self.is_session_active = True
                        self.current_session_cycle = 0
                        print("🚀 TRIGGER ATTIVATO: Inizio Sessione di Gioco (12 cicli).")

                else:
                    # FASE 2: LA SESSIONE DI GIOCO (12 Cicli)
                    self.current_session_cycle += 1
                    if win_in_cycle:
                        print(f"✅ VINTO al ciclo {self.current_session_cycle}! Profitto incassato. Torno in attesa.")
                        self.reset_bot()
                    elif self.current_session_cycle >= 12:
                        print(f"🛑 Limite 12 sessioni raggiunto senza vincita. Stop temporaneo.")
                        self.reset_bot()
                    else:
                        print(f"Puntata persa nel ciclo {self.current_session_cycle}/12. In attesa del prossimo 5...")
                
                break # Processiamo un ciclo alla volta per precisione

    def reset_bot(self):
        self.failed_cycles_count = 0
        self.is_session_active = False
        self.current_session_cycle = 0

    def start(self):
        print("Bot Tracksino in ascolto... (Target: 8 fallimenti del '5')")
        while True:
            self.process_logic()
            time.sleep(15) # Polling ogni 15 secondi per non saturare l'API

if __name__ == "__main__":
    bot = TracksinoStrategyBot()
    bot.start()
