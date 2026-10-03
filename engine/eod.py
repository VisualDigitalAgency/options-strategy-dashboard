"""End-of-day option prices from NSE's daily F&O bhavcopy (data plan, PR A).

The plan: virtual trading moves off NSE's live option-chain API (SEBI's May 2024 circular restricts
real-time price data for paper-trading products) onto the official end-of-day file, which NSE
publishes after the close in its "UDiFF" CSV format:
    https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip

This module only ingests: download once a trading day after EOD_READY_IST, keep stock options
(FinInstrmTp "STO"), and save a compact JSON per day under engine/cache/eod/ (the volume the API and
worker share, like the SPAN files). Nothing reads it for pricing yet; PR B switches fills and marks
over once the owner has checked real files with `python scripts/check_eod.py`.

Per contract it keeps the settlement price (what positions are marked and filled at), the close,
the previous close, open interest and its change, and volume. The underlying's price comes from the
same file (UndrlygPric) and the lot size from NewBrdLotQty. The file carries no IV, so chain() works
it out from the settlement price with Black-Scholes (greeks_sr.implied_vol).
"""

import csv
import io
import json
import logging
import zipfile
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests

from . import config, greeks_sr, pricing
from .data_fetch import _HEADERS
from .progress import IST

log = logging.getLogger("theta.eod")

URL = "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d}_F_0000.csv.zip"
DIR = Path(__file__).parent / "cache" / "eod"
KEEP_DAYS = 5
_loaded: dict = {"path": None, "mtime": 0.0, "data": None}


def _num(v, cast=float, default=0):
    try:
        return cast(float(v)) if v not in (None, "", "-") else default
    except ValueError:
        return default


def parse(zip_bytes: bytes) -> dict:
    """The bhavcopy zip -> {"date", "symbols": {sym: {"spot", "lot", "chains": {expiry: [row, ...]}}}}.
    Only stock options are kept; a row is {strike, side, settle, close, prev_close, oi, oi_chg, volume}."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        text = z.read(name).decode("utf-8-sig")
    out, day = {}, None
    for r in csv.DictReader(io.StringIO(text)):
        if (r.get("FinInstrmTp") or "").strip() != "STO" or (r.get("OptnTp") or "").strip() not in ("CE", "PE"):
            continue
        day = day or (r.get("TradDt") or "").strip()
        sym = r["TckrSymb"].strip()
        s = out.setdefault(sym, {"spot": _num(r.get("UndrlygPric")), "lot": _num(r.get("NewBrdLotQty"), int), "chains": {}})
        s["chains"].setdefault(r["XpryDt"].strip(), []).append({
            "strike": _num(r.get("StrkPric")), "side": r["OptnTp"].strip(),
            "settle": _num(r.get("SttlmPric")), "close": _num(r.get("ClsPric")), "prev_close": _num(r.get("PrvsClsgPric")),
            "oi": _num(r.get("OpnIntrst"), int), "oi_chg": _num(r.get("ChngInOpnIntrst"), int),
            "volume": _num(r.get("TtlTradgVol"), int),
        })
    if not out:
        raise ValueError("No stock options in the bhavcopy (did the format change?)")
    return {"date": day, "symbols": out}


def download(day: date) -> bytes | None:
    """The bhavcopy zip for `day`, or None while NSE hasn't published it (404 or a tiny body)."""
    r = requests.get(URL.format(d=day.strftime("%Y%m%d")), headers=_HEADERS, timeout=60)
    return r.content if r.status_code == 200 and len(r.content) > 10_000 else None


def path_for(day: date) -> Path:
    return DIR / f"{day.isoformat()}.json"


def save(day: date, data: dict) -> Path:
    DIR.mkdir(parents=True, exist_ok=True)
    p = path_for(day)
    p.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    for old in sorted(DIR.glob("*.json"))[:-KEEP_DAYS]:
        old.unlink(missing_ok=True)
    return p


def latest() -> dict | None:
    """The newest saved day, read once per file change."""
    files = sorted(DIR.glob("*.json"))
    if not files:
        return None
    p = files[-1]
    if _loaded["path"] != p or _loaded["mtime"] != p.stat().st_mtime:
        _loaded.update(path=p, mtime=p.stat().st_mtime, data=json.loads(p.read_text(encoding="utf-8")))
    return _loaded["data"]


def due(now: datetime) -> date | None:
    """The trading day whose file the worker should fetch now, or None: after EOD_READY_IST on a
    trading day whose file isn't saved yet."""
    now = now.astimezone(IST)
    today = now.date()
    if not pricing.trading_day(now) or now.strftime("%H:%M") < config.EOD_READY_IST:
        return None
    return None if path_for(today).exists() else today


def refresh(now: datetime | None = None) -> str | None:
    """Fetches and saves the due day's file. Returns the saved date, or None when nothing was due
    or NSE hasn't published it yet (the worker tries again later)."""
    day = due(now or datetime.now(IST))
    if day is None:
        return None
    blob = download(day)
    if blob is None:
        return None
    data = parse(blob)
    save(day, data)
    log.info("eod: %s saved, %s stocks", day, len(data["symbols"]))
    return day.isoformat()


def expiries(symbol: str, data: dict | None = None) -> list[pd.Timestamp]:
    """The stock's expiries listed in the end-of-day file, nearest first."""
    s = ((data or latest() or {}).get("symbols") or {}).get(symbol)
    return sorted(pd.Timestamp(e) for e in s["chains"]) if s else []


def lot(symbol: str, data: dict | None = None) -> int | None:
    s = ((data or latest() or {}).get("symbols") or {}).get(symbol)
    return (s or {}).get("lot") or None


def chain(symbol: str, expiry: str, data: dict | None = None) -> tuple[float, pd.DataFrame] | None:
    """(spot, chain) for one stock and expiry from the end-of-day file, in the same columns as
    data_fetch.normalize_option_chain, so PR B can swap the source. Bid and ask are the settlement
    price (the file has no order book). None when the stock or expiry isn't in the file."""
    data = data or latest()
    s = (data or {}).get("symbols", {}).get(symbol)
    rows = s and s["chains"].get(expiry)
    if not rows:
        return None
    dte = max((pd.Timestamp(expiry) - pd.Timestamp(data["date"])).days, 0)
    by = {}
    for r in rows:
        b = by.setdefault(r["strike"], {"strikePrice": r["strike"]})
        px, side = r["settle"], r["side"]
        b |= {f"{side}_OI": r["oi"], f"{side}_OI_CHG": r["oi_chg"], f"{side}_LTP": px, f"{side}_BID": px, f"{side}_ASK": px,
              f"{side}_PCHG": round((r["close"] - r["prev_close"]) / r["prev_close"] * 100, 2) if r["prev_close"] else None,
              f"{side}_IV": greeks_sr.implied_vol(px, s["spot"], r["strike"], dte, side)}
    df = pd.DataFrame(sorted(by.values(), key=lambda x: x["strikePrice"]))
    for side in ("CE", "PE"):
        for col, fill in (("OI", 0), ("OI_CHG", 0), ("LTP", 0.0), ("BID", 0.0), ("ASK", 0.0), ("IV", 0.0), ("PCHG", None)):
            c = f"{side}_{col}"
            if c not in df:
                df[c] = fill
            elif fill is not None:  # a strike quoted on one side only: the other is 0, never NaN
                df[c] = df[c].fillna(fill)
    return s["spot"], df
