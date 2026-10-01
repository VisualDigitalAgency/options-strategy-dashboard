"""Virtual capital milestones (issue #47): ₹2 lakh start, tasks pay once, a reset keeps what was
earned and never takes a chosen amount, and earned capital never shows as profit."""
import sys

from engine import capital, config, db, lessons, users, virtual
from support import new_user

fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def cap(uid):
    with db.tx(uid) as c:
        return float(c.value("SELECT starting_capital FROM accounts WHERE user_id=:u", u=uid))


def trade(uid, pnl=1000.0, sl=True, delta=0.1, months_ago=0):
    with db.tx(uid) as c:
        c.run("INSERT INTO trade_results (user_id, symbol, expiry, side, strike, short, lots, avg_price, realized_pnl,"
              " capital, opened_at, closed_at, exit_reason, had_sl, entry_delta) VALUES (:u,'SBIN','2026-12-29','CE',900,"
              " true, 1, 5, :p, 200000, now() - make_interval(months => :m), now() - make_interval(months => :m),"
              " 'expiry', :sl, :d)", u=uid, p=pnl, m=months_ago, sl=sl, d=delta)


def passes(uid, level):
    with db.tx(uid) as c:
        for l in lessons.list_lessons():
            if l["level"] == level:
                c.run("INSERT INTO lesson_progress (user_id, slug, attempts, best_score, passed_at, last_attempt_at) "
                      "VALUES (:u, :s, 1, 100, now(), now()) ON CONFLICT DO NOTHING", u=uid, s=l["slug"])


uid = users.create_user("cap@test.example", "Cap", status="active")
check("new account starts at ₹2 lakh", cap(uid) == 200_000 == config.STARTING_CAPITAL, cap(uid))
check("nothing paid for nothing", capital.evaluate(uid) == [] and cap(uid) == 200_000)

passes(uid, 1)
got = capital.evaluate(uid)
check("Level 1 lessons pay +₹25k", [g["task"] for g in got] == ["l1_lessons"] and cap(uid) == 225_000, got)
check("paid once only", capital.evaluate(uid) == [] and cap(uid) == 225_000)

for _ in range(4):
    trade(uid)
trade(uid, sl=False)
got = {g["task"] for g in capital.evaluate(uid)}
check("first stop-loss trade pays; 5 trades with one stop-loss off doesn't", got == {"first_sl_trade"}, got)

uid2 = new_user("cap2@test.example", 200_000)
with db.tx(uid2) as c:
    c.run("UPDATE accounts SET base_capital=200000 WHERE user_id=:u", u=uid2)
for _ in range(5):
    trade(uid2)
trade(uid2, months_ago=1)
got = {g["task"]: g for g in capital.evaluate(uid2)}
check("5 trades all with stop-loss pay", "five_sl_trades" in got, list(got))
check("a past profitable month pays; the running month doesn't", "profit_month" in got and got["profit_month"]["ref"] < "9999"
      and sum(1 for t in got if t == "profit_month") == 1, got.get("profit_month"))

# Levels pay what config says, once per level reached.
with db.tx(uid) as c:
    c.run("INSERT INTO user_levels (user_id, level, level_since) VALUES (:u, 3, now()) "
          "ON CONFLICT (user_id) DO UPDATE SET level = 3", u=uid)
before = cap(uid)
got = sorted(g["ref"] for g in capital.evaluate(uid) if g["task"] == "level")
check("Levels 2 and 3 pay their amounts", got == ["2", "3"] and cap(uid) == before + 100_000 + 150_000, (got, cap(uid)))

# Earned capital is not profit.
acct = virtual.get_account(uid)
check("return % ignores earned capital", acct["return_pct"] == 0.0, acct["return_pct"])

# Reset: base plus everything earned, never a chosen amount.
earned = cap(uid)
virtual.reset(uid)
check("reset restarts with base + grants", cap(uid) == earned, (cap(uid), earned))
try:
    virtual.reset(uid, starting_capital=10_000_000)
    check("reset refuses a chosen amount", False)
except TypeError:
    check("reset refuses a chosen amount", True)
check("grants survive a reset and are not paid again", capital.evaluate(uid) == [] and cap(uid) == earned)

# Invites: a verified invitee who trades pays the inviter; their rows stay private.
inv = users.create_user("inv@test.example", "Inv", status="active")
with db.tx() as c:
    c.run("UPDATE users SET referred_by=:r, email_verified_at=now() WHERE id=:u", r=uid, u=inv)
check("an invitee without a trade pays nothing", not [g for g in capital.evaluate(uid) if g["task"] == "invite_trades"])
trade(inv)
got = [g for g in capital.evaluate(uid) if g["task"] == "invite_trades"]
check("an invitee's first trade pays the inviter", len(got) == 1 and got[0]["amount"] == 50_000, got)

# Status for the page.
s = capital.status(uid)
check("status lists tasks, levels and grants", s["capital"] == cap(uid) and len(s["tasks"]) == len(config.CAPITAL_TASKS)
      and s["grants"] and any(t["key"] == "l1_lessons" and t["done"] == 1 for t in s["tasks"]), s["tasks"][0])
with db.tx(uid2) as c:
    check("grants are private (RLS)", c.all("SELECT * FROM capital_grants WHERE user_id=:u", u=uid) == [])

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
