"""Weekly habits (retention plan, phase 1): a learning streak and one rotating weekly challenge.

A week is an ISO week in IST ("2026-W40"). A week counts toward the streak when the user passed a
lesson quiz or closed a trade in it. The streak runs back from this week; a week that hasn't had
activity yet doesn't break it until it ends.

The challenge rotates by ISO week number through config.CHALLENGES. Finishing it pays
config.COIN_CHALLENGE coins once per week (coin_ledger kind "challenge", ref = the week), through
coins.evaluate like every other coin. Only this week and last week are checked, so a missed payout
is caught by the next evaluation as long as it runs within a week.
"""

from datetime import datetime, timedelta

from . import config, db
from .progress import IST

WEEK_SQL = "to_char({col} AT TIME ZONE 'Asia/Kolkata', 'IYYY-\"W\"IW')"


def week_of(d: datetime) -> str:
    y, w, _ = d.astimezone(IST).isocalendar()
    return f"{y}-W{w:02d}"


def _active_weeks(c, user_id: int) -> set[str]:
    rows = c.all(f"SELECT {WEEK_SQL.format(col='passed_at')} AS w FROM lesson_progress "
                 "WHERE user_id=:u AND passed_at IS NOT NULL "
                 f"UNION SELECT {WEEK_SQL.format(col='closed_at')} FROM trade_results WHERE user_id=:u", u=user_id)
    return {r["w"] for r in rows}


def streak(c, user_id: int, now: datetime) -> dict:
    """Consecutive active weeks ending this week (or last week, while this one is still open)."""
    active = _active_weeks(c, user_id)
    this = week_of(now)
    d = now if this in active else now - timedelta(days=7)
    n = 0
    while week_of(d) in active:
        n += 1
        d -= timedelta(days=7)
    return {"weeks": n, "this_week": this in active}


def challenge_for(week: str) -> dict:
    """The challenge that runs in `week`: config.CHALLENGES in turn by ISO week number."""
    return config.CHALLENGES[int(week.split("-W")[1]) % len(config.CHALLENGES)]


def _count(c, user_id: int, kind: str, week: str) -> int:
    """How far the user is on a challenge kind within `week`."""
    if kind == "lesson":
        return c.value(f"SELECT count(*) FROM lesson_progress WHERE user_id=:u AND passed_at IS NOT NULL "
                       f"AND {WEEK_SQL.format(col='passed_at')} = :w", u=user_id, w=week)
    where = {
        "closed_sl": "had_sl",
        "low_delta": f"short AND entry_delta < {config.DELTA_MAX_ABS}",
        "profit_sl": "had_sl AND realized_pnl > 0",
    }[kind]
    return c.value(f"SELECT count(*) FROM trade_results WHERE user_id=:u AND {where} "
                   f"AND {WEEK_SQL.format(col='closed_at')} = :w", u=user_id, w=week)


def completed_weeks(c, user_id: int, now: datetime) -> list[str]:
    """This week and last week, where the user finished that week's challenge."""
    out = []
    for week in (week_of(now - timedelta(days=7)), week_of(now)):
        ch = challenge_for(week)
        if _count(c, user_id, ch["kind"], week) >= ch["target"]:
            out.append(week)
    return out


def get(user_id: int, _now: datetime | None = None) -> dict:
    """The streak and this week's challenge with live progress. Pays any challenge coins due first."""
    from . import coins
    coins.evaluate(user_id)
    now = _now or datetime.now(IST)  # `_now` is for tests only; clients can't set it
    week = week_of(now)
    ch = challenge_for(week)
    with db.tx(user_id) as c:
        done = _count(c, user_id, ch["kind"], week)
        out = {"streak": streak(c, user_id, now),
               "challenge": {"week": week, "label": ch["label"], "target": ch["target"],
                             "progress": min(done, ch["target"]), "done": done >= ch["target"],
                             "coins": config.COIN_CHALLENGE}}
    return out

