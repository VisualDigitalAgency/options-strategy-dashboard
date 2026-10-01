"""Nifty 50 monthly ranges (issue #146), for the Level 6 "volatile month" gate.

The worker refreshes them once a day from yfinance (^NSEI) into Redis; requests only read the copy,
so opening the progress page never waits on yfinance. A month's swing is (high - low) / open.
"""

import logging
import time

import pandas as pd

from . import cache, data_fetch

log = logging.getLogger("theta.nifty")
KEY = "nifty:monthly"
REFRESH_EVERY = 24 * 3600
LOOKBACK_DAYS = 800  # a bit over two years: the longest gate window is 18 months


def months_from(hist: pd.DataFrame) -> dict[str, dict]:
    """{'YYYY-MM': {open, high, low, swing_pct}} from daily OHLC."""
    if isinstance(hist.columns, pd.MultiIndex):
        hist = hist.copy()
        hist.columns = hist.columns.get_level_values(0)
    out = {}
    for month, g in hist.dropna(subset=["Open", "High", "Low"]).groupby(hist.index.strftime("%Y-%m")):
        o, h, lo = float(g["Open"].iloc[0]), float(g["High"].max()), float(g["Low"].min())
        out[month] = {"open": o, "high": h, "low": lo, "swing_pct": round((h - lo) / o * 100, 2) if o else 0.0}
    return out


def refresh() -> dict:
    data = {"months": months_from(data_fetch.fetch_price_history("^NSEI", LOOKBACK_DAYS)), "fetched_at": time.time()}
    cache.set_json(KEY, data)
    return data


def due() -> bool:
    data = cache.get_json(KEY)
    return not data or time.time() - data.get("fetched_at", 0) > REFRESH_EVERY


def monthly() -> dict[str, dict]:
    """The cached months; empty until the worker's first refresh."""
    data = cache.get_json(KEY)
    return data["months"] if isinstance(data, dict) else {}
