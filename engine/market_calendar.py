"""NSE trading holidays and Nifty 50 corporate events (results, dividends, splits, bonuses, AGMs).

The worker refreshes this once a day outside the market window (a handful of NSE calls through the
usual pacing) and stores it in Redis. The API and the screen schedule only read the stored copy, so
a screen never makes extra NSE calls for it. Each source fails on its own: a blocked endpoint leaves
its part empty and is listed under "errors"; it never breaks the screen.
"""

import logging
import time
from datetime import date

import pandas as pd

from . import cache, config, data_fetch, risk_rules

KEY = "market:calendar"
log = logging.getLogger("theta.calendar")

# Events that can gap a stock through a short strike, or trigger early assignment on short calls.
RISKY = {"results", "dividend"}


def _date(text) -> str | None:
    """NSE writes dates as 14-Oct-2026 (sometimes 14-OCT-2026); returns YYYY-MM-DD, or None."""
    if not text or not isinstance(text, str):
        return None
    try:
        return pd.to_datetime(text.strip(), format="%d-%b-%Y").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def parse_holidays(raw: dict) -> list[dict]:
    """Equity-derivatives (FO) holidays, falling back to the cash-market (CM) list."""
    rows = (raw or {}).get("FO") or (raw or {}).get("CM") or []
    out = []
    for r in rows:
        d = _date(r.get("tradingDate"))
        if d:
            out.append({"date": d, "day": (r.get("weekDay") or "").strip(),
                        "description": (r.get("description") or "").strip()})
    return sorted(out, key=lambda h: h["date"])


def _board_type(purpose: str) -> str:
    return "results" if "result" in purpose.lower() else "board_meeting"


def _action_type(subject: str) -> str | None:
    s = subject.lower()
    if "dividend" in s:
        return "dividend"
    if "split" in s or "sub-division" in s or "sub division" in s:
        return "split"
    if "bonus" in s:
        return "bonus"
    if "general meeting" in s or "agm" in s:
        return "agm"
    if "buy back" in s or "buyback" in s:
        return "buyback"
    return None


def parse_board_meetings(raw: list, symbols: set[str]) -> list[dict]:
    out = []
    for r in raw or []:
        sym, d = (r.get("symbol") or "").strip(), _date(r.get("date"))
        if sym in symbols and d:
            purpose = (r.get("purpose") or r.get("bm_desc") or "Board meeting").strip()
            out.append({"symbol": sym, "date": d, "type": _board_type(purpose), "purpose": purpose})
    return out


def parse_corporate_actions(raw: list, symbols: set[str]) -> list[dict]:
    out = []
    for r in raw or []:
        sym, d = (r.get("symbol") or "").strip(), _date(r.get("exDate"))
        subject = (r.get("subject") or "").strip()
        kind = _action_type(subject)
        if sym in symbols and d and kind:
            out.append({"symbol": sym, "date": d, "type": kind, "purpose": subject})
    return out


def refresh() -> dict:
    """Fetches every source (each on its own) and stores the merged calendar in Redis."""
    today = pd.Timestamp(date.today())
    symbols = set(risk_rules.get_universe())
    holidays, events, errors = [], [], []
    sources = (
        ("holidays", lambda: holidays.extend(parse_holidays(data_fetch.fetch_holidays()))),
        ("board meetings", lambda: events.extend(parse_board_meetings(data_fetch.fetch_event_calendar(), symbols))),
        ("corporate actions", lambda: events.extend(parse_corporate_actions(
            data_fetch.fetch_corporate_actions(today, today + pd.Timedelta(days=config.CALENDAR_DAYS_AHEAD)),
            symbols))),
    )
    old = load()
    for name, run in sources:
        try:
            run()
        except Exception as e:  # noqa: BLE001 — a blocked source must not take down the others
            log.warning("market calendar: %s fetch failed: %s", name, e)
            errors.append(name)
    # Keep yesterday's copy of a source that failed today rather than blanking it.
    if "holidays" in errors:
        holidays = old["holidays"]
    if "board meetings" in errors:
        events += [e for e in old["events"] if e["type"] in ("results", "board_meeting")]
    if "corporate actions" in errors:
        events += [e for e in old["events"] if e["type"] not in ("results", "board_meeting")]
    seen, unique = set(), []
    for e in sorted(events, key=lambda e: (e["date"], e["symbol"], e["type"])):
        k = (e["symbol"], e["date"], e["type"])
        if k not in seen:
            seen.add(k)
            unique.append(e)
    data = {"holidays": holidays, "events": unique, "fetched_at": time.time(), "errors": errors}
    cache.set_json(KEY, data)
    return data


def load() -> dict:
    data = cache.get_json(KEY)
    return data if isinstance(data, dict) else {"holidays": [], "events": [], "fetched_at": None, "errors": []}


def holiday_dates(data: dict | None = None) -> set[str]:
    return {h["date"] for h in (data or load())["holidays"]}


def events_until(events: list[dict], symbol: str, today: str, expiry: str | None) -> list[dict]:
    """`symbol`'s events from today through `expiry` (inclusive), each with days_away and risky."""
    t = pd.Timestamp(today)
    out = []
    for e in events:
        if e["symbol"] == symbol and e["date"] >= today and (not expiry or e["date"] <= expiry):
            out.append({**e, "days_away": (pd.Timestamp(e["date"]) - t).days, "risky": e["type"] in RISKY})
    return out


def due(now: float | None = None) -> bool:
    """Refresh once a day, outside the market window; right away if there is no copy yet."""
    fetched = load()["fetched_at"]
    if not fetched:
        return True
    now = time.time() if now is None else now
    return now - fetched >= config.CALENDAR_REFRESH_SECONDS
