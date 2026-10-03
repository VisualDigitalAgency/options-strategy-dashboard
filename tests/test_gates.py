"""Gates for Levels 6-10 (issue #146), each against hand-built trade histories: the volatile month
and stop-loss discipline, the Adjustments course, profitable-month windows, 12-month drawdown and
return/drawdown, top-20% finished leaderboards, mentees, the track record, and the owner-only
Level 10 sign-off."""
import sys
from datetime import datetime, timedelta, timezone

import server
from engine import auth, cache, config, db, lessons, nifty, permissions, progress, users
from support import EXP

ORIGIN = "https://t.example"
server.ALLOWED_ORIGINS = {ORIGIN}
fails = []
NOW = datetime.now(timezone.utc)


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def month(k: int) -> datetime:
    """The 15th of the month k months before this one (IST months)."""
    d = NOW.astimezone(progress.IST).replace(day=15, hour=12)
    for _ in range(k):
        d = (d.replace(day=1) - timedelta(days=1)).replace(day=15)
    return d


def person(email, level, role="user", referred_by=None):
    uid = users.create_user(email, email.split("@")[0], role=role, status="active")
    with db.tx() as c:
        c.run("UPDATE users SET referred_by=:r WHERE id=:u", r=referred_by, u=uid)
    with db.tx(uid) as c:
        c.run("UPDATE accounts SET created_at=:t WHERE user_id=:u", t=NOW - timedelta(days=900), u=uid)
        c.run("INSERT INTO user_levels (user_id, level, level_since) VALUES (:u, :l, :s) ON CONFLICT (user_id) "
              "DO UPDATE SET level=:l, level_since=:s", u=uid, l=level, s=NOW - timedelta(days=400))
    return uid


def trade(uid, when, pnl, had_sl=True, short=True, alert=None):
    with db.tx(uid) as c:
        pid = None
        if alert is not None:  # a position whose stop alert fired `alert` days before the close
            pid = c.value("INSERT INTO positions (user_id, symbol, expiry, side, strike, qty, avg_price, lot_size, status,"
                          " sl_alert_at) VALUES (:u, 'SBIN', :e, 'CE', 1200, 0, 5, 100, 'closed', :a) RETURNING id",
                          u=uid, e=EXP, a=when - timedelta(days=alert))
        c.run("INSERT INTO trade_results (user_id, position_id, symbol, expiry, side, strike, short, lots, avg_price,"
              " realized_pnl, capital, opened_at, closed_at, exit_reason, had_sl, entry_delta) VALUES (:u, :p, 'SBIN', :e,"
              " 'CE', 1200, :sh, 1, 5, :pnl, 1000000, :o, :c, 'manual', :sl, 0.05)",
              u=uid, p=pid, e=EXP, sh=short, pnl=pnl, o=when - timedelta(days=2), c=when, sl=had_sl)


def checks(uid):
    with db.tx(uid) as c:
        snap = progress._snapshot(c, uid, NOW)
    return {ch["label"]: (ch["ok"], ch["value"]) for ch in snap["next"]["checks"]}


def find(cs, word):
    return next(v for k, v in cs.items() if word in k)


# ---------- Nifty months from daily prices ----------
import pandas as pd  # noqa: E402
days = pd.DataFrame({"Open": [100.0, 101.0, 99.0], "High": [102.0, 104.0, 100.0], "Low": [98.0, 100.0, 97.0]},
                    index=pd.to_datetime(["2026-08-03", "2026-08-20", "2026-09-01"]))
mm = nifty.months_from(days)
check("monthly range: first open, highest high, lowest low", mm["2026-08"] == {"open": 100.0, "high": 104.0, "low": 98.0,
      "swing_pct": 6.0} and mm["2026-09"]["swing_pct"] == 3.03, mm)

# ---------- Level 6: volatile month, no stop broken, Adjustments course ----------
a = person("l6a@test.example", 6)
check("no Nifty data yet: says so, not passed", find(checks(a), "volatile") == (False, "Nifty data not loaded yet"))
cache.set_json(nifty.KEY, {"fetched_at": 0, "months": {
    month(1).strftime("%Y-%m"): {"swing_pct": 1.5}, month(2).strftime("%Y-%m"): {"swing_pct": 4.2},
    month(3).strftime("%Y-%m"): {"swing_pct": 3.1}}})
trade(a, month(1), 500)                       # calm month: doesn't count
trade(a, month(2), -200, had_sl=False)         # volatile month, stop off: broken
check("volatile month with a stop off doesn't pass", find(checks(a), "volatile")[0] is False, find(checks(a), "volatile"))
trade(a, month(3), 300, alert=0.5)             # alert answered within the day: fine
check("an earlier volatile month with discipline passes", find(checks(a), "volatile") == (True, f"{month(3):%Y-%m} (Nifty 3.1%)"),
      find(checks(a), "volatile"))
b = person("l6b@test.example", 6)
trade(b, month(2), 300, alert=3)               # alert ignored for 3 days
check("an ignored stop alert is a breach", find(checks(b), "volatile")[0] is False)
check("Adjustments course needs the 3 Level 6 lessons", find(checks(a), "Adjustments") == (False, "0/3"))
with db.tx(a) as c:
    for l in lessons.list_lessons():
        if l["level"] == 6:
            c.run("INSERT INTO lesson_progress (user_id, slug, attempts, best_score, passed_at) VALUES (:u, :s, 1, 100, now())",
                  u=a, s=l["slug"])
check("...and passes once they're done", find(checks(a), "Adjustments") == (True, "3/3"))

# ---------- Level 7: 6 profitable months of the last 8, drawdown <= 10% ----------
s7 = person("l7@test.example", 7)
for k, pnl in zip(range(1, 9), (1000, 1000, -400, 1000, 1000, -400, 1000, 1000)):
    trade(s7, month(k), pnl)
