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


def nearest_valid_expiry(expiries: list[pd.Timestamp], today: pd.Timestamp) -> pd.Timestamp | None:
    """First expiry that is at least MIN_DTE days out."""
    for exp in sorted(expiries):
        if (exp - today).days >= config.MIN_DTE:
            return exp
    return None
