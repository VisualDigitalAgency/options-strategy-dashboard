"""Retention phase 1: the weekly streak, the weekly challenge paid once in coins, and the
day-before email nudges with their opt-out."""
import sys
from datetime import date, datetime, timedelta

from engine import auth, cache, coins, config, db, habits, mail, nudges
from engine.progress import IST
from support import new_user

fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def trade(uid, closed, had_sl=True, pnl=100, delta=0.1):
    with db.tx(uid) as c:
        c.run("INSERT INTO trade_results (user_id, symbol, expiry, side, strike, short, lots, avg_price, realized_pnl,"
              " capital, opened_at, closed_at, exit_reason, had_sl, entry_delta) VALUES (:u, 'SBIN', '2026-12-29', 'PE',"
              " 900, true, 1, 5, :p, 1000000, :t, :t, 'manual', :sl, :d)", u=uid, t=closed, p=pnl, sl=had_sl, d=delta)


now = datetime(2026, 10, 7, 12, 0, tzinfo=IST)  # a Wednesday, ISO week 41
uid = new_user("h@test.example", 1_000_000)

# 1. Streak: weeks 39 and 40 active, week 41 not yet: 2 weeks, kept while this week is open.
trade(uid, now - timedelta(days=14))
trade(uid, now - timedelta(days=7))
with db.tx(uid) as c:
    s = habits.streak(c, uid, now)
check("streak counts back from last week while this week is open", s == {"weeks": 2, "this_week": False}, s)
trade(uid, now)
with db.tx(uid) as c:
    s = habits.streak(c, uid, now)
check("activity this week extends it", s == {"weeks": 3, "this_week": True}, s)
with db.tx(uid) as c:
    s = habits.streak(c, uid, now + timedelta(days=14))
check("a whole empty week breaks it", s["weeks"] == 0, s)

# 2. Challenge: week 41 -> CHALLENGES[41 % 4] = "Pass a lesson quiz"; not done until a quiz is passed.
ch = habits.challenge_for(habits.week_of(now))
check("challenge rotates by ISO week", ch == config.CHALLENGES[41 % len(config.CHALLENGES)] and ch["kind"] == "lesson", ch)
with db.tx(uid) as c:
    check("not done yet", habits.completed_weeks(c, uid, now) == [])
    c.run("INSERT INTO lesson_progress (user_id, slug, attempts, best_score, passed_at) VALUES (:u, 'margin', 1, 100, :t)",
          u=uid, t=now)
with db.tx(uid) as c:
    done = habits.completed_weeks(c, uid, now)
check("finished challenge weeks found", habits.week_of(now) in done, done)
habits.datetime = type("D", (), {"now": staticmethod(lambda tz=None: now)})  # noqa: E731
coins.datetime = habits.datetime
paid = [x for x in coins.evaluate(uid) if x["kind"] == "challenge"]
check("challenge pays its coins", any(p["ref"] == habits.week_of(now) and p["coins"] == config.COIN_CHALLENGE for p in paid), paid)
check("paid once only", not [x for x in coins.evaluate(uid) if x["kind"] == "challenge"])
g = habits.get(uid, _now=now)
check("habits_get: streak and challenge progress", g["streak"]["weeks"] == 3 and g["challenge"]["done"], g)

# 3. Nudges: a short leg whose stop arms tomorrow, and one the time exit closes tomorrow.
today = date(2026, 10, 7)
tomorrow = today + timedelta(days=1)
exit_expiry = str(tomorrow + timedelta(days=config.TIME_EXIT_DTE - 1))
with db.tx(uid) as c:
    for sym, exp, sl_on in (("SBIN", "2026-12-29", tomorrow), ("INFY", exit_expiry, None)):
        c.run("INSERT INTO positions (user_id, symbol, expiry, side, strike, qty, avg_price, lot_size, sl_mode, sl_activates_on)"
              " VALUES (:u, :s, :e, 'PE', 900, -100, 5, 100, 'auto', :a)", u=uid, s=sym, e=exp, a=sl_on)
lines = nudges.items(uid, tomorrow)
check("nudge lines: stop arming and time exit", len(lines) == 2 and "stop-loss arms" in lines[1] and "time exit" in lines[0], lines)
sent = []
mail.send = lambda to, subject, text: sent.append((to, subject, text))
check("one email per user", nudges.send_all(today) == 1 and sent[0][0] == "h@test.example", sent)
check("not twice the same day", nudges.send_all(today) == 0 or not cache.up())
auth.set_prefs(uid, None, None, email_nudges=False)
check("opt-out: no lines", nudges.items(uid, tomorrow) == [])
check("opt-out shows in auth_me", auth.me(uid)["prefs"]["email_nudges"] is False)

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
