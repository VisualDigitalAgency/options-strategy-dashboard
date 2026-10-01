"""Strategy builder (issue #137): what the builder page needs to let a user build their own
strategy on any Nifty 50 stock. Open to every account; ordering goes through va_preview_order /
va_place_order, where the buy-leg rule is enforced (virtual._buy_rule)."""

import pandas as pd

from . import cache, config, data_fetch, greeks_sr, market_calendar, virtual

EXPIRIES_TTL = 6 * 3600  # NSE lists new expiries once a month; one call per stock per 6 hours


def expiries(symbol: str) -> list[str]:
    key = f"expiries:{symbol}"
    hit = cache.get_json(key)
    if hit is None:
        hit = [str(e.date()) for e in data_fetch.fetch_expiries(symbol)]
        cache.set_json(key, hit, ttl=EXPIRIES_TTL)
    today = str(virtual._today().date())
    return sorted(e for e in hit if e >= today)


def _side(r, side: str, spot: float, dte: int) -> dict | None:
    ltp, bid, ask, iv = (float(r[f"{side}_{k}"]) for k in ("LTP", "BID", "ASK", "IV"))
    if ltp <= 0 and bid <= 0 and ask <= 0:
        return None
    delta = None
    if iv > 0:
        try:
            delta = round(greeks_sr.bs_delta(spot, float(r["strikePrice"]), max(dte, 1), iv, side), 4)
        except (ValueError, ZeroDivisionError):
            pass
    return {"ltp": ltp, "bid": bid, "ask": ask, "iv": iv, "oi": int(r[f"{side}_OI"]), "delta": delta}


def chain(symbol: str, expiry: str | None = None) -> dict:
    """The option chain for one stock and expiry (default: the first at least MIN_DTE days out),
    with each strike's delta, plus the lot size, the stock's results/dividend dates before expiry
    and the screening rules the page warns about (never blocks)."""
    exps = expiries(symbol)
    if not exps:
        raise ValueError(f"No open expiries for {symbol}")
    today = virtual._today()
    if expiry is None:
        expiry = next((e for e in exps if (pd.Timestamp(e) - today).days >= config.MIN_DTE), exps[-1])
    elif expiry not in exps:
        raise ValueError(f"{symbol} has no {expiry} expiry")
    spot, df = virtual._chain(symbol, expiry)
    dte = (pd.Timestamp(expiry) - today).days
    rows = []
    for _, r in df.reset_index().iterrows():
        ce, pe = _side(r, "CE", spot, dte), _side(r, "PE", spot, dte)
        if ce or pe:
            rows.append({"strike": float(r["strikePrice"]), "CE": ce, "PE": pe})
    events = market_calendar.events_until(market_calendar.load()["events"], symbol, str(today.date()), expiry)
    return {
        "symbol": symbol, "expiry": expiry, "expiries": exps, "spot": spot, "dte": dte,
        "lot_size": data_fetch.fetch_lot_size(symbol, pd.Timestamp(expiry)),
        "rows": sorted(rows, key=lambda x: x["strike"]),
        "events": [e for e in events if e["risky"]],
        "rules": {"min_dte": config.MIN_DTE, "delta_max_abs": config.DELTA_MAX_ABS,
                  "long_sl_pct": config.LONG_SL_PCT, "time_exit_dte": config.TIME_EXIT_DTE},
    }