trade(s7, month(10), -900000)                  # outside the 8-month window: ignored
cs = checks(s7)
check("6/8 profitable months passes", find(cs, "profitable") == (True, "6/8"), find(cs, "profitable"))
check("drawdown inside the window is small", find(cs, "drawdown")[0] is True, find(cs, "drawdown"))
f7 = person("l7f@test.example", 7)
for k, pnl in zip(range(1, 9), (1000, -1, 1000, -1, 1000, 1000, -1, 1000)):
    trade(f7, month(k), pnl)
check("5/8 doesn't", find(checks(f7), "profitable") == (False, "5/8"))
d7 = person("l7d@test.example", 7)
for k, pnl in zip(range(1, 9), (1000, 1000, 1000, -150000, 1000, 1000, 1000, 1000)):
    trade(d7, month(k), pnl)
check("a 15% drawdown fails the 10% limit", find(checks(d7), "drawdown")[0] is False, find(checks(d7), "drawdown"))

# ---------- Level 8: 12-month return/drawdown >= 2, top 20% twice ----------
s8 = person("l8@test.example", 8)
for k, pnl in ((1, 30000), (2, -20000), (3, 30000)):   # +4% with a 2% drawdown: 2.0
    trade(s8, month(k), pnl)
trade(s8, month(14), 500000)                            # older than 12 months: ignored
check("12-month return/drawdown passes (4% over a 1.94% drawdown from the peak)", find(checks(s8), "Return") == (True, 2.06), find(checks(s8), "Return"))
with db.tx() as c:
    def board(m, size, rank_of_s8):
        for r in range(1, size + 1):
            c.run("INSERT INTO leaderboard_entries (month, band, rank, user_id, nickname, level, ratio, return_pct,"
                  " max_dd_pct, trades, win_rate) VALUES (:m, '7-10', :r, :u, :n, 8, 1, 1, 1, 5, 50)",
                  m=m, r=r, u=s8 if r == rank_of_s8 else None, n=f"p{r}")
    board("2026-01", 10, 3)       # 3rd of 10: not top 20%
    board("2026-02", 5, 1)        # 1st of 5: top 20%
check("one top-20% board isn't enough", find(checks(s8), "Top") == (False, 1))
with db.tx() as c:
    board("2026-03", 7, 2)        # 2nd of 7: top 20% rounds up to 2
check("two are", find(checks(s8), "Top") == (True, 2))

# ---------- Level 9 -> 10: 9/12 months, drawdown, mentees, track record, owner sign-off ----------
s9 = person("l9@test.example", 9)
for k in range(1, 13):
    trade(s9, month(k), -100 if k in (2, 5, 8) else 1000)
trade(s9, month(19), 100)                                # 19 months of track record
with db.tx(s9) as c:
    c.run("INSERT INTO xp_ledger (user_id, points, reason, ref) VALUES (:u, 8100, 'seed', 'seed')", u=s9)
for i in range(3):
    m = person(f"mentee{i}@test.example", 3 if i < 2 else 1, referred_by=s9)
cs = checks(s9)
check("9/12 profitable months", find(cs, "profitable") == (True, "9/12"), find(cs, "profitable"))
check("track record of 18+ months", find(cs, "track record")[0] is True, find(cs, "track record"))
check("2 of 3 mentees at Level 3 isn't enough", find(cs, "invited") == (False, 2))
check("not ready for the owner yet", progress.final_ready(s9) is False)
with db.tx(m) as c:
    c.run("UPDATE user_levels SET level=3 WHERE user_id=:u", u=m)
check("third mentee at Level 3", find(checks(s9), "invited") == (True, 3))
check("waiting only on the owner", progress.final_ready(s9) is True and find(checks(s9), "Final") == (False, "Waiting"))

owner = users.create_user("owner@test.example", "Owner", role="owner", status="active")
sub = users.create_user("sub@test.example", "Sub", role="sub_admin", status="active")


def rpc(uid, method, params=None):
    c = server.app.test_client()
    c.set_cookie(server.COOKIE, auth.new_session(uid, "10.0.0.9", "ua"), domain="localhost")
    return c.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                  headers={"Origin": ORIGIN}).get_json()


r = rpc(sub, "admin_approve_final", {"target_id": s9})
check("a sub-admin can't approve Level 10", r.get("error", {}).get("code") == server.FORBIDDEN, r)
listed = {u["id"]: u for u in rpc(owner, "admin_list_users")["result"]}
check("Admin list flags who waits for sign-off", listed[s9]["final_ready"] and not listed[s7]["final_ready"])
check("Admin list: level and the Level 8 real-trading tag (#120)", listed[s9]["level"] == 9 and listed[s9]["live_eligible"]
      and listed[s7]["level"] == 7 and not listed[s7]["live_eligible"], (listed[s9]["level"], listed[s7]["level"]))
check("the tag never grants real trading", not permissions.user_allowed({"id": s9, "role": "user"}, "live_trading"))
r = rpc(owner, "admin_approve_final", {"target_id": s7})
check("approving someone not ready is refused", "error" in r, r)
r = rpc(owner, "admin_approve_final", {"target_id": s9})
check("owner sign-off moves them to Level 10", r.get("result", {}).get("level") == 10
      and r["result"]["title"] == config.LEVEL_TITLES[10], r.get("result", {}).get("level"))
with db.tx() as c:
    check("sign-off audited", c.value("SELECT count(*) FROM audit_log WHERE action='final_assessment_approved' "
                                      "AND target_user_id=:u", u=s9) == 1)

sys.exit(1 if fails else 0)
