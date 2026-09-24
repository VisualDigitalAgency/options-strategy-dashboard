"""Applies the full rule set to one symbol and returns an actionable recommendation."""

from datetime import timedelta

import numpy as np
import pandas as pd

from . import config, data_fetch, filters, greeks_sr, span

LIQUIDITY_MIN_OI = 500
LIQUIDITY_MAX_SPREAD_PCT = 10


def _check(checks: list, rule: str, status: str, detail: str):
    checks.append({"rule": rule, "status": status, "detail": detail})


def _pick_leg(chain: pd.DataFrame, spot: float, dte: int, side: str) -> dict | None:
    """Highest-OI OTM strike on this side whose |delta| < DELTA_MAX_ABS."""
    otm = chain[chain["strikePrice"] > spot] if side == "CE" else chain[chain["strikePrice"] < spot]
    otm = otm.copy()
    oi_col, ltp_col, iv_col = f"{side}_OI", f"{side}_LTP", f"{side}_IV"
    otm = otm[(otm[oi_col] > 0) & (otm[ltp_col] > 0) & (otm[iv_col] > 0)]
    if otm.empty:
        return None

    otm["delta"] = otm.apply(
        lambda r: greeks_sr.bs_delta(spot, r["strikePrice"], dte, r[iv_col], side), axis=1
    )
    eligible = otm[otm["delta"].abs() < config.DELTA_MAX_ABS]
    if eligible.empty:
        return None

    best = eligible.loc[eligible[oi_col].idxmax()]
    strike, iv = float(best["strikePrice"]), float(best[iv_col])
    g = greeks_sr.bs_greeks(spot, strike, dte, iv, side)
    p_below = greeks_sr.prob_below(spot, strike, dte, iv)
    p_beyond = (1 - p_below) if side == "CE" else p_below
    return {
        "side": side,
        "strike": strike,
        "premium": float(best[ltp_col]),
        "bid": float(best[f"{side}_BID"]),
        "ask": float(best[f"{side}_ASK"]),
        "iv": iv,
        "oi": int(best[oi_col]),
        "oi_change": int(best[f"{side}_OI_CHG"]),
        **g,
        "prob_itm": round(p_beyond * 100, 1),
        # Reflection principle: chance of touching the strike before expiry is ~2x finishing past it.
        "prob_touch": round(min(1.0, 2 * p_beyond) * 100, 1),
        "distance_pct": round((strike - spot) / spot * 100, 2),
    }


def _exposure_pct(price_hist: pd.DataFrame) -> float:
    closes = price_hist["Close"].dropna()
    sigma = float(np.log(closes / closes.shift(1)).dropna().std()) * 100 if len(closes) > 20 else 0.0
    return round(max(config.EXPOSURE_MIN_PCT, config.EXPOSURE_SIGMA_MULT * sigma), 2)


