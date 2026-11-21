# Williams paper bot

A small bot that trades one rule on SPY on an **Alpaca paper account** (simulated money, no real orders).
It runs on GitHub Actions; this repository is public only so the Actions minutes are free.

**Rule** (Larry Williams-style volatility breakout, fixed before the forward test):
- levels = today's 09:30 New York open ± 0.5 × yesterday's 09:30–16:00 range
- the first level reached before 12:00 is the entry (up = buy, down = sell), one trade a day
- the other level is the stop; no target; out at 15:58
- size: 10 % of equity between entry and stop (since 2026-11-21), position at most 4 × equity and 95 % of the day-trading buying power; the 4 × cap decides the size on almost every day

Alpaca refuses a buy stop and a sell stop on the same symbol at once, so the bot watches the price from 09:31 to
12:00, enters at market and then places the stop. Every run first checks the account and makes sure any SPY
position has its stop.

Files:
- `05 Bot/williams_bot.py` the bot (`auto`, `scan`, `status`)
- `05 Bot/alpaca.py` a minimal Alpaca REST client that refuses anything but a paper account
- `05 Bot/state_williams/` one state file a day, `04 Trade Journal/` one journal note a day (Latvian)
- `.github/workflows/williams-bot.yml` the schedule

Nothing here is investment advice.
