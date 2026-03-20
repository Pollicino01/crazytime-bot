# Bot Crazy Time

Bot Telegram che monitora il gioco **Crazy Time** su Tracksino e invia segnali di puntata al canale.

## Come funziona

- Legge `spins_since` per il numero **5** ogni 10 secondi dalla pagina Tracksino
- Conta i cicli falliti (pattern 5 → non5 → non5)
- Dopo **8 cicli falliti** attiva una **SESSIONE** di 12 cicli
- Invia i segnali sul canale Telegram configurato

---

## Deploy su Render.com

### 1. Crea il repository GitHub

1. Vai su [github.com](https://github.com) → **New repository**
2. Nome: `bot-crazy-time`
3. Lascialo **privato** (consigliato)
4. Clicca **Create repository**
5. Carica i file: `main.py` e `requirements.txt`

### 2. Crea il Web Service su Render

1. Vai su [render.com](https://render.com) → **New → Web Service**
2. Collega il tuo account GitHub e seleziona il repo `bot-crazy-time`
3. Compila così:

| Campo | Valore |
|---|---|
| **Name** | bot-crazy-time |
| **Region** | Frankfurt (EU) |
| **Branch** | main |
| **Runtime** | Python 3 |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `python main.py` |
| **Instance Type** | Free |

4. Clicca **Advanced** → **Add Environment Variable** e aggiungi:

| Key | Value |
|---|---|
| `TELEGRAM_TOKEN` | Il token del tuo bot (da @BotFather) |
| `CHANNEL_ID` | Il tuo canale, es. `@miocanale` |

5. Clicca **Create Web Service** — il deploy parte automaticamente

### 3. Configura UptimeRobot (keepalive gratuito)

Render free tier mette il servizio in sleep dopo 15 minuti senza traffico.  
Per tenerlo sveglio 24/7:

1. Vai su [uptimerobot.com](https://uptimerobot.com) → **Add New Monitor**
2. Monitor Type: **HTTP(s)**
3. Friendly Name: `Bot Crazy Time`
4. URL: `https://[nome-tuo-servizio].onrender.com/ping`
5. Monitoring Interval: **5 minutes**
6. Clicca **Create Monitor**

L'URL del tuo servizio Render lo trovi nella dashboard Render in alto a destra.

---

## File del progetto

```
bot-crazy-time/
├── main.py           # Codice del bot
└── requirements.txt  # Dipendenze Python
```
