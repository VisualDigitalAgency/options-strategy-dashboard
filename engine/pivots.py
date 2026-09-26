"""Classic floor pivots (P, R1-R4, S1-S4) from the last completed day, week and month.

Traditional formulas, as most charting platforms use them:
    P  = (H + L + C) / 3
    R1 = 2P - L          S1 = 2P - H
    R2 = P + (H - L)     S2 = P - (H - L)
    R3 = H + 2(P - L)    S3 = L - 2(H - P)
    R4 = 3P + H - 3L     S4 = 3P - 3H + L
"""
from datetime import date, timedelta

import pandas as pd

from . import cache, config, data_fetch

TTL = 30 * 60  # pivots move once a session; this only saves yfinance calls between page loads
PERIODS = ("daily", "weekly", "monthly")


def levels(h: float, l: float, c: float) -> dict:
    p = (h + l + c) / 3
    lv = {"P": p, "R1": 2 * p - l, "S1": 2 * p - h, "R2": p + (h - l), "S2": p - (h - l),
          "R3": h + 2 * (p - l), "S3": l - 2 * (h - p), "R4": 3 * p + h - 3 * l, "S4": 3 * p - 3 * h + l}
    return {k: round(v, 2) for k, v in lv.items()}


def _period_start(day: date, period: str) -> date:
    if period == "daily":
        return day
    if period == "weekly":
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


def compute(hist: pd.DataFrame, session: date) -> dict:
    """Pivots for `session` (the next or current trading day) from the period before the one it is
    in. `hist` is daily OHLC indexed by date. A bar for `session` itself is still forming, so it is
    never used."""
    done = hist[[d.date() < _period_start(session, "daily") for d in hist.index]]
    out = {}
    for period in PERIODS:
        bars = done[[d.date() < _period_start(session, period) for d in done.index]]
        if bars.empty:
            continue
        last = bars.index[-1].date()
        start = _period_start(last, period)
        span = bars[[d.date() >= start for d in bars.index]]
        h, l, c = float(span["High"].max()), float(span["Low"].min()), float(span["Close"].iloc[-1])
        out[period] = {"from": start.isoformat(), "to": last.isoformat(),
                       "high": round(h, 2), "low": round(l, 2), "close": round(c, 2), "levels": levels(h, l, c)}
    return out


def for_symbol(symbol: str, session: date) -> dict:
    """6 months of daily closes plus pivots, cached in Redis for all users."""
    key = f"pivots:{symbol}:{session.isoformat()}"
    hit = cache.get_json(key)
    if hit:
        return hit
    hist = data_fetch.fetch_price_history(f"{symbol}.NS", config.SR_LOOKBACK_DAYS)
    if isinstance(hist.columns, pd.MultiIndex):
        hist.columns = hist.columns.get_level_values(0)
    hist = hist.dropna(subset=["High", "Low", "Close"])
    if hist.empty:
        raise ValueError(f"Price history for {symbol} isn't available right now. Try again in a minute")
    out = {
        "symbol": symbol, "session": session.isoformat(),
        "history": [{"date": d.strftime("%Y-%m-%d"), "close": round(float(r["Close"]), 2),
                     "high": round(float(r["High"]), 2), "low": round(float(r["Low"]), 2)}
                    for d, r in hist.iterrows()],
        "pivots": compute(hist, session),
    }
    cache.set_json(key, out, ttl=TTL)
    return out
