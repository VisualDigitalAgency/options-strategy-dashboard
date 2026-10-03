"""Strategy builder (issue #137): what the builder page needs to let a user build their own
strategy on any Nifty 50 stock. Open to every account; ordering goes through va_preview_order /
va_place_order, where the buy-leg rule is enforced (virtual._buy_rule)."""

from datetime import datetime

import pandas as pd

from . import cache, config, data_fetch, eod, greeks_sr, market_calendar, pivots, virtual

EXPIRIES_TTL = 6 * 3600  # NSE lists new expiries once a month; one call per stock per 6 hours


def expiries(symbol: str) -> list[str]:
    key = f"expiries:{symbol}"
    hit = [str(e.date()) for e in eod.expiries(symbol)] if virtual.eod_mode() else cache.get_json(key)
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
    chg, pchg = r.get(f"{side}_OI_CHG"), r.get(f"{side}_PCHG")
    return {"ltp": ltp, "bid": bid, "ask": ask, "iv": iv, "oi": int(r[f"{side}_OI"]),
            "oi_chg": None if chg is None or pd.isna(chg) else int(chg),
            # Last traded price vs yesterday's close, % (#156); null when NSE doesn't send it.
            "pchg": None if pchg is None or pd.isna(pchg) else round(float(pchg), 2), "delta": delta}


def _summary(df: pd.DataFrame, spot: float, rows: list[dict]) -> dict:
    """The chain footer (#158): put/call OI ratio, max pain and the ATM strike's IV (the mean of the
    call and put IV that are quoted)."""
    ce_oi, pe_oi = float(df["CE_OI"].sum()), float(df["PE_OI"].sum())
    try:
        pain = greeks_sr.compute_max_pain(df.reset_index())
    except (KeyError, ValueError):
        pain = None
    atm = min(rows, key=lambda r: abs(r["strike"] - spot)) if rows else None
    ivs = [atm[s]["iv"] for s in ("CE", "PE") if atm and atm[s] and atm[s]["iv"] > 0]
    return {"pcr": round(pe_oi / ce_oi, 2) if ce_oi else None, "max_pain": pain,
            "atm_strike": atm["strike"] if atm else None, "atm_iv": round(sum(ivs) / len(ivs), 2) if ivs else None}


def chain(symbol: str, expiry: str | None = None) -> dict:
    """The option chain for one stock and expiry (default: the first at least MIN_DTE days out),
    with each strike's delta, plus the lot size, the stock's results/dividend dates before expiry
    and the screening rules the page warns about (never blocks)."""
    exps = expiries(symbol)
    today = virtual._today()
    if expiry is None:
        expiry = chain_expiry(symbol)
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
        "summary": _summary(df, spot, rows),
        "symbol": symbol, "expiry": expiry, "expiries": exps, "spot": spot, "dte": dte,
        "lot_size": virtual.lot_size(symbol, expiry), "as_of": virtual.as_of(),
        "rows": sorted(rows, key=lambda x: x["strike"]),
        "events": [e for e in events if e["risky"]],
        "rules": {"min_dte": config.MIN_DTE, "delta_max_abs": config.DELTA_MAX_ABS,
                  "long_sl_pct": config.LONG_SL_PCT, "time_exit_dte": config.TIME_EXIT_DTE},
    }


def levels(symbol: str) -> dict:
    """Price levels the builder draws on its payoff chart and checks short strikes against: last
    month's floor pivots and the swing support/resistance zones the screener uses. Shares the
    pivots cache (one yfinance call per stock per session)."""
    data = pivots.for_symbol(symbol, datetime.fromisoformat(virtual._valid_until()).date())
    hist = pd.DataFrame(data["history"]).rename(columns={"high": "High", "low": "Low", "close": "Close"})
    zones = greeks_sr.find_swing_sr_zones(hist) if not hist.empty else []
    last = data["history"][-1]["close"] if data["history"] else None
    for z in zones:  # role flips with price, as in the screener (last close stands in for spot)
        z["type"] = "resistance" if last is not None and z["level"] > last else "support"
    monthly = data["pivots"].get("monthly")
    return {"symbol": symbol, "pivots": monthly["levels"] if monthly else {}, "zones": zones,
            "zone_width_pct": config.SR_ZONE_WIDTH_PCT}


def chain_expiry(symbol: str) -> str:
    """The builder's default expiry: the first at least MIN_DTE days out (else the last one)."""
    exps = expiries(symbol)
    if not exps:
        raise ValueError(f"No open expiries for {symbol}")
    today = virtual._today()
    return next((e for e in exps if (pd.Timestamp(e) - today).days >= config.MIN_DTE), exps[-1])
