"""Monthly paper-trading leaderboard (issue #125, part of #120).

Built from booked paper trades only (`trade_results`, one row per closed leg, the same "trade" unit
as progress.py). For one IST calendar month, per user:
  - only legs closed since the last virtual-account reset count, so two capitals never mix
  - return %    = summed realised P&L / starting capital
  - max drawdown = deepest fall of the cumulative realised P&L from its running peak (which starts
                   at 0), as % of capital. Open positions are not marked.
  - ratio       = return % / max(drawdown %, MIN_DD_PCT), so a loss-free month isn't infinite.
Ranked by ratio, ties by return %, then nickname for a stable order.

Eligible: active, has a nickname, opted in, Level 4+, at least MIN_TRADES legs in the month. Bands
are Levels 4-6 and 7-10 (Levels 1-3 can't enter, so the page shows them a teaser instead).

Finished months are frozen into `leaderboard_entries` by the worker on the 1st; the running month is
computed live, cached for CURRENT_TTL, and shown as provisional. Nothing private leaves here:
nickname, level and ratios only, never an email, a user id or a rupee amount.
"""

import logging
import re
from datetime import datetime, timedelta

from . import cache, db
from .progress import IST

log = logging.getLogger("theta.leaderboard")

MIN_TRADES = 5
MIN_LEVEL = 4
MIN_DD_PCT = 1.0
BANDS = (("4-6", 4, 6), ("7-10", 7, 10))
CURRENT_TTL = 600
MONTH_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
FIELDS = ("rank", "nickname", "level", "ratio", "return_pct", "max_dd_pct", "trades", "win_rate")


def this_month(now: datetime | None = None) -> str:
    return (now or datetime.now(IST)).astimezone(IST).strftime("%Y-%m")


def previous_month(now: datetime | None = None) -> str:
    first = (now or datetime.now(IST)).astimezone(IST).replace(day=1)
    return (first - timedelta(days=1)).strftime("%Y-%m")


def score(pnls: list[float], capital: float) -> dict:
    """Return %, max drawdown %, ratio and win rate for one month of closed legs, in close order."""
    eq = peak = dd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    ret = eq / capital * 100
    dd_pct = dd / capital * 100
    return {"return_pct": round(ret, 2), "max_dd_pct": round(dd_pct, 2),
            "ratio": round(ret / max(dd_pct, MIN_DD_PCT), 2), "trades": len(pnls),
            "win_rate": round(sum(p > 0 for p in pnls) / len(pnls) * 100, 1)}


def _entry(user_id: int, month: str) -> dict | None:
    with db.tx(user_id) as c:
        level = c.value("SELECT level FROM user_levels WHERE user_id=:u", u=user_id) or 1
        if level < MIN_LEVEL:
            return None
        rows = c.all("SELECT t.realized_pnl, t.capital FROM trade_results t JOIN accounts a ON a.user_id = t.user_id "
                     "WHERE t.user_id=:u AND t.closed_at >= a.created_at "
                     "AND to_char(t.closed_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM') = :m "
                     "ORDER BY t.closed_at, t.id", u=user_id, m=month)
    if len(rows) < MIN_TRADES or not float(rows[-1]["capital"]):
        return None
    return {"level": level, **score([float(r["realized_pnl"]) for r in rows], float(rows[-1]["capital"]))}


def compute(month: str) -> dict[str, list[dict]]:
    """Every band's ranked rows for `month`, from the trade log as it stands now."""
    with db.tx() as c:
        people = c.all("SELECT id, nickname FROM users WHERE status = 'active' AND leaderboard_opt_in "
                       "AND nickname IS NOT NULL ORDER BY id")
    entries = []
    for p in people:
        try:
            e = _entry(p["id"], month)
        except Exception:  # one user's failure never stops the board
            log.exception("leaderboard entry failed for user %s", p["id"])
            continue
        if e:
            entries.append({"nickname": p["nickname"], **e})
    out = {}
    for band, lo, hi in BANDS:
        rows = sorted((e for e in entries if lo <= e["level"] <= hi),
                      key=lambda e: (-e["ratio"], -e["return_pct"], e["nickname"].lower()))
        out[band] = [{"rank": i, **e} for i, e in enumerate(rows, 1)]
    return out


def finalize(month: str) -> int:
    """Freezes `month` into leaderboard_entries, replacing any earlier copy. Returns rows written."""
    boards = compute(month)
    with db.tx() as c:
        c.run("DELETE FROM leaderboard_entries WHERE month=:m", m=month)
        for band, rows in boards.items():
            for r in rows:
                c.run("INSERT INTO leaderboard_entries (month, band, rank, nickname, level, ratio, return_pct,"
                      " max_dd_pct, trades, win_rate) VALUES (:m, :b, :rank, :nickname, :level, :ratio,"
                      " :return_pct, :max_dd_pct, :trades, :win_rate)", m=month, b=band, **r)
    return sum(len(r) for r in boards.values())


def finalized_months() -> list[str]:
    with db.tx() as c:
        return [r["month"] for r in c.all("SELECT DISTINCT month FROM leaderboard_entries ORDER BY month DESC")]


def get(month: str | None = None) -> dict:
    """One month's board. No month, or the running month, gives the live provisional board."""
    current = this_month()
    if month and not MONTH_RE.fullmatch(month):
        raise ValueError("Month must look like 2026-09")
    months = finalized_months()
    if not month or month == current:
        boards = cache.get_json("leaderboard:current")
        if boards is None or boards.get("month") != current:
            boards = {"month": current, "bands": compute(current)}
            cache.set_json("leaderboard:current", boards, CURRENT_TTL)
        bands = boards["bands"]
        month, provisional = current, True
    else:
        with db.tx() as c:
            rows = c.all("SELECT * FROM leaderboard_entries WHERE month=:m ORDER BY band, rank", m=month)
        bands = {b: [{k: float(r[k]) if k in ("ratio", "return_pct", "max_dd_pct", "win_rate") else r[k]
                      for k in FIELDS} for r in rows if r["band"] == b] for b, _, _ in BANDS}
        provisional = False
    return {"month": month, "provisional": provisional, "months": [current, *months],
            "bands": [{"band": b, "levels": f"Levels {lo}-{hi}", "rows": bands.get(b, [])} for b, lo, hi in BANDS],
            "min_trades": MIN_TRADES, "min_level": MIN_LEVEL}
