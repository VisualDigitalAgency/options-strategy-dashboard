"""Monthly recap email (retention plan, phase 2).

When the worker freezes a month's leaderboard, each active user who closed a trade or earned XP that
month gets one email: trades closed, discipline score, XP earned, level now, and a season title if
they won one. It follows the same opt-out as the day-before nudges (user_prefs.email_nudges). A
Redis key per user and month stops a second copy when the worker restarts.
"""

import logging
from datetime import datetime

from . import cache, config, db, leaderboard, mail, users

log = logging.getLogger("theta.recap")
MONTH_SQL = "to_char({col} AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM') = :m"


def summary(user_id: int, month: str) -> dict | None:
    """The month's numbers for one user, or None when there is nothing to report or they opted out."""
    with db.tx(user_id) as c:
        if c.value("SELECT email_nudges FROM user_prefs WHERE user_id=:u", u=user_id) is False:
            return None
        legs = c.all(f"SELECT had_sl, short, entry_delta FROM trade_results WHERE user_id=:u AND {MONTH_SQL.format(col='closed_at')}",
                     u=user_id, m=month)
        xp = c.value(f"SELECT COALESCE(SUM(points), 0) FROM xp_ledger WHERE user_id=:u AND {MONTH_SQL.format(col='ts')}",
                     u=user_id, m=month)
        level = c.value("SELECT level FROM user_levels WHERE user_id=:u", u=user_id) or 1
    if not legs and not xp:
        return None
    won = [t["band"] for t in leaderboard.titles(user_id) if t["month"] == month]
    return {"trades": len(legs), "discipline": leaderboard.discipline(legs), "xp": int(xp), "level": level,
            "title": config.LEVEL_TITLES[level], "champion": won[0] if won else None}


def body(name: str, month: str, s: dict) -> str:
    nice = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
    lines = [f"Hi {name},", "", f"Your {nice} on the virtual account:", "",
             f"- Trades closed: {s['trades']}",
             f"- Discipline score: {s['discipline']}/100 (stop-loss on, delta below {config.DELTA_MAX_ABS})",
             f"- XP earned: {s['xp']:+d}",
             f"- Level now: {s['level']} · {s['title']}"]
    if s["champion"]:
        lines.append(f"- Season champion of {s['champion']}: {config.CHAMPION_PRO_MONTHS} month(s) of Pro on us. "
                     "Share your certificate from My progress.")
    return "\n".join([*lines, "", "A new month starts today. Turn these emails off on My progress.",
                      "", "Paper trading, educational."])


def send_all(month: str) -> int:
    """Emails every active user with something to report for `month`. Returns how many were sent."""
    sent = 0
    for uid in users.active_user_ids():
        key = f"recap:{uid}:{month}"
        if cache.exists(key):
            continue
        try:
            s = summary(uid, month)
            if not s:
                continue
            with db.tx() as c:
                u = c.one("SELECT email, name FROM users WHERE id=:u", u=uid)
            mail.send(u["email"], f"Your {datetime.strptime(month, '%Y-%m').strftime('%B')} recap", body(u["name"], month, s))
            cache.set_json(key, 1, ttl=40 * 86400)
            sent += 1
        except Exception:
            log.exception("recap for user %s failed", uid)
    return sent
