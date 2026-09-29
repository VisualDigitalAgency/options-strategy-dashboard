"""One definition of an option's fair price and tradability, shared by the screener, the order
ticket, position P&L and the stop-loss rule.

NSE's LTP is the last trade, which on a thin strike can be hours old and far from today's
bid/ask (e.g. DRREDDY 1400 CE: bid 3.40, LTP 6.00). Pricing from it overstates the premium a
sell actually gets and shows the gap as an instant unbooked loss. So:
  - a sell is priced at the bid (what a marketable limit gets),
  - open positions are marked at the bid/ask mid, with LTP only as a fallback held inside the book,
  - a strike is untradable when the spread is wide, OI is thin, or the LTP sits far outside the book.
"""

from datetime import datetime, timedelta, timezone

from . import config

IST = timezone(timedelta(hours=5, minutes=30))


def market_open() -> bool:
    now = datetime.now(IST)
    return now.weekday() < 5 and (9, 15) <= (now.hour, now.minute) < (15, 30)


def has_book(bid: float, ask: float) -> bool:
    """Both sides quoted and not crossed."""
    return bid > 0 and ask > 0 and ask >= bid


def mid(bid: float, ask: float) -> float:
    return round((bid + ask) / 2, 2)


def spread_pct(bid: float, ask: float) -> float | None:
    """Bid-ask spread as % of the mid; None without a two-sided book."""
    return round((ask - bid) / mid(bid, ask) * 100, 1) if has_book(bid, ask) else None


def ltp_gap_pct(bid: float, ask: float, ltp: float) -> float:
    """How far the LTP sits outside the book, as % of the mid (0 when inside it or no book)."""
    if not has_book(bid, ask) or ltp <= 0:
        return 0.0
    off = max(bid - ltp, ltp - ask, 0.0)
    return round(off / mid(bid, ask) * 100, 1)


def mark(bid: float, ask: float, ltp: float) -> tuple[float | None, str]:
    """Fair value of one contract and where it came from: the mid when both sides are quoted,
    else the LTP held inside whichever side exists, else None."""
    if has_book(bid, ask):
        return mid(bid, ask), "mid"
    if ltp > 0:
        px = ltp
        if bid > 0:
            px = max(px, bid)
        if ask > 0:
            px = min(px, ask)
        return round(px, 2), "ltp"
    return None, "none"


def sell_premium(bid: float, ask: float, ltp: float, in_session: bool) -> tuple[float, str]:
    """The premium a sell realistically books: the bid. Outside the session NSE often clears the
    book, so the LTP stands in there (labelled) until the next in-session screen replaces it."""
    if bid > 0 and (ask <= 0 or ask >= bid):
        return round(bid, 2), "bid"
    if not in_session and ltp > 0:
        return round(ltp, 2), "ltp"
    return 0.0, "none"


def liquidity(bid: float, ask: float, ltp: float, oi: int, in_session: bool) -> dict:
    """{ok, reason, spread_pct, ltp_gap_pct}. ok is None when it can't be judged (no book outside
    the session); in session, no two-sided book is itself illiquid."""
    sp, gap = spread_pct(bid, ask), ltp_gap_pct(bid, ask, ltp)
    out = {"ok": True, "reason": None, "spread_pct": sp, "ltp_gap_pct": gap}
    if oi < config.LIQUIDITY_MIN_OI:
        return {**out, "ok": False, "reason": f"OI {oi:,} below {config.LIQUIDITY_MIN_OI:,}"}
    if sp is None:
        if in_session:
            return {**out, "ok": False, "reason": "no two-sided bid/ask"}
        return {**out, "ok": None, "reason": "no bid/ask outside market hours"}
    if sp > config.LIQUIDITY_MAX_SPREAD_PCT:
        return {**out, "ok": False, "reason": f"bid-ask spread {sp:.0f}% of mid (max {config.LIQUIDITY_MAX_SPREAD_PCT}%)"}
    if gap > config.LIQUIDITY_MAX_LTP_GAP_PCT:
        return {**out, "ok": False,
                "reason": f"last trade ₹{ltp:.2f} is {gap:.0f}% outside the ₹{bid:.2f}/₹{ask:.2f} book (stale)"}
    return out
