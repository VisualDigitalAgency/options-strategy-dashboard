"""Monthly paper-trading leaderboard (issue #125, part of #120).

Built from booked paper trades only (`trade_results`, one row per closed leg, the same "trade" unit
as progress.py). For one IST calendar month, per user:
  - only legs closed since the last virtual-account reset count, so two capitals never mix
  - return %    = summed realised P&L / starting capital
  - max drawdown = deepest fall of the cumulative realised P&L from its running peak (which starts
                   at 0), as % of capital. Open positions are not marked.
  - ratio       = return % / max(drawdown %, MIN_DD_PCT), so a loss-free month isn't infinite.
Ranked by ratio, ties by return %, then nickname for a stable order.

Eligible: active, has a nickname, opted in, at least MIN_TRADES legs a month. Bands are Levels 1-3
("Rising"), 4-6 and 7-10. A period is a month ("2026-10") or a calendar quarter ("2026-Q4"); a quarter
needs 3 x MIN_TRADES legs and is scored over all of them. Opted-in players short of the count are
listed as "near" (nickname, level, trades) while the period runs.

Finished months are frozen into `leaderboard_entries` by the worker on the 1st; the running month is
computed live, cached for CURRENT_TTL, and shown as provisional. Quarters are computed from the trade
log on request and cached (PAST_TTL once finished). Nothing private leaves here:
nickname, level and ratios only, never an email, a user id or a rupee amount.
"""

import logging
import re
from datetime import datetime, timedelta

from . import cache, config, db, progress
from .progress import IST

log = logging.getLogger("theta.leaderboard")

MIN_TRADES = 5
MIN_LEVEL = 1
MIN_DD_PCT = 1.0
BANDS = (("1-3", 1, 3), ("4-6", 4, 6), ("7-10", 7, 10))
BAND_NAMES = {"1-3": "Rising", "4-6": "Levels 4-6", "7-10": "Levels 7-10"}
CURRENT_TTL = 600
PAST_TTL = 86400
NEAR_MAX = 30
MONTH_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
QUARTER_RE = re.compile(r"(\d{4})-Q([1-4])")
FIELDS = ("rank", "nickname", "level", "ratio", "return_pct", "max_dd_pct", "trades", "win_rate")


def this_month(now: datetime | None = None) -> str:
    return (now or datetime.now(IST)).astimezone(IST).strftime("%Y-%m")


def quarter_of(month: str) -> str:
    return f"{month[:4]}-Q{(int(month[5:7]) - 1) // 3 + 1}"


def quarter_months(quarter: str) -> list[str]:
    y, q = QUARTER_RE.fullmatch(quarter).groups()
    return [f"{y}-{m:02d}" for m in range(3 * int(q) - 2, 3 * int(q) + 1)]


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


def _entry(user_id: int, month: str, months: list[str] | None = None) -> dict | None:
    with db.tx(user_id) as c:
        level = c.value("SELECT level FROM user_levels WHERE user_id=:u", u=user_id) or 1
        if level < MIN_LEVEL:
            return None
        rows = c.all("SELECT t.realized_pnl, t.capital, t.had_sl, t.short, t.entry_delta FROM trade_results t "
                     "JOIN accounts a ON a.user_id = t.user_id "
                     "WHERE t.user_id=:u AND t.closed_at >= a.created_at "
                     "AND to_char(t.closed_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM') = ANY(:ms) "
                     "ORDER BY t.closed_at, t.id", u=user_id, ms=months or [month])
    if not rows or not float(rows[-1]["capital"]):
        return None
    if len(rows) < MIN_TRADES * len(months or [month]):
        return {"level": level, "trades": len(rows)}  # not ranked yet: shown under "Getting there"
    return {"level": level, **score([float(r["realized_pnl"]) for r in rows], float(rows[-1]["capital"])),
            "discipline": discipline(rows)}


def discipline(rows: list[dict]) -> int:
    """0-100: the share of closed legs traded by the rules: stop-loss on, and a short sold below
    DELTA_MAX_ABS (retention phase 2). Shown next to the ratio; it decides the season champion."""
    ok = sum(1 for r in rows if r["had_sl"] and not (r["short"] and (r["entry_delta"] is None
                                                                     or float(r["entry_delta"]) >= config.DELTA_MAX_ABS)))
    return round(ok * 100 / len(rows)) if rows else 0


