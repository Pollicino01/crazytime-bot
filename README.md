# 🎰 Bot Crazy Time v5.0 — Deploy Render.com

Monitora **Crazy Time** in tempo reale e invia segnali su Telegram.
- **Sorgente primaria**: CasinoScores.com (API JSON, più affidabile)
- **Fallback automatico**: Tracksino.com (HTML scraping NUXT)
- **Proxy rotanti**: supporto multi-proxy con round-robin

---

## File nella cartella

```
bot/
├── bot.py            ← Bot principale (proxy + casinoscores + tracksino)
├── keepalive.py      ← Thread keepalive per Render free
├── requirements.txt  ← Dipendenze Python
├── render.yaml       ← Configurazione Render
├── .env.example      ← Esempio variabili d'ambiente
├── .gitignore
└── README.md
```

---

## Variabili d'ambiente

### Obbligatorie

| Variabile        | Descrizione                              |
|------------------|------------------------------------------|
| `TELEGRAM_TOKEN` | Token del bot (da @BotFather)            |
| `CHANNEL_ID`     | `@canale` oppure `-100xxxxxxxxxx`        |

### Proxy (opzionale — fortemente consigliato)

**Opzione A — Multi-proxy (consigliata):**

```
PROXY_LIST=191.96.254.138:6185:gnrzyqfs:3lbaq4efyfv5,198.23.239.134:6540:gnrzyqfs:3lbaq4efyfv5,198.105.121.200:6462:gnrzyqfs:3lbaq4efyfv5,216.10.27.159:6837:gnrzyqfs:3lbaq4efyfv5
```

**Opzione B — Proxy singolo:**

```
PROXY_HOST=191.96.254.138
PROXY_PORT=6185
PROXY_USER=gnrzyqfs
PROXY_PASS=3lbaq4efyfv5
```

---

## Deploy su Render.com

### Step 1 — Carica su GitHub

```bash
cd bot
git init
git add .
git commit -m "Bot Crazy Time v5.0"
git branch -M main
git remote add origin https://github.com/TUO_USERNAME/crazy-time-bot.git
git push -u origin main
```

### Step 2 — Crea il servizio su Render

1. [render.com](https://render.com) → **New** → **Web Service**
2. Collega il repository GitHub
3. Configura:
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python bot.py`
   - **Plan**: Free

### Step 3 — Variabili d'ambiente su Render

In **Environment** aggiungi `TELEGRAM_TOKEN`, `CHANNEL_ID` e `PROXY_LIST`.

---

## Endpoint di monitoraggio

| Endpoint   | Cosa mostra                                   |
|------------|-----------------------------------------------|
| `/`        | Stato base                                    |
| `/healthz` | Health check JSON `{"status":"ok"}`           |
| `/status`  | Stato macchina, sorgente attiva, proxy count  |
| `/ping`    | Risponde `pong` (keepalive)                   |

---

## Logica del Bot

```
FILTRO (cicli base):
  Fase 0 → Attende il primo 5
  Fase 1 → Dopo 5: se esce ancora 5 reset, altrimenti Fase 2
  Fase 2 → Se 5 reset; se non-5 conta fallimento
  Dopo 8 fallimenti → TRIGGER → passa a SESSIONE

SESSIONE (12 cicli):
  Fase 0 → Attende 5 → invia "Punta!"
  Fase 1 → Se 5 VINTO (1° colpo); altrimenti avvisa
  Fase 2 → Se 5 VINTO (2° colpo); altrimenti ciclo perso
  Dopo 12 cicli senza vittoria → chiude sessione → torna FILTRO
```

---

## Anti-ban

| Tecnica              | Dettaglio                                              |
|----------------------|--------------------------------------------------------|
| Proxy rotanti        | Round-robin su tutti i proxy in PROXY_LIST             |
| User-Agent rotation  | 10 browser diversi scelti casualmente                  |
| Jitter temporale     | Intervallo variabile 12-18s                            |
| Session rotation     | Nuova sessione HTTP ogni 40 richieste                  |
| Gestione 403/429     | Pausa automatica 30-60s se il sito blocca              |
| Backoff esponenziale | Attesa progressiva in caso di errori consecutivi       |
| Cloudscraper         | Bypass automatico Cloudflare JS challenge              |
