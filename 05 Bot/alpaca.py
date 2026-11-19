"""Small Alpaca client. Paper only: it refuses to start on any other URL."""
import json, os, ssl, time, urllib.error, urllib.parse, urllib.request
import pandas as pd
import truststore

ENV_FILE = r"C:\Users\User\alpaca-paper.env"
PAPER_URL = "https://paper-api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets/v2/stocks"
_CTX = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


class ApiError(Exception):
    pass


class Alpaca:
    def __init__(self, env_file=ENV_FILE):
        keys = ("ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ALPACA_BASE_URL")
        if all(os.environ.get(k) for k in keys):        # in the cloud the keys come from GitHub secrets
            env = {k: os.environ[k].strip() for k in keys}
        else:
            env = {}
            for line in open(env_file, encoding="utf-8-sig"):
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    env[k.strip()] = v.strip()
        if env.get("ALPACA_BASE_URL") != PAPER_URL:
            raise SystemExit("Not the paper trading URL. Refusing to start.")
        self.h = {"APCA-API-KEY-ID": env["ALPACA_API_KEY"], "APCA-API-SECRET-KEY": env["ALPACA_SECRET_KEY"],
                  "Content-Type": "application/json"}
        if not self.account()["account_number"].startswith("PA"):
            raise SystemExit("Not a paper account. Refusing to start.")

    def _req(self, method, url, body=None):
        data = json.dumps(body).encode() if body is not None else None
        last = None
        # Only reads repeat: a repeated POST could place the same order twice.
        for attempt in range(4 if method == "GET" else 1):
            try:
                req = urllib.request.Request(url, data=data, headers=self.h, method=method)
                with urllib.request.urlopen(req, timeout=20, context=_CTX) as r:
                    raw = r.read()
                return json.loads(raw) if raw else None
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code} {e.read()[:300].decode('utf-8', 'replace')}"
                if e.code < 500 and e.code != 429:
                    break
            except OSError as e:
                last = str(e)[:300]
            time.sleep(2 * (attempt + 1))
        raise ApiError(f"{method} {url.split('?')[0]}: {last}")

    def _t(self, path, method="GET", body=None):
        return self._req(method, PAPER_URL + path, body)

    def account(self): return self._t("/v2/account")
    def clock(self): return self._t("/v2/clock")
    def calendar(self, day): return self._t(f"/v2/calendar?start={day}&end={day}")
    def order(self, oid): return self._t(f"/v2/orders/{oid}?nested=true")
    def cancel(self, oid): return self._t(f"/v2/orders/{oid}", "DELETE")
    def move_stop(self, oid, stop): return self._t(f"/v2/orders/{oid}", "PATCH", {"stop_price": f"{stop:.2f}"})

    def position_qty(self, symbol):
        try:
            return abs(float(self._t(f"/v2/positions/{symbol}")["qty"]))
        except ApiError as e:
            if "HTTP 404" in str(e):
                return 0.0
            raise

    def flatten(self):
        """Cancel every order and close every position."""
        return self._t("/v2/positions?cancel_orders=true", "DELETE")

    def bracket(self, symbol, side, qty, limit, tp, sl, client_id):
        body = {"symbol": symbol, "qty": str(qty), "side": side, "time_in_force": "day",
                "order_class": "bracket", "client_order_id": client_id,
                "take_profit": {"limit_price": f"{tp:.2f}"}, "stop_loss": {"stop_price": f"{sl:.2f}"}}
        if limit is None:
            body["type"] = "market"
        else:
            body.update(type="limit", limit_price=f"{limit:.2f}")
        return self._t("/v2/orders", "POST", body)

    # --- used by williams_bot.py ---
    def calendar_range(self, start, end): return self._t(f"/v2/calendar?start={start}&end={end}")
    def close_position(self, symbol): return self._t(f"/v2/positions/{symbol}", "DELETE")
    def open_orders(self, symbol): return self._t(f"/v2/orders?status=open&symbols={symbol}&limit=100")

    def position(self, symbol):
        """The position dict, or None when there is none."""
        try:
            return self._t(f"/v2/positions/{symbol}")
        except ApiError as e:
            if "HTTP 404" in str(e):
                return None
            raise

    def stop_order(self, symbol, side, qty, stop, client_id):
        return self._t("/v2/orders", "POST", {"symbol": symbol, "qty": str(qty), "side": side, "type": "stop",
                                              "stop_price": f"{stop:.2f}", "time_in_force": "day",
                                              "client_order_id": client_id})

    def market_order(self, symbol, side, qty, client_id, tif="day"):
        """tif "cls" = market-on-close (Alpaca accepts it until 15:50 New York)."""
        return self._t("/v2/orders", "POST", {"symbol": symbol, "qty": str(qty), "side": side, "type": "market",
                                              "time_in_force": tif, "client_order_id": client_id})

    def latest_price(self, symbol, feed="iex"):
        return float(self._req("GET", f"{DATA_URL}/{symbol}/trades/latest?feed={feed}")["trade"]["p"])

    def bars(self, symbol, tf, start, end=None, feed="iex"):
        q = {"timeframe": tf, "feed": feed, "limit": 10000, "adjustment": "raw", "sort": "asc",
             "start": pd.Timestamp(start).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")}
        if end is not None:
            q["end"] = pd.Timestamp(end).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = []
        while True:
            r = self._req("GET", f"{DATA_URL}/{symbol}/bars?" + urllib.parse.urlencode(q))
            rows += r.get("bars") or []
            if not r.get("next_page_token"):
                break
            q["page_token"] = r["next_page_token"]
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close"],
                                index=pd.DatetimeIndex([], tz="America/New_York"))
        df = pd.DataFrame(rows).rename(columns={"o": "open", "h": "high", "l": "low", "c": "close"})
        df.index = pd.to_datetime(df.t, utc=True).dt.tz_convert("America/New_York")
        df.index.name = None
        return df[["open", "high", "low", "close"]].astype(float)