def _discipline_of(user_id: int, months: list[str]) -> int:
    with db.tx(user_id) as c:
        rows = c.all("SELECT t.had_sl, t.short, t.entry_delta FROM trade_results t JOIN accounts a ON a.user_id = t.user_id "
                     "WHERE t.user_id=:u AND t.closed_at >= a.created_at "
                     "AND to_char(t.closed_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM') = ANY(:ms)", u=user_id, ms=months)
    return discipline(rows)


def champions(month: str) -> dict[str, int]:
    """A finalized month's season champion per band: band -> user_id. The best-ranked player whose
    discipline score is at least config.CHAMPION_DISCIPLINE, so a lucky reckless month never wins."""
    with db.tx() as c:
        rows = c.all("SELECT band, user_id FROM leaderboard_entries WHERE month=:m ORDER BY band, rank", m=month)
    out = {}
    for r in rows:
        if r["band"] not in out and _discipline_of(r["user_id"], [month]) >= config.CHAMPION_DISCIPLINE:
            out[r["band"]] = r["user_id"]
    return out


def titles(user_id: int) -> list[dict]:
    """The months this user was a season champion, newest first: month and band name."""
    names = dict((b, BAND_NAMES[b]) for b, _, _ in BANDS)
    return [{"month": m, "band": names[b]} for m in finalized_months()
            for b, uid in champions(m).items() if uid == user_id]


def compute(month: str, with_ids: bool = False, months: list[str] | None = None) -> dict[str, list[dict]]:
    """Every band's ranked rows for `month`, from the trade log as it stands now: FIELDS only, plus
    `user_id` when `with_ids` (finalize, for the Level 8 gate, #146; never for the public board)."""
    return _bands(_scan(month, months), with_ids)


def _scan(month: str, months: list[str] | None = None) -> list[dict]:
    """Every opted-in player with a closed leg in the period: ranked ones carry a score, the rest only
    their trade count."""
    with db.tx() as c:
        people = c.all("SELECT id, nickname FROM users WHERE status = 'active' AND leaderboard_opt_in "
                       "AND nickname IS NOT NULL ORDER BY id")
    entries = []
    for p in people:
        try:
            e = _entry(p["id"], month, months)
        except Exception:  # one user's failure never stops the board
            log.exception("leaderboard entry failed for user %s", p["id"])
            continue
        if e:
            entries.append({"user_id": p["id"], "nickname": p["nickname"], **e})
    return entries


def _near(entries: list[dict], need: int) -> list[dict]:
    """Players not ranked yet, most trades first: nickname, level and trade count only."""
    rows = sorted((e for e in entries if "ratio" not in e), key=lambda e: (-e["trades"], e["nickname"].lower()))
    # ponytail: capped at NEAR_MAX rows; page through them if the list ever gets long.
    return [{"nickname": e["nickname"], "level": e["level"], "trades": e["trades"], "need": need} for e in rows[:NEAR_MAX]]


def _bands(entries: list[dict], with_ids: bool = False) -> dict[str, list[dict]]:
    entries = [e for e in entries if "ratio" in e]
    out = {}
    for band, lo, hi in BANDS:
        rows = sorted((e for e in entries if lo <= e["level"] <= hi),
                      key=lambda e: (-e["ratio"], -e["return_pct"], e["nickname"].lower()))
        out[band] = [{"rank": i, **{k: v for k, v in e.items() if with_ids or k != "user_id"}} for i, e in enumerate(rows, 1)]
    return out


def finalize(month: str) -> int:
    """Freezes `month` into leaderboard_entries, replacing any earlier copy. Returns rows written."""
    boards = compute(month, with_ids=True)
    with db.tx() as c:
        c.run("DELETE FROM leaderboard_entries WHERE month=:m", m=month)
        for band, rows in boards.items():
            for r in rows:
                c.run("INSERT INTO leaderboard_entries (month, band, rank, user_id, nickname, level, ratio,"
                      " return_pct, max_dd_pct, trades, win_rate) VALUES (:m, :b, :rank, :user_id, :nickname,"
                      " :level, :ratio, :return_pct, :max_dd_pct, :trades, :win_rate)", m=month, b=band, **r)
    return sum(len(r) for r in boards.values())


