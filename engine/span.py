"""NSE SPAN margin from the exchange's own risk parameter file.

NSE (NSCCL) publishes SPAN 4.0 XML files several times a day. Each option contract
carries a 16-scenario risk array: loss per unit for a LONG position under each
price/volatility scenario (positive = loss). For a portfolio in one underlying and
one expiry, SPAN scan risk = worst scenario of the summed position losses. NSE sets
the short-option minimum charge to 0 for stock options, and a single-expiry
position has no calendar-spread charge, so scan risk is the full SPAN requirement.
"""

import io
import threading
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

import requests

from .data_fetch import _HEADERS

SPAN_URL = "https://nsearchives.nseindia.com/archives/nsccl/span/nsccl.{d}.{suffix}.zip"
_SUFFIXES = ["i6", "i5", "i4", "i3", "i2", "i1", "s"]  # newest intraday first; "s" = end of day
CACHE_DIR = Path(__file__).parent / "cache"
KEEP_FILES = 2  # newest SPAN zips kept on disk: the one in use plus the previous for comparison
_REFRESH_SECONDS = 60 * 60

_state = {"ts": 0.0, "source": None, "arrays": {}}


def _download_latest() -> tuple[str, bytes]:
    day = date.today()
    for _ in range(6):  # walk back over weekends/holidays
        d = day.strftime("%Y%m%d")
        for suffix in _SUFFIXES:
            url = SPAN_URL.format(d=d, suffix=suffix)
            r = requests.get(url, headers=_HEADERS, timeout=30)
            if r.status_code == 200 and len(r.content) > 100_000:
                return f"nsccl.{d}.{suffix}", r.content
        day -= timedelta(days=1)
    raise RuntimeError("No NSE SPAN file found for the last 6 days")


def _parse(zip_bytes: bytes, symbols: set[str]) -> dict:
    """{(symbol, 'YYYYMMDD', 'C'|'P', strike): [16 loss-per-unit values for a long]}"""
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    arrays = {}
    with z.open(z.namelist()[0]) as fh:
        for _, el in ET.iterparse(fh, events=("end",)):
            if el.tag != "oopPf":
                continue
            code = el.findtext("pfCode")
            if code in symbols:
                for series in el.findall("series"):
                    pe = series.findtext("pe")
                    for opt in series.findall("opt"):
                        ra = opt.find("ra")
                        arrays[(code, pe, opt.findtext("o"), float(opt.findtext("k")))] = [
                            float(a.text) for a in ra.findall("a")
                        ]
            el.clear()
    return arrays


_load_lock = threading.Lock()


def load(symbols: list[str]) -> dict:
    if _state["arrays"] and time.time() - _state["ts"] < _REFRESH_SECONDS:
        return _state
    # One download at a time: concurrent callers wait, then reuse the fresh result.
    with _load_lock:
        if _state["arrays"] and time.time() - _state["ts"] < _REFRESH_SECONDS:
            return _state
        name, blob = _download_latest()
        CACHE_DIR.mkdir(exist_ok=True)
        (CACHE_DIR / f"{name}.zip").write_bytes(blob)
        _state.update(ts=time.time(), source=name, arrays=_parse(blob, set(symbols)))
        _prune_cache()
    return _state


def _prune_cache(keep: int = KEEP_FILES) -> list[str]:
    """Deletes all but the newest `keep` SPAN zips. The app always parses the fresh download, so
    older copies are only kept for reference; each is ~8 MB and NSE publishes several a day."""
    files = sorted(CACHE_DIR.glob("nsccl.*.zip"), key=lambda f: f.stat().st_mtime, reverse=True)
    removed = []
    for f in files[keep:]:
        try:
            f.unlink()
            removed.append(f.name)
        except OSError:
            pass  # file in use or already gone; the next download retries
    return removed


def scan_risk_positions(symbol: str, expiry_yyyymmdd: str, positions: list[dict]) -> float | None:
    """SPAN requirement in rupees for signed positions [{side, strike, qty}] (qty < 0 = short).

    Returns None if any leg is missing from the SPAN file.
    """
    arrays = _state["arrays"]
    totals = [0.0] * 16
    for p in positions:
        key = (symbol, expiry_yyyymmdd, "C" if p["side"] == "CE" else "P", float(p["strike"]))
        ra = arrays.get(key)
        if ra is None:
            return None
        for i, v in enumerate(ra):
            totals[i] += v * p["qty"]  # arrays are loss per long unit; a short flips the sign
    return round(max(0.0, max(totals)), 2)


def scan_risk(symbol: str, expiry_yyyymmdd: str, legs: list[dict], lot_size: int) -> float | None:
    """SPAN requirement for SHORT legs [{side, strike}] of `lot_size` qty each."""
    return scan_risk_positions(
        symbol, expiry_yyyymmdd, [{"side": l["side"], "strike": l["strike"], "qty": -lot_size} for l in legs]
    )
