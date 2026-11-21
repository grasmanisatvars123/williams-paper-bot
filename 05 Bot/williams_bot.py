"""Williams paper bot for SPY on Alpaca (from 2026-11-18). PAPER ONLY: alpaca.py refuses any other account.

Rule (03 Strategies/Overnight Report 2026-11-18.md, the only rule positive in every backtest year):
  levels   = today's 09:30 open +/- 0.5 x yesterday's 09:30-16:00 range
  entry    = the first level price reaches before 12:00 New York: up = buy, down = sell (one trade a day)
  stop     = the other level; no target; out at the close

Alpaca refuses a buy stop and a sell stop on the same symbol at once ("potential wash trade"), so the bot watches
the price itself from 09:31 to 12:00 and enters at market, then places the stop at Alpaca. Three runs a day:
  open   (~09:31-12:00) work out the levels, watch, enter, place the stop
  noon   (~12:00)       nothing left to do in watch mode except check the stop
  close  (~14:00-15:58) keep the stop until 15:58, then close with a market order
Every run first checks the account: an SPY position without a stop gets one (or is closed).
"python williams_bot.py auto" picks the phase from the clock and today's state file, so a late or repeated run is safe.

Run:  python williams_bot.py auto        the phase that is due now
      python williams_bot.py scan        today's levels only, no orders
      python williams_bot.py status      read only: equity, SPY position, open and today's orders
      python williams_bot.py probe       place two far-away 1-share stop orders, see if Alpaca accepts both, cancel
"""
import json, logging, math, os, sys, time
import pandas as pd
from alpaca import Alpaca, ApiError

NY = "America/New_York"
SYMBOL = "SPY"
START = "2026-11-18"          # moved up from 2026-11-23 at the user's request; the TJR test ended 2026-11-17
RISK_PCT = 0.10               # 10 % of equity between entry and stop (the user's choice on 2026-11-21, paper only)
MAX_NOTIONAL = 4.0            # position value at most 4 x equity (Alpaca's day-trading limit); in practice this
                              # cap decides the size almost every day (see 03 Strategies/Drawdown Study 2026-11-21.md)
MIN_RISK = 0.10               # $ per share; 1 index point
ENTRY_END = "12:00"
POLL = 10
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(HERE, "state_williams")
JOURNAL_DIR = os.path.join(os.path.dirname(HERE), "04 Trade Journal")
log = logging.getLogger("williams")


# ---------------------------------------------------------------- time (replaced in the offline test)
def now():
    return pd.Timestamp.now(tz=NY)


def sleep_until(t):
    while now() < t:
        time.sleep(max(1.0, min(30.0, (t - now()).total_seconds())))


def at(day, hhmm):
    return pd.Timestamp(f"{day} {hhmm}", tz=NY)


def px(x):
    return round(float(x) + 1e-9, 2)


# ---------------------------------------------------------------- state and journal
def new_state(day):
    return dict(day=day, open_px=None, prior_high=None, prior_low=None, up=None, dn=None, qty=0, equity=None,
                mode="orders", orders={}, trade=None, notes=[], open_done=False, noon_done=False, close_done=False,
                done=False, close_time="16:00")


def load(day):
    p = os.path.join(STATE_DIR, f"{day}.json")
    s = new_state(day)
    if os.path.exists(p):
        s.update(json.load(open(p, encoding="utf-8")))
    return s


def save(s):
    os.makedirs(STATE_DIR, exist_ok=True)
    p = os.path.join(STATE_DIR, f"{s['day']}.json")
    json.dump(s, open(p + ".tmp", "w", encoding="utf-8"), indent=1)
    os.replace(p + ".tmp", p)
    journal(s)


def note(s, text):
    log.info(text)
    s["notes"].append(f"{now():%H:%M} {text}")


