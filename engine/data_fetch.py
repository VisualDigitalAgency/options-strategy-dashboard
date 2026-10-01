"""Data fetch module.

- NSE option chain: OI, LTP, IV per strike (free, unofficial API — needs a
  browser-like session with cookies, so we warm up a session first).
- yfinance: daily OHLC history, used for swing support/resistance detection.

Both fetchers cache to avoid hammering NSE (they rate-limit / block bots
aggressively if you hit the endpoint too often).
"""

import io
import random
import threading
import time
import requests
import pandas as pd
import yfinance as yf

from . import config

NSE_BASE = "https://www.nseindia.com"
NSE_CONTRACT_INFO_URL = f"{NSE_BASE}/api/option-chain-contract-info"
NSE_OPTION_CHAIN_URL = f"{NSE_BASE}/api/option-chain-v3"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

_session_cache = {"session": None, "ts": 0}
_SESSION_TTL = 60 * 5  # refresh NSE session cookies every 5 min
_session_lock = threading.Lock()  # one thread refreshes cookies; the others wait and reuse them
_pace = {"lock": threading.Lock(), "next": 0.0}


def _wait_turn() -> None:
    """Spaces every nseindia.com request in this process by NSE_MIN_GAP_SECONDS plus random jitter,
    however many screen threads are running, so NSE sees a steady trickle instead of bursts."""
    with _pace["lock"]:
        now = time.monotonic()
        start = max(now, _pace["next"])
        _pace["next"] = start + config.NSE_MIN_GAP_SECONDS + random.uniform(0, config.NSE_GAP_JITTER_SECONDS)
    if start > now:
        time.sleep(start - now)


def _get_nse_session(stale: requests.Session | None = None) -> requests.Session:
    """Cached session with NSE cookies. Pass the session that just failed to force a refresh;
    if another thread already replaced it, that fresh one is reused."""
    with _session_lock:
        cur = _session_cache["session"]
        if cur and cur is not stale and time.time() - _session_cache["ts"] < _SESSION_TTL:
            return cur
        session = requests.Session()
        session.headers.update(_HEADERS)
        # Hitting the homepage first is required to receive valid cookies —
        # calling the API cold returns 401/403.
        _wait_turn()
        session.get(NSE_BASE, timeout=config.NSE_TIMEOUT_SECONDS)
        time.sleep(1)
        _session_cache.update(session=session, ts=time.time())
        return session


def _nse_get(url: str, params: dict) -> dict:
    session = _get_nse_session()
    _wait_turn()
    resp = session.get(url, params=params, timeout=config.NSE_TIMEOUT_SECONDS)
    if resp.status_code != 200 or not resp.text.strip("{} \n"):
        # Session likely stale, or NSE pushing back: back off, refresh cookies once and retry.
        time.sleep(config.NSE_RETRY_BACKOFF_SECONDS)
        session = _get_nse_session(stale=session)
        _wait_turn()
        resp = session.get(url, params=params, timeout=config.NSE_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.json()


NSE_HOLIDAYS_URL = f"{NSE_BASE}/api/holiday-master"
NSE_EVENT_CALENDAR_URL = f"{NSE_BASE}/api/event-calendar"
NSE_CORP_ACTIONS_URL = f"{NSE_BASE}/api/corporates-corporateActions"


def fetch_holidays() -> dict:
    """NSE trading holidays: {"CM": [...], "FO": [...]}, rows with tradingDate / weekDay / description."""
    return _nse_get(NSE_HOLIDAYS_URL, {"type": "trading"})


def fetch_event_calendar() -> list:
    """Upcoming board meetings (results etc.) for all equities: rows with symbol / purpose / bm_desc / date."""
    return _nse_get(NSE_EVENT_CALENDAR_URL, {"index": "equities"})


def fetch_corporate_actions(start: pd.Timestamp, end: pd.Timestamp) -> list:
    """Corporate actions (dividends, splits, bonuses, AGMs) with ex-dates in [start, end]:
    rows with symbol / subject / exDate."""
    return _nse_get(NSE_CORP_ACTIONS_URL, {
        "index": "equities", "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y"),
    })


def fetch_expiries(symbol: str) -> list[pd.Timestamp]:
    raw = _nse_get(NSE_CONTRACT_INFO_URL, {"symbol": symbol})
    return [pd.to_datetime(e, format="%d-%b-%Y") for e in raw.get("expiryDates", [])]


class NseSchemaError(RuntimeError):
    """Raised when NSE's option-chain response no longer matches the expected shape.

    NSE has silently swapped this endpoint before (option-chain-equities -> option-chain-v3),
    so a shape drift should surface as a loud, specific error rather than a KeyError deep in
    normalize_option_chain or silently-empty data.
    """


