"""Universe and PCR/expiry filters."""

import pandas as pd
from . import config


def compute_pcr(chain_df: pd.DataFrame) -> float:
    """Put-Call Ratio by OI, summed across all strikes for the chosen expiry."""
    total_ce_oi = chain_df["CE_OI"].sum()
    total_pe_oi = chain_df["PE_OI"].sum()
    if total_ce_oi == 0:
        return float("inf")
    return round(total_pe_oi / total_ce_oi, 3)


def pcr_in_range(pcr: float) -> bool:
    return config.PCR_MIN <= pcr <= config.PCR_MAX


def eligible_expiries(expiries: list[pd.Timestamp], today: pd.Timestamp, min_dte: int, max_dte: int,
                      limit: int) -> list[pd.Timestamp]:
    """Every expiry with min_dte <= days out <= max_dte, nearest first, at most `limit` of them."""
    out = []
    for exp in sorted(expiries):
        dte = (exp - today).days
        if dte > max_dte or len(out) >= limit:
            break
        if dte >= min_dte:
            out.append(exp)
    return out


def nearest_valid_expiry(expiries: list[pd.Timestamp], today: pd.Timestamp) -> pd.Timestamp | None:
    """First expiry that is at least MIN_DTE days out."""
    found = eligible_expiries(expiries, today, config.MIN_DTE, 10**6, 1)
    return found[0] if found else None