def finalized_months() -> list[str]:
    with db.tx() as c:
        return [r["month"] for r in c.all("SELECT DISTINCT month FROM leaderboard_entries ORDER BY month DESC")]


def _quarter(quarter: str, current: str) -> tuple[dict, bool, list]:
    """A calendar quarter's board, from the trade log. Banded by each player's level today, not at the time."""
    # ponytail: computed on request and cached, not frozen like months; freeze it if quarters ever gate a level.
    key = f"leaderboard:{quarter}"
    got = cache.get_json(key)
    running = quarter == quarter_of(current)
    if got is None:
        months = quarter_months(quarter)
        entries = _scan(quarter, months)
        got = {"bands": _bands(entries), "near": _near(entries, MIN_TRADES * 3) if running else []}
        cache.set_json(key, got, CURRENT_TTL if running else PAST_TTL)
    return got["bands"], running, got["near"]


def get(month: str | None = None) -> dict:
    """One period's board: a month ("2026-09") or a quarter ("2026-Q3"). No period, or the running
    month, gives the live provisional monthly board."""
    current = this_month()
    if month and not (MONTH_RE.fullmatch(month) or QUARTER_RE.fullmatch(month)):
        raise ValueError("Period must look like 2026-09 or 2026-Q3")
    months = finalized_months()
    quarters = sorted({quarter_of(m) for m in [current, *months]}, reverse=True)
    if month and QUARTER_RE.fullmatch(month):
        bands, provisional, near = _quarter(month, current)
        return _out(month, provisional, [current, *months], quarters, bands, near)
    if not month or month == current:
        boards = cache.get_json("leaderboard:current")
        if boards is None or boards.get("month") != current or "near" not in boards:
            entries = _scan(current)
            boards = {"month": current, "bands": _bands(entries), "near": _near(entries, MIN_TRADES)}
            cache.set_json("leaderboard:current", boards, CURRENT_TTL)
        bands, near = boards["bands"], boards["near"]
        month, provisional = current, True
    else:
        with db.tx() as c:
            rows = c.all("SELECT * FROM leaderboard_entries WHERE month=:m ORDER BY band, rank", m=month)
        champs = set(champions(month).values())
        bands = {b: [{**{k: float(r[k]) if k in ("ratio", "return_pct", "max_dd_pct", "win_rate") else r[k]
                         for k in FIELDS},
                      "discipline": _discipline_of(r["user_id"], [month]), "champion": r["user_id"] in champs}
                     for r in rows if r["band"] == b] for b, _, _ in BANDS}
        provisional, near = False, []
    return _out(month, provisional, [current, *months], quarters, bands, near)


def hall_of_fame() -> list[dict]:
    """Level 10 players who show on the leaderboard, first to get there first: nickname and the date
    they reached it. Opt-in like the boards, and never an email or an amount."""
    with db.tx() as c:
        people = c.all("SELECT id, nickname FROM users WHERE status = 'active' AND leaderboard_opt_in "
                       "AND nickname IS NOT NULL")
    out = []
    for p in people:  # user_levels is per-user under RLS
        with db.tx(p["id"]) as c:
            row = c.one("SELECT level, level_since FROM user_levels WHERE user_id=:u", u=p["id"])
        if row and row["level"] == 10:
            out.append({"nickname": p["nickname"], "since": str(row["level_since"])[:10]})
    return sorted(out, key=lambda r: r["since"])


def _out(period: str, provisional: bool, months: list[str], quarters: list[str], bands: dict, near: list) -> dict:
    bands = {b: [{**r, "badges": progress.badges(r["level"])} for r in rows] for b, rows in bands.items()}
    return {"hall_of_fame": hall_of_fame(), "month": period, "kind": "quarter" if QUARTER_RE.fullmatch(period) else "month", "provisional": provisional,
            "months": months, "quarters": quarters, "min_trades": MIN_TRADES, "min_level": MIN_LEVEL, "near": near,
            "bands": [{"band": b, "levels": BAND_NAMES[b], "range": f"Levels {lo}-{hi}", "rows": bands.get(b, [])}
                      for b, lo, hi in BANDS]}
