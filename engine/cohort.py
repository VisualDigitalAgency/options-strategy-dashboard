"""Signup cohorts (retention plan, phase 2): everyone who joined in the same ISO week (IST).

My progress shows the user's cohort: how many joined that week and where each level stands, so
progress is measured against peers who started together rather than a distant top ten. Counts only:
never a name, a nickname or a number about anyone else.
"""

from . import db

WEEK = "to_char(created_at AT TIME ZONE 'Asia/Kolkata', 'IYYY-\"W\"IW')"


def get(user_id: int) -> dict:
    """The caller's cohort: its week, size, how many are at each level, and how many are ahead."""
    with db.tx() as c:
        week = c.value(f"SELECT {WEEK} FROM users WHERE id=:u", u=user_id)
        ids = [r["id"] for r in c.all(f"SELECT id FROM users WHERE status = 'active' AND {WEEK} = :w", w=week)]
    levels = {}
    for uid in ids:  # user_levels is per-user under RLS
        with db.tx(uid) as c:
            levels[uid] = c.value("SELECT level FROM user_levels WHERE user_id=:u", u=uid) or 1
    mine = levels.get(user_id, 1)
    by_level = {}
    for lv in levels.values():
        by_level[lv] = by_level.get(lv, 0) + 1
    return {"week": week, "size": len(ids), "level": mine,
            "levels": [{"level": lv, "count": n} for lv, n in sorted(by_level.items())],
            "ahead": sum(1 for lv in levels.values() if lv > mine)}