def journal(s):
    t = s["trade"]
    r = t.get("R") if t else None
    out = ["---", "tags: [trade]", f"date: {s['day']}", f"symbol: {SYMBOL}", "account: paper",
           'strategy: "[[Overnight Report 2026-11-18|Williams]]"', f"trades: {1 if t else 0}",
           f"result_R: {r:.2f}" if r is not None else "result_R: ", "---", f"# {s['day']} Williams Paper Bot", "",
           "Rakstījis bots. Noteikums: pārrāvums no atvēršanas ± puse no vakardienas diapazona, līdz 12:00 NY, "
           "stops otrā līnijā, ārā pie slēguma. Papīra konts, nav īsta nauda.", "", "## Līmeņi"]
    if s["up"]:
        out += [f"- Vakardienas diapazons: {s['prior_low']:.2f} – {s['prior_high']:.2f} "
                f"({s['prior_high'] - s['prior_low']:.2f} $)",
                f"- Atvēršana: {s['open_px']:.2f}", f"- Pirkt virs: **{s['up']:.2f}**, pārdot zem: **{s['dn']:.2f}**",
                f"- Daudzums: {s['qty']} akcijas (risks ~{s['qty'] * (s['up'] - s['dn']):.0f} $ no "
                f"{float(s['equity'] or 0):.0f} $)"]
    else:
        out.append("- Nav aprēķināti.")
    out += ["", "## Darījums"]
    if t:
        out += ["| Virziens | Ieeja | Laiks | Stops | Izeja | Laiks | Kā | P&L $ | R |", "|---|---|---|---|---|---|---|---|---|",
                f"| {'pirkt' if t['side'] == 1 else 'pārdot'} | {t['entry']:.2f} | {t['entry_time']} | {t['stop']:.2f} | "
                + (f"{t['exit']:.2f} | {t['exit_time']} | {t['how']} | {t['pnl']:.2f} | {t['R']:.2f} |" if t.get("exit")
                   else "atvērts | | | | |")]
    else:
        out.append("Nav darījuma.")
    out += ["", "## Piezīmes"] + ([f"- {x}" for x in s["notes"]] or ["- Nav."])
    out += ["", "## Pārskats (Claude)", "*Salīdzinājums ar nākotnes testu (05 Bot/forward) un mācības.*", ""]
    os.makedirs(JOURNAL_DIR, exist_ok=True)
    with open(os.path.join(JOURNAL_DIR, f"{s['day']} Williams Paper.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(out))


def lv_time(day, hhmm):
    """New York HH:MM on that day as Latvian time."""
    return pd.Timestamp(f"{day} {hhmm}", tz=NY).tz_convert("Europe/Riga").strftime("%H:%M")


def usd(x):
    return f"{abs(x):,.0f}".replace(",", " ") + " $"


def message(s):
    """A short plain-language message for the phone (written to $MSG_FILE; sent via WhatsApp).
    Nothing is sent while the bot is only waiting for a level."""
    t, d = s["trade"], s["day"]
    head = f"Williams bots, {pd.Timestamp(d):%d.%m.} (mācību konts, nav īsta nauda):"
    if t and t.get("exit"):
        eq = float(s["equity"] or 0) + t["pnl"]
        bought = t["side"] == 1
        txt = (f"{head} šodien {'NOPELNĪJA' if t['pnl'] >= 0 else 'ZAUDĒJA'} {usd(t['pnl'])}. "
               f"Tas {'nopirka' if bought else 'pārdeva'} SPY par {t['entry']:.2f} un "
               f"{'pārdeva' if bought else 'atpirka'} par {t['exit']:.2f}. Kontā tagad ap {usd(eq)}.")
    elif t:
        what = "NOPIRKA SPY (gaida, ka cena celsies)" if t["side"] == 1 else "PĀRDEVA SPY (gaida, ka cena kritīsies)"
        risk = abs(t["entry"] - t["stop"]) * t["qty"]
        txt = (f"{head} {what} par {t['entry']:.2f}. Ja cena aizies līdz {t['stop']:.2f}, bots izies ar zaudējumu "
               f"ap {usd(risk)}. Citādi tas aizvērs darījumu {lv_time(d, '15:58')} pēc Latvijas laika un atsūtīs rezultātu.")
    elif s["up"] and s["noon_done"]:
        txt = (f"{head} šodien darījuma nebija. Cena neaizgāja ne līdz {s['up']:.2f} (pirkšanai), "
               f"ne līdz {s['dn']:.2f} (pārdošanai). Nauda kontā nemainījās.")
    elif s["up"]:
        return
    else:
        why = s["notes"][-1].split(" ", 1)[-1] if s["notes"] else ""
        txt = f"{head} šodien darījuma nebija. {why}".strip()
    if os.environ.get("MSG_FILE"):
        open(os.environ["MSG_FILE"], "w", encoding="utf-8").write(txt)
    print(txt)


# ---------------------------------------------------------------- market data
def session(api, day):
    """(open, close) of today's session, or None when the market is closed."""
    cal = api.calendar(day)
    if not cal or cal[0]["date"] != day:
        return None
    return cal[0]["open"], cal[0]["close"]


def prior_range(api, day):
    d = pd.Timestamp(day)
    cal = [c for c in api.calendar_range((d - pd.Timedelta(days=10)).date(), (d - pd.Timedelta(days=1)).date())
           if c["date"] < day]
    c = cal[-1]
    m1 = api.bars(SYMBOL, "1Min", at(c["date"], c["open"]), at(c["date"], c["close"]) - pd.Timedelta(minutes=1), feed="sip")
    m1 = m1[(m1.index >= at(c["date"], c["open"])) & (m1.index < at(c["date"], c["close"]))]
    return float(m1.high.max()), float(m1.low.min())


def finished_bars(api, day):
    if now() < at(day, "09:31"):                         # before the open Alpaca refuses a start in the future
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    m1 = api.bars(SYMBOL, "1Min", at(day, "09:30"), feed="iex")
    return m1[(m1.index >= at(day, "09:30")) & (m1.index + pd.Timedelta(minutes=1) <= now())]


def fill(o):
    """(price, NY time) of a filled order, else None."""
    if o and o.get("status") in ("filled", "partially_filled") and o.get("filled_avg_price"):
        return float(o["filled_avg_price"]), pd.Timestamp(o["filled_at"]).tz_convert(NY)
    return None


def cancel_quiet(api, oid):
    try:
        api.cancel(oid)
    except ApiError as e:
        log.info("cancel %s: %s", oid, e)


# ---------------------------------------------------------------- phases
def phase_open(api, s):
    day = s["day"]
    sleep_until(at(day, "09:31") + pd.Timedelta(seconds=5))
    if api.position_qty(SYMBOL) > 0:                    # left over from a missed close
        o = api.close_position(SYMBOL)                  # SPY only: other positions on the account are not ours
        note(s, "Atlikusi pozīcija no iepriekšējās dienas aizvērta pie atvēršanas.")
        record_leftover(api, o, day)
    hi, lo = prior_range(api, day)
    m1 = finished_bars(api, day)
    if not len(m1):
        note(s, "Nav šodienas minūšu datu, darījuma nebūs.")
        s.update(open_done=True); return
    o = float(m1.open.iloc[0])
    rg = hi - lo
    up, dn = px(o + rg / 2), px(o - rg / 2)
    acct = api.account()
    eq = float(acct["equity"])
    bp = float(acct.get("daytrading_buying_power") or 0)    # Alpaca refuses orders above this
    cap = min(MAX_NOTIONAL * eq, 0.95 * bp) if bp > 0 else MAX_NOTIONAL * eq
    qty = int(min(RISK_PCT * eq / max(up - dn, 1e-9), cap / max(up, o)))
    s.update(open_px=o, prior_high=hi, prior_low=lo, up=up, dn=dn, qty=qty, equity=eq)
    if up - dn < MIN_RISK or qty < 1:
        note(s, f"Diapazons pārāk mazs ({up - dn:.2f} $), darījuma nebūs.")
        s.update(open_done=True); return
    if m1.high.max() >= up or m1.low.min() <= dn:
        note(s, f"Bots sāka {now():%H:%M}, un cena jau bija aizsniegusi līmeni. Šodien izlaists.")
        s.update(open_done=True); return
    # Alpaca refuses a buy stop and a sell stop on the same symbol at once ("potential wash trade", seen on
    # 2026-11-18), so the bot watches the price itself until 12:00 and enters at market.
    s["mode"] = "watch"
    note(s, f"Līmeņi: pirkt virs {up:.2f}, pārdot zem {dn:.2f}, {qty} akcijas. Bots vēro cenu līdz 12:00.")
    s.update(open_done=True); save(s)
    watch(api, s)


def record_leftover(api, o, day):
    """Write the next-morning exit into the earlier day's state, so its journal shows the real result."""
    for _ in range(30):
        o = api.order(o["id"])
        if o.get("status") == "filled": break
        time.sleep(1)
    f = fill(o)
    days = sorted(x[:-5] for x in os.listdir(STATE_DIR) if x[:-5] < day and x.endswith(".json") and x[:4].isdigit())
    for d in reversed(days):
        prev = load(d)
        t = prev.get("trade")
        if t and not t.get("exit") and f:
            finish(prev, f[0], f[1], f"aizvērts {day} atvēršanā (slēgšanas palaišana nokavēja)")
            prev.update(close_done=True, done=True)
            note(prev, f"Pozīcija aizvērta {day} pie {f[0]:.2f}.")
            save(prev)
            return


def watch(api, s):
    """Poll the price until 12:00; on a level, enter at market, then protect the position with its stop."""
    day, end = s["day"], at(s["day"], ENTRY_END)
    while now() < end:
        p = api.latest_price(SYMBOL)
        side = 1 if p >= s["up"] else (-1 if p <= s["dn"] else 0)
        if side:
            o = api.market_order(SYMBOL, "buy" if side == 1 else "sell", s["qty"], f"W-{day}-entry")
            s["orders"] = {"entry": o["id"]}; save(s)
            for _ in range(60):
                o = api.order(o["id"])
                if o.get("status") == "filled": break
                time.sleep(1)
            f = fill(o)
            if f:
                s["trade"] = dict(side=side, entry=f[0], entry_time=f"{f[1]:%H:%M}", stop=s["dn"] if side == 1 else s["up"],
                                  qty=int(float(o["filled_qty"])), stop_order=None)
                note(s, f"Ieeja {'pirkt' if side == 1 else 'pārdot'} {s['trade']['qty']} pie {f[0]:.2f} (līmenis "
                        f"{s['up'] if side == 1 else s['dn']:.2f}).")
            protect(api, s)
            return
        time.sleep(POLL)


def protect(api, s):
    """Make the state match the broker and make sure an SPY position has its stop at Alpaca.
    Adopts a position the state does not know (e.g. after a crash), cancels stray SPY orders, places the stop,
    and closes at market if the price is already past the stop or Alpaca refuses the stop."""
    pos = api.position(SYMBOL)
    t = s["trade"]
    if not pos or float(pos["qty"]) == 0:
        return
    q = float(pos["qty"]); side = 1 if q > 0 else -1
    if not t or t.get("exit"):
        if s.get("up") is None:
            api.close_position(SYMBOL)
            note(s, "SPY pozīcija bez šodienas līmeņiem, aizvērta.")
            return
        s["trade"] = t = dict(side=side, entry=float(pos["avg_entry_price"]), entry_time=f"{now():%H:%M}",
                              stop=s["dn"] if side == 1 else s["up"], qty=int(abs(q)), stop_order=None)
        note(s, f"Brokerī atrasta pozīcija ({'pirkts' if side == 1 else 'pārdots'} {t['qty']} pie {t['entry']:.2f}), "
                f"pievienota šodienas darījumam.")
    t["qty"] = int(abs(q))
    need = "sell" if t["side"] == 1 else "buy"
    live = api.open_orders(SYMBOL)
    ok = [o for o in live if o["side"] == need and o["type"] == "stop" and int(float(o["qty"])) == t["qty"]]
    for o in live:
        if not ok or o["id"] != ok[0]["id"]:
            cancel_quiet(api, o["id"])
    if ok:
        t["stop_order"] = ok[0]["id"]
        return
    for _ in range(20):                                  # wait until the cancels have gone through
        if not api.open_orders(SYMBOL): break
        time.sleep(1)
    p = api.latest_price(SYMBOL)
    if (p - t["stop"]) * t["side"] <= 0:
        close_now(api, s, "cena jau aiz stopa")
        return
    try:
        so = api.stop_order(SYMBOL, need, t["qty"], t["stop"], f"W-{s['day']}-stop-{int(time.time())}")
        t["stop_order"] = so["id"]
        note(s, f"Stops brokerī pie {t['stop']:.2f}.")
    except ApiError as e:
        note(s, f"Alpaca nepieņēma stopu ({str(e)[:100]}). Pozīcija aizvērta drošības dēļ.")
        close_now(api, s, "stops netika pieņemts")


def phase_noon(api, s):
    day, end = s["day"], at(s["day"], ENTRY_END)
    sleep_until(end)
    if s["mode"] == "orders" and s["orders"]:
        o = {k: api.order(v) for k, v in s["orders"].items()}
        f = {k: fill(v) for k, v in o.items()}
        got = sorted([k for k in f if f[k]], key=lambda k: f[k][1])
        if not got:
            for v in s["orders"].values(): cancel_quiet(api, v)
            note(s, "Līdz 12:00 neviens līmenis netika aizsniegts. Orderi atcelti, darījuma nav.")
        else:
            k = got[0]; side = 1 if k == "buy" else -1; other = "sell" if k == "buy" else "buy"
            e, et = f[k]
            s["trade"] = dict(side=side, entry=e, entry_time=f"{et:%H:%M}", stop=s["dn"] if side == 1 else s["up"],
                              qty=int(float(o[k]["filled_qty"])), stop_order=s["orders"][other])
            if len(got) == 2:
                finish(s, *f[other], "stops")
            elif et >= end:                                  # Williams never enters after 12:00
                cancel_quiet(api, s["orders"][other])
                close_now(api, s, "ieeja pēc 12:00, aizvērts")
            else:
                note(s, f"Ieeja {e:.2f} {et:%H:%M}; otrs orderis tagad ir stops.")
    s.update(noon_done=True)


def finish(s, price, when, how):
    t = s["trade"]
    t.update(exit=price, exit_time=f"{when:%H:%M}", how=how)
    t["pnl"] = (price - t["entry"]) * t["side"] * t["qty"]
    t["R"] = (price - t["entry"]) * t["side"] / max(abs(t["entry"] - t["stop"]), 1e-9)


def close_now(api, s, how):
    t = s["trade"]
    if t.get("stop_order"):
        cancel_quiet(api, t["stop_order"])
    o = api.market_order(SYMBOL, "sell" if t["side"] == 1 else "buy", t["qty"], f"W-{s['day']}-exit")
    for _ in range(30):
        o = api.order(o["id"])
        if fill(o): break
        time.sleep(1)
    f = fill(o) or (api.latest_price(SYMBOL), now())
    finish(s, f[0], f[1], how)


def phase_close(api, s):
    day = s["day"]
    t = s["trade"]
    if not t or t.get("exit"):
        s.update(close_done=True); return
    close = at(day, s["close_time"])
    sleep_until(close - pd.Timedelta(minutes=2))          # the stop stays at the broker until 15:58
    so = api.order(t["stop_order"])
    if fill(so):
        finish(s, *fill(so), "stops")
        s.update(close_done=True); return
    if now() < close:
        cancel_quiet(api, t["stop_order"])
        so = api.order(t["stop_order"])
        if fill(so):                                         # filled while being cancelled
            finish(s, *fill(so), "stops")
        else:
            close_now(api, s, "slēgums")
        s.update(close_done=True); return
    note(s, "Bots palaists pēc slēguma: pozīcija paliek līdz rītdienas atvēršanai.")


def auto(api):
    day = now().date().isoformat()
    sess = session(api, day)
    if not sess:
        print(f"{day}: birža slēgta"); return
    s = load(day)
    s["close_time"] = sess[1]
    if s["done"]:
        print(f"{day}: jau pabeigts"); return
    t = now()
    early_close = sess[1] <= "14:00"
    try:
        if s["open_done"] and s.get("up") is not None and at(day, "09:31") <= t < at(day, s["close_time"]):
            protect(api, s); save(s)                         # every run first checks the account itself
        if not s["open_done"]:
            if t < at(day, "11:45"):
                phase_open(api, s); save(s); message(s)
            else:
                note(s, "Rīta palaišana nenotika (GitHub to neizpildīja laikā). Darījuma nav.")
                s.update(open_done=True, noon_done=True)
        if s["open_done"] and not s["noon_done"] and now() >= at(day, "11:45"):
            phase_noon(api, s); save(s)
            if not s["trade"]: message(s)
        if s["noon_done"] and not s["close_done"] and (now() >= at(day, "13:55") or early_close):
            phase_close(api, s); save(s)
            if s["trade"]: message(s)
        if s["open_done"] and s["noon_done"] and s["close_done"]:
            s["done"] = True
    finally:
        save(s)


def scan(api):
    day = now().date().isoformat()
    hi, lo = prior_range(api, day)
    m1 = finished_bars(api, day)
    o = float(m1.open.iloc[0]) if len(m1) else api.latest_price(SYMBOL)
    print(f"{day}: vakardiena {lo:.2f}-{hi:.2f}, atvēršana {o:.2f} -> pirkt virs {px(o + (hi - lo) / 2):.2f}, "
          f"pārdot zem {px(o - (hi - lo) / 2):.2f}" + ("" if len(m1) else " (pēc pēdējās cenas, tirgus vēl nav atvērts)"))


def status(api):
    """Read only: the SPY position and open SPY orders on the paper account."""
    a = api.account()
    print("account:", {k: a.get(k) for k in ("equity", "last_equity", "cash", "buying_power")})
    pos = api.position(SYMBOL)
    print("position:", {k: pos.get(k) for k in ("qty", "avg_entry_price", "current_price", "unrealized_pl")} if pos else None)
    for o in api.open_orders(SYMBOL):
        print("open order:", {k: o.get(k) for k in ("id", "side", "type", "qty", "stop_price", "status", "submitted_at")})
    for o in api._t(f"/v2/orders?status=closed&symbols={SYMBOL}&limit=10&after={now().date().isoformat()}T00:00:00Z"):
        print("today's closed order:", {k: o.get(k) for k in ("side", "type", "qty", "filled_qty", "filled_avg_price", "status", "filled_at")})


def probe(api):
    """Does Alpaca accept a buy stop and a sell stop for the same symbol at once? 1 share, 3 % away, then cancelled."""
    p = api.latest_price(SYMBOL)
    ids, res = [], []
    for side, k in (("buy", 1.03), ("sell", 0.97)):
        try:
            o = api.stop_order(SYMBOL, side, 1, p * k, f"W-probe-{side}-{int(time.time())}")
            ids.append(o["id"]); res.append(f"{side} stop accepted")
        except ApiError as e:
            res.append(f"{side} stop REJECTED: {str(e)[:150]}")
    time.sleep(3)
    for i in ids: cancel_quiet(api, i)
    txt = f"Williams probe {now():%Y-%m-%d %H:%M} NY, SPY {p:.2f}: " + "; ".join(res)
    os.makedirs(STATE_DIR, exist_ok=True)
    open(os.path.join(STATE_DIR, "probe.txt"), "w", encoding="utf-8").write(txt + "\n")
    if os.environ.get("MSG_FILE"):
        open(os.environ["MSG_FILE"], "w", encoding="utf-8").write(txt)
    print(txt)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    api = Alpaca()
    {"auto": auto, "scan": scan, "probe": probe, "status": status}[mode](api)
