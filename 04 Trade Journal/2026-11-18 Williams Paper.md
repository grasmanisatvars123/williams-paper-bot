---
tags: [trade]
date: 2026-11-18
symbol: SPY
account: paper
strategy: "[[Overnight Report 2026-11-18|Williams]]"
trades: 1
result_R: -0.78
---
# 2026-11-18 Williams Paper Bot

Rakstījis bots. Noteikums: pārrāvums no atvēršanas ± puse no vakardienas diapazona, līdz 12:00 NY, stops otrā līnijā, ārā pie slēguma. Papīra konts, nav īsta nauda.

## Līmeņi
- Vakardienas diapazons: 727.00 – 739.76 (12.76 $)
- Atvēršana: 733.41
- Pirkt virs: **739.80**, pārdot zem: **727.04**
- Daudzums: 78 akcijas (risks ~995 $ no 100000 $)

## Darījums
| Virziens | Ieeja | Laiks | Stops | Izeja | Laiks | Kā | P&L $ | R |
|---|---|---|---|---|---|---|---|---|
| pārdot | 727.03 | 11:20 | 739.80 | 737.01 | 09:54 | aizvērts 2026-11-19 atvēršanā (slēgšanas palaišana nokavēja) | -778.52 | -0.78 |

## Piezīmes
- 09:31 Alpaca nepieņēma abus orderus (POST https://paper-api.alpaca.markets/v2/orders: HTTP 403 {"code":40310000,"existing_order_id":"b70cab94-c818-42f5-94c1-). Bots pats vēro cenu līdz 12:00.
- 11:26 Brokerī atrasta pozīcija (pārdots 78 pie 727.03), pievienota šodienas darījumam.
- 11:26 Stops brokerī pie 739.80.
- 16:12 Bots palaists pēc slēguma: pozīcija paliek līdz rītdienas atvēršanai.
- 16:30 Bots palaists pēc slēguma: pozīcija paliek līdz rītdienas atvēršanai.
- 16:39 Bots palaists pēc slēguma: pozīcija paliek līdz rītdienas atvēršanai.
- 2026-11-19 09:54 Pozīcija aizvērta nākamās dienas atvēršanā pie 737.01 (slēgšanas palaišanas sākās pēc 16:00).

## Pārskats (Claude)
*Salīdzinājums ar nākotnes testu (05 Bot/forward) un mācības.*
