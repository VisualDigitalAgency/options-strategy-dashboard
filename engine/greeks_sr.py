"""Black-Scholes delta, Max Pain, and swing-based support/resistance."""

import math
from datetime import datetime

import numpy as np
import pandas as pd

from . import config


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_delta(spot: float, strike: float, dte_days: int, iv_pct: float, option_type: str) -> float:
    """Black-Scholes delta. iv_pct is IV as a percentage (e.g. NSE gives 18.5 for 18.5%)."""
    if dte_days <= 0 or iv_pct <= 0 or spot <= 0 or strike <= 0:
        return 0.0
    t = dte_days / 365.0
    sigma = iv_pct / 100.0
    r = config.RISK_FREE_RATE
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma ** 2) * t) / (sigma * math.sqrt(t))
    if option_type == "CE":
        return round(_norm_cdf(d1), 4)
    return round(_norm_cdf(d1) - 1.0, 4)


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def bs_greeks(spot: float, strike: float, dte_days: int, iv_pct: float, option_type: str) -> dict:
    """Per-share Greeks for a LONG option. Theta is per calendar day, vega per 1 IV point."""
    if dte_days <= 0 or iv_pct <= 0:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    t, sigma, r = dte_days / 365.0, iv_pct / 100.0, config.RISK_FREE_RATE
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma ** 2) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    gamma = _norm_pdf(d1) / (spot * sigma * math.sqrt(t))
    vega = spot * _norm_pdf(d1) * math.sqrt(t) / 100
    decay = -spot * _norm_pdf(d1) * sigma / (2 * math.sqrt(t))
    if option_type == "CE":
        delta = _norm_cdf(d1)
        theta = (decay - r * strike * math.exp(-r * t) * _norm_cdf(d2)) / 365
    else:
        delta = _norm_cdf(d1) - 1
        theta = (decay + r * strike * math.exp(-r * t) * _norm_cdf(-d2)) / 365
    return {"delta": round(delta, 4), "gamma": round(gamma, 5), "theta": round(theta, 3), "vega": round(vega, 3)}


def prob_below(spot: float, level: float, dte_days: int, iv_pct: float) -> float:
    """Risk-neutral lognormal P(price at expiry < level)."""
    if level <= 0:
        return 0.0
    t, sigma, r = dte_days / 365.0, iv_pct / 100.0, config.RISK_FREE_RATE
    d2 = (math.log(spot / level) + (r - 0.5 * sigma ** 2) * t) / (sigma * math.sqrt(t))
    return _norm_cdf(-d2)


def compute_max_pain(chain_df: pd.DataFrame) -> float:
    """Strike where total option-writer payout is minimized (classic Max Pain)."""
    strikes = chain_df["strikePrice"].values
    pain = []
    for s in strikes:
        ce_loss = np.sum(np.maximum(0, s - chain_df["strikePrice"]) * chain_df["CE_OI"])
        pe_loss = np.sum(np.maximum(0, chain_df["strikePrice"] - s) * chain_df["PE_OI"])
        pain.append(ce_loss + pe_loss)
    return float(strikes[int(np.argmin(pain))])


def top_oi_strike(chain_df: pd.DataFrame, side: str) -> float:
    col = "CE_OI" if side == "CE" else "PE_OI"
    return float(chain_df.loc[chain_df[col].idxmax(), "strikePrice"])


def find_swing_sr_zones(price_df: pd.DataFrame) -> list[dict]:
    """5-candle fractal swing highs/lows, clustered into zones with 2+ touches.

    Returns list of {"level": float, "type": "support"|"resistance", "touches": int}
    """
    if price_df.empty or len(price_df) < (2 * config.SR_FRACTAL_N + 1):
        return []

    highs = price_df["High"].values
    lows = price_df["Low"].values
    n = config.SR_FRACTAL_N

    swing_highs, swing_lows = [], []
    for i in range(n, len(price_df) - n):
        window_h = highs[i - n : i + n + 1]
        window_l = lows[i - n : i + n + 1]
        if highs[i] == window_h.max():
            swing_highs.append(float(highs[i]))
        if lows[i] == window_l.min():
            swing_lows.append(float(lows[i]))

    def cluster(points: list[float], kind: str) -> list[dict]:
        if not points:
            return []
        points = sorted(points)
        zones = []
        current = [points[0]]
        for p in points[1:]:
            if abs(p - current[-1]) / current[-1] * 100 <= config.SR_ZONE_WIDTH_PCT:
                current.append(p)
            else:
                zones.append(current)
                current = [p]
        zones.append(current)
        return [
            {"level": round(sum(z) / len(z), 2), "type": kind, "touches": len(z)}
            for z in zones
            if len(z) >= config.SR_MIN_TOUCHES
        ]

    return cluster(swing_highs, "resistance") + cluster(swing_lows, "support")


def compute_sentiment(price_df: pd.DataFrame, spot: float, chain_df: pd.DataFrame) -> dict:
    """Two-signal score: moving-average trend + today's PE vs CE OI change."""
    signals = []
    score = 0

    closes = price_df["Close"]
    if len(closes) >= 50:
        ma20, ma50 = float(closes.tail(20).mean()), float(closes.tail(50).mean())
        if spot > ma20 > ma50:
            score += 1
            signals.append(f"Uptrend: spot {spot:.0f} > 20DMA {ma20:.0f} > 50DMA {ma50:.0f}")
        elif spot < ma20 < ma50:
            score -= 1
            signals.append(f"Downtrend: spot {spot:.0f} < 20DMA {ma20:.0f} < 50DMA {ma50:.0f}")
        else:
            signals.append(f"No clear trend: 20DMA {ma20:.0f}, 50DMA {ma50:.0f}")

    pe_chg, ce_chg = float(chain_df["PE_OI_CHG"].sum()), float(chain_df["CE_OI_CHG"].sum())
    denom = abs(pe_chg) + abs(ce_chg)
    if denom > 0:
        bias = (pe_chg - ce_chg) / denom
        if bias > config.SENTIMENT_OI_BIAS:
            score += 1
            signals.append(f"Put writing dominant today (PE OI +{pe_chg:.0f} vs CE {ce_chg:+.0f})")
        elif bias < -config.SENTIMENT_OI_BIAS:
            score -= 1
            signals.append(f"Call writing dominant today (CE OI +{ce_chg:.0f} vs PE {pe_chg:+.0f})")
        else:
            signals.append(f"Balanced OI change (PE {pe_chg:+.0f}, CE {ce_chg:+.0f})")

    label = "Bullish" if score >= 1 else "Bearish" if score <= -1 else "Neutral"
    return {"label": label, "score": score, "signals": signals}


def strike_in_sr_zone(strike: float, zones: list[dict]) -> dict | None:
    """Returns the zone dict if strike falls within any zone's width, else None."""
    for z in zones:
        if abs(strike - z["level"]) / z["level"] * 100 <= config.SR_ZONE_WIDTH_PCT:
            return z
    return None