def _validate_option_chain_shape(raw: dict, symbol: str) -> None:
    records = raw.get("records")
    if not isinstance(records, dict):
        raise NseSchemaError(
            f"NSE option-chain response for {symbol} is missing 'records' — API shape may have changed"
        )
    data = records.get("data")
    if not isinstance(data, list) or not data:
        raise NseSchemaError(
            f"NSE option-chain response for {symbol} has no 'records.data' rows — API shape may have changed"
        )
    if "underlyingValue" not in records:
        raise NseSchemaError(
            f"NSE option-chain response for {symbol} is missing 'records.underlyingValue' — API shape may have changed"
        )
    sample = next((row for row in data if row.get("CE") or row.get("PE")), None)
    if sample is None:
        raise NseSchemaError(
            f"NSE option-chain response for {symbol} has no CE/PE rows — API shape may have changed"
        )
    leg = sample.get("CE") or sample.get("PE")
    expected_fields = {"openInterest", "changeinOpenInterest", "lastPrice", "impliedVolatility"}
    missing = expected_fields - leg.keys()
    if missing:
        raise NseSchemaError(
            f"NSE option-chain response for {symbol} is missing fields {missing} on CE/PE rows — "
            "API shape may have changed"
        )


def fetch_option_chain(symbol: str, expiry: pd.Timestamp) -> dict:
    """Raw NSE v3 option-chain JSON for one equity symbol and one expiry."""
    raw = _nse_get(
        NSE_OPTION_CHAIN_URL,
        {"type": "Equity", "symbol": symbol, "expiry": expiry.strftime("%d-%b-%Y")},
    )
    _validate_option_chain_shape(raw, symbol)
    return raw


def normalize_option_chain(raw: dict) -> pd.DataFrame:
    """Flattens NSE's nested option-chain JSON into a per-strike DataFrame."""
    records = []
    for row in raw.get("records", {}).get("data", []):
        ce = row.get("CE") or {}
        pe = row.get("PE") or {}
        records.append(
            {
                "strikePrice": row.get("strikePrice"),
                "CE_OI": ce.get("openInterest", 0),
                "CE_OI_CHG": ce.get("changeinOpenInterest", 0),
                "CE_PCHG": ce.get("pChange"),
                "CE_LTP": ce.get("lastPrice", 0.0),
                "CE_BID": ce.get("buyPrice1", 0.0),
                "CE_ASK": ce.get("sellPrice1", 0.0),
                "CE_IV": ce.get("impliedVolatility", 0.0),
                "PE_OI": pe.get("openInterest", 0),
                "PE_OI_CHG": pe.get("changeinOpenInterest", 0),
                "PE_PCHG": pe.get("pChange"),
                "PE_LTP": pe.get("lastPrice", 0.0),
                "PE_BID": pe.get("buyPrice1", 0.0),
                "PE_ASK": pe.get("sellPrice1", 0.0),
                "PE_IV": pe.get("impliedVolatility", 0.0),
            }
        )
    return pd.DataFrame(records)


def get_spot_price(raw: dict) -> float:
    return float(raw.get("records", {}).get("underlyingValue", 0.0))


def fetch_nifty50_symbols(csv_url: str) -> list[str]:
    resp = requests.get(csv_url, headers=_HEADERS, timeout=15)
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.text))["Symbol"].str.strip().tolist()


LOT_SIZE_CSV_URL = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"
_lot_cache = {"ts": 0.0, "df": None}


def fetch_lot_size(symbol: str, expiry: pd.Timestamp) -> int | None:
    """Lot size for `symbol` in the expiry's month column (e.g. 'OCT-26')."""
    if _lot_cache["df"] is None or time.time() - _lot_cache["ts"] > 6 * 3600:
        resp = requests.get(LOT_SIZE_CSV_URL, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        df.columns = [c.strip() for c in df.columns]
        df["SYMBOL"] = df["SYMBOL"].str.strip()
        _lot_cache.update(ts=time.time(), df=df.set_index("SYMBOL"))
    df = _lot_cache["df"]
    col = expiry.strftime("%b-%y").upper()
    if symbol not in df.index or col not in df.columns:
        return None
    val = str(df.at[symbol, col]).strip()
    return int(float(val)) if val and val.lower() != "nan" else None


def fetch_price_history_batch(yf_symbols: list[str], lookback_days: int) -> dict[str, pd.DataFrame]:
    """One yfinance request for a whole batch. Returns {yf_symbol: OHLC DataFrame}."""
    df = yf.download(
        yf_symbols,
        period=f"{lookback_days + 30}d",
        interval="1d",
        progress=False,
        auto_adjust=True,
        group_by="ticker",
        threads=True,
    )
    out = {}
    for sym in yf_symbols:
        try:
            sub = df[sym] if isinstance(df.columns, pd.MultiIndex) else df
            out[sym] = sub.dropna(how="all").tail(lookback_days)
        except KeyError:
            out[sym] = pd.DataFrame()
    return out


def fetch_price_history(yf_symbol: str, lookback_days: int) -> pd.DataFrame:
    """Daily OHLC history for swing S/R detection."""
    df = yf.download(
        yf_symbol,
        period=f"{lookback_days + 30}d",  # pad for weekends/holidays
        interval="1d",
        progress=False,
        auto_adjust=True,
    )
    return df.tail(lookback_days)
