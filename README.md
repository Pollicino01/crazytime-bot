| Backoff esponenziale | Aumenta l'attesa progressivamente in caso di errori |
| Header realistici | Sec-Fetch-*, Accept-Encoding, DNT, ecc. |

---

## 6. Logica del Bot

```
FILTRO:
  Fase 0: Attende primo 5
  Fase 1: Dopo 5 → se esce ancora 5 reset, altrimenti Fase 2
  Fase 2: Se 5 → reset; se non-5 → conta fallimento
  Dopo 8 fallimenti → TRIGGER → passa a SESSIONE

SESSIONE (12 cicli):
  Fase 0: Attende 5 → invia segnale "Punta!"
  Fase 1: Se 5 → VINTO (1° colpo); altrimenti avvisa
  Fase 2: Se 5 → VINTO (2° colpo); altrimenti ciclo perso
  Dopo 12 cicli senza vittoria → chiude sessione → torna FILTRO
```