def _strategy(symbol: str, legs: list[dict], spot: float, dte: int, expiry: pd.Timestamp,
              lot: int | None, exposure_pct: float) -> dict:
    ce = next((l for l in legs if l["side"] == "CE"), None)
    pe = next((l for l in legs if l["side"] == "PE"), None)
    credit = sum(l["premium"] for l in legs)

    upper = ce["strike"] + credit if ce else None
    lower = pe["strike"] - credit if pe else None
    p_up_be = greeks_sr.prob_below(spot, upper, dte, ce["iv"]) if ce else 1.0
    p_low_be = greeks_sr.prob_below(spot, lower, dte, pe["iv"]) if pe else 0.0
    p_up_k = greeks_sr.prob_below(spot, ce["strike"], dte, ce["iv"]) if ce else 1.0
    p_low_k = greeks_sr.prob_below(spot, pe["strike"], dte, pe["iv"]) if pe else 0.0

    out = {
        "credit_per_share": round(credit, 2),
        "breakeven_lower": round(lower, 2) if lower else None,
        "breakeven_upper": round(upper, 2) if upper else None,
        "pop": round((p_up_be - p_low_be) * 100, 1),
        "max_profit_prob": round((p_up_k - p_low_k) * 100, 1),
        "lot_size": lot,
        "exposure_pct": exposure_pct,
    }
    # Short position Greeks per share = negative of long Greeks
    for g in ("delta", "gamma", "theta", "vega"):
        out[f"net_{g}"] = round(-sum(l[g] for l in legs), 5)

    if lot:
        span_amt = span.scan_risk(symbol, expiry.strftime("%Y%m%d"), legs, lot)
        exposure = sum(spot * lot * exposure_pct / 100 for _ in legs)
        out["max_profit"] = round(credit * lot, 2)
        out["span"] = span_amt
        out["exposure"] = round(exposure, 2)
        if span_amt is not None:
            margin = span_amt + exposure
            out["margin"] = round(margin, 2)
            out["roi_pct"] = round(credit * lot / margin * 100, 2) if margin else None
            out["roi_annual_pct"] = round(out["roi_pct"] * 365 / dte, 1) if out["roi_pct"] and dte else None
    return out


