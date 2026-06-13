"""
forward_paper.py — live forward paper-trading log for the EMA30 daily trend.

Runs the validated trend strategy in PAPER (equal-weight, long-only) and records
a real-time equity track record to forward_log.csv. Two jobs:
  1. Operational check — confirms the live signals/data/accounting all work.
  2. Builds a genuine, timestamped LIVE track record you can later show on the
     proof panel ("live since <date>").

Run once a day, OR leave it running with --loop (it acts once per UTC day):
  python forward_paper.py            # record today's step
  python forward_paper.py --loop     # leave running; updates daily

State persists in forward_state.json; the log is forward_log.csv.
"""

import os
import csv
import sys
import json
import time
import datetime
import requests

MEXC = "https://contract.mexc.com"
EMA_PERIOD = 30
START_EQUITY = 10000.0
FEE = 0.0010
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "forward_state.json")
LOG = os.path.join(HERE, "forward_log.csv")

SYMBOLS = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "BNB_USDT", "XRP_USDT", "DOGE_USDT",
           "ADA_USDT", "AVAX_USDT", "LINK_USDT", "DOT_USDT", "LTC_USDT", "ATOM_USDT",
           "UNI_USDT", "NEAR_USDT", "APT_USDT"]


def fetch_daily(symbol, limit=120):
    try:
        d = requests.get(f"{MEXC}/api/v1/contract/kline/{symbol}",
                         params={"interval": "Day1", "limit": limit}, timeout=15).json().get("data", {})
        c = [float(x) for x in d.get("close", [])]
        return c
    except Exception:
        return []


def ema_last(values, period):
    if len(values) < period:
        return None
    k = 2/(period+1); e = sum(values[:period])/period
    for v in values[period:]:
        e = v*k + e*(1-k)
    return e


def signals_now():
    """Return {symbol: (direction, price)} for coins with enough data."""
    out = {}
    for s in SYMBOLS:
        c = fetch_daily(s)
        e = ema_last(c, EMA_PERIOD)
        if e is None or not c:
            continue
        out[s] = ("LONG" if c[-1] > e else "SHORT", c[-1])
    return out


def load_state():
    if os.path.exists(STATE):
        with open(STATE) as f:
            return json.load(f)
    return None


def save_state(st):
    with open(STATE, "w") as f:
        json.dump(st, f, indent=2)


def log_row(date, equity, since_pct, n_long, n_total):
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "equity", "since_start_%", "longs", "coins"])
        w.writerow([date, round(equity, 2), round(since_pct, 2), n_long, n_total])


def step():
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    sig = signals_now()
    if not sig:
        print("No data fetched — check connection."); return
    st = load_state()

    if st is None:
        positions = {s: (1 if d == "LONG" else 0) for s, (d, p) in sig.items()}
        prices = {s: p for s, (d, p) in sig.items()}
        st = {"start_date": today, "last_date": today, "equity": START_EQUITY,
              "positions": positions, "prices": prices}
        save_state(st)
        n_long = sum(positions.values())
        log_row(today, START_EQUITY, 0.0, n_long, len(positions))
        print(f"[{today}] STARTED forward paper @ ${START_EQUITY:.0f} | "
              f"{n_long}/{len(positions)} coins LONG")
        return

    if st["last_date"] == today:
        print(f"[{today}] already recorded today. equity ${st['equity']:.2f} "
              f"({(st['equity']/START_EQUITY-1)*100:+.2f}% since {st['start_date']})")
        return

    # advance one day: earn yesterday's positions, then rebalance to new signals
    rets = []
    for s, (d, price) in sig.items():
        prev_price = st["prices"].get(s)
        pos_prev = st["positions"].get(s, 0)
        if prev_price:
            r = (price - prev_price) / prev_price
            rets.append(pos_prev * r)
    port_ret = sum(rets) / len(rets) if rets else 0.0
    st["equity"] *= (1 + port_ret)

    new_pos = {s: (1 if d == "LONG" else 0) for s, (d, p) in sig.items()}
    # fee on coins whose position changed (approx, equal-weight)
    changed = sum(1 for s in new_pos if new_pos[s] != st["positions"].get(s, 0))
    if changed:
        st["equity"] *= (1 - FEE * changed / max(1, len(new_pos)))
    st["positions"] = new_pos
    st["prices"] = {s: p for s, (d, p) in sig.items()}
    st["last_date"] = today
    save_state(st)

    since = (st["equity"]/START_EQUITY - 1) * 100
    n_long = sum(new_pos.values())
    log_row(today, st["equity"], since, n_long, len(new_pos))
    print(f"[{today}] equity ${st['equity']:.2f} ({since:+.2f}% since {st['start_date']}) | "
          f"{n_long}/{len(new_pos)} LONG | day {port_ret*100:+.2f}%")


def main():
    if "--loop" in sys.argv:
        print("Forward paper running (--loop). Updates once per UTC day. Ctrl+C to stop.")
        while True:
            try:
                step()
            except Exception as e:
                print("error:", e)
            time.sleep(3600)
    else:
        step()


if __name__ == "__main__":
    main()