def evaluate_symbol(symbol: str, yf_symbol: str, today: pd.Timestamp | None = None,
                    price_hist: pd.DataFrame | None = None) -> dict:
    today = today or pd.Timestamp.today().normalize()
    checks: list = []
    result = {"symbol": symbol, "action": "SKIP", "checks": checks, "legs": []}

    expiry = filters.nearest_valid_expiry(data_fetch.fetch_expiries(symbol), today)
    if expiry is None:
        _check(checks, "Expiry", "fail", f"No expiry with {config.MIN_DTE}+ days left")
        return result
    dte = (expiry - today).days
    result.update(expiry=expiry.strftime("%Y-%m-%d"), dte=dte)
    _check(checks, "Expiry", "pass", f"{expiry:%d %b %Y}, {dte} days out (min {config.MIN_DTE})")

    raw = data_fetch.fetch_option_chain(symbol, expiry)
    spot = data_fetch.get_spot_price(raw)
    chain = data_fetch.normalize_option_chain(raw)
    result["spot"] = spot
    if chain.empty:
        _check(checks, "Option chain", "fail", "NSE returned no option chain data")
        return result

    max_pain = greeks_sr.compute_max_pain(chain)
    result["max_pain"] = max_pain
    result["lot_size"] = data_fetch.fetch_lot_size(symbol, expiry)

    if price_hist is None or price_hist.empty:
        price_hist = data_fetch.fetch_price_history(yf_symbol, config.SR_LOOKBACK_DAYS)
    if isinstance(price_hist.columns, pd.MultiIndex):
        price_hist.columns = price_hist.columns.get_level_values(0)
    result["sentiment"] = greeks_sr.compute_sentiment(price_hist, spot, chain)
    result["history"] = [
        {"date": d.strftime("%Y-%m-%d"), "close": round(float(c), 2)}
        for d, c in price_hist["Close"].dropna().items()
    ]
    near = chain[(chain["strikePrice"] > spot * 0.75) & (chain["strikePrice"] < spot * 1.25)]
    result["chain"] = near[["strikePrice", "CE_OI", "PE_OI", "CE_OI_CHG", "PE_OI_CHG",
                            "CE_LTP", "PE_LTP", "CE_BID", "PE_BID", "CE_IV", "PE_IV"]].to_dict("records")

    zones = greeks_sr.find_swing_sr_zones(price_hist)
    # Role flips with price: an old swing low above spot now acts as resistance, and vice versa.
    for z in zones:
        z["type"] = "resistance" if z["level"] > spot else "support"
    result["sr_zones"] = zones

    pcr = filters.compute_pcr(chain)
    result["pcr"] = pcr
    if not filters.pcr_in_range(pcr):
        _check(checks, "PCR filter", "fail", f"PCR {pcr} is outside {config.PCR_MIN}-{config.PCR_MAX}")
        return result
    _check(checks, "PCR filter", "pass", f"PCR {pcr} is inside {config.PCR_MIN}-{config.PCR_MAX}")

    legs = []
    for side in ("CE", "PE"):
        leg = _pick_leg(chain, spot, dte, side)
        if leg is None:
            _check(checks, f"{side} strike", "fail", f"No OTM strike with |delta| below {config.DELTA_MAX_ABS}")
            continue
        _check(checks, f"{side} strike", "pass",
               f"{leg['strike']:.0f} has the highest OI ({leg['oi']:,}) with delta {leg['delta']:.3f}")
        zone = greeks_sr.strike_in_sr_zone(leg["strike"], zones)
        if zone:
            _check(checks, f"{side} S/R", "fail",
                   f"{leg['strike']:.0f} sits in {zone['type']} zone ~{zone['level']:.0f} "
                   f"({zone['touches']} touches), leg dropped")
            continue
        _check(checks, f"{side} S/R", "pass", f"{leg['strike']:.0f} is clear of all S/R zones")
        spread_pct = (leg["ask"] - leg["bid"]) / leg["premium"] * 100 if leg["premium"] else 0
        if leg["oi"] < LIQUIDITY_MIN_OI or spread_pct > LIQUIDITY_MAX_SPREAD_PCT:
            _check(checks, f"{side} liquidity", "warn",
                   f"OI {leg['oi']:,}, bid-ask spread {spread_pct:.0f}% of premium; fills may slip")
        leg["max_pain_distance_pct"] = round((leg["strike"] - max_pain) / max_pain * 100, 2)
        legs.append(leg)

    result["legs"] = legs
    if not legs:
        return result

    result["action"] = "SELL STRANGLE" if len(legs) == 2 else f"SELL {legs[0]['side']} ONLY"
    _check(checks, "Max pain", "info",
           f"Max pain {max_pain:.0f} is {((max_pain - spot) / spot * 100):+.1f}% from spot")

    mood = result["sentiment"]["label"]
    if len(legs) == 1:
        side = legs[0]["side"]
        against = (mood == "Bullish" and side == "CE") or (mood == "Bearish" and side == "PE")
        _check(checks, "Sentiment fit", "warn" if against else "pass",
               f"Selling {side} only {'runs against' if against else 'fits'} {mood.lower()} sentiment")
    else:
        _check(checks, "Sentiment fit", "info", f"Strangle is direction-neutral; sentiment is {mood.lower()}")

    result["strategy"] = _strategy(symbol, legs, spot, dte, expiry, result["lot_size"], _exposure_pct(price_hist))
    if result["lot_size"] is None:
        _check(checks, "Margin", "warn", "Lot size not found in NSE lot file; margin unavailable")
    elif result["strategy"].get("span") is None:
        _check(checks, "Margin", "warn", "Contract missing from NSE SPAN file; margin unavailable")

    result["sl"] = {
        "entry": today.strftime("%Y-%m-%d"),
        "activates_on": (today + timedelta(days=config.SL_GRACE_DAYS)).strftime("%Y-%m-%d"),
        "expiry": result["expiry"],
        "levels": {l["side"]: l["premium"] for l in legs},
    }
    return result


def get_universe() -> list[str]:
    try:
        symbols = data_fetch.fetch_nifty50_symbols(config.NIFTY50_CSV_URL)
        if len(symbols) >= 45:
            return symbols
    except Exception:
        pass
    return config.NIFTY50_FALLBACK


def safe_evaluate(symbol: str, price_hist: pd.DataFrame | None = None) -> dict:
    try:
        return evaluate_symbol(symbol, f"{symbol}.NS", price_hist=price_hist)
    except Exception as e:  # one bad symbol shouldn't kill the whole screen
        return {"symbol": symbol, "action": "ERROR", "legs": [],
                "checks": [{"rule": "Data", "status": "fail", "detail": str(e)}]}
