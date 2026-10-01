"""Coins (issue #47): earned on top of capital grants, each paid once; disciplined profitable trades
only, capped per month; XP milestones; one-way exchange into capital that survives a reset."""
import sys

from engine import coins, config, db, lessons, users, virtual

fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def bal(uid):
    with db.tx(uid) as c:
        return coins.balance(c, uid)


def cap(uid):
    with db.tx(uid) as c:
        return float(c.value("SELECT starting_capital FROM accounts WHERE user_id=:u", u=uid))


def trade(uid, pnl=1000.0, sl=True, delta=0.1, days=10):
    with db.tx(uid) as c:
        c.run("INSERT INTO trade_results (user_id, symbol, expiry, side, strike, short, lots, avg_price, realized_pnl,"
              " capital, opened_at, closed_at, exit_reason, had_sl, entry_delta) VALUES (:u,'SBIN','2026-12-29','CE',900,"
              " true, 1, 5, :p, 200000, now() - make_interval(days => :d), now(), 'expiry', :sl, :dl)",
              u=uid, p=pnl, d=days, sl=sl, dl=delta)


uid = users.create_user("coin@test.example", "Coin", status="active")
check("starts with no coins", coins.evaluate(uid) == [] and bal(uid) == 0)

with db.tx(uid) as c:
    for l in lessons.list_lessons():
        if l["level"] == 1:
            c.run("INSERT INTO lesson_progress (user_id, slug, attempts, best_score, passed_at, last_attempt_at) "
                  "VALUES (:u, :s, 1, 100, now(), now())", u=uid, s=l["slug"])
coins.status(uid)  # runs capital grants then coins
check("a task pays coins on top of capital", bal(uid) == config.COIN_TASKS["l1_lessons"][0]
      and cap(uid) == config.STARTING_CAPITAL + config.CAPITAL_TASKS["l1_lessons"][0], (bal(uid), cap(uid)))

before = bal(uid)
trade(uid)                      # qualifies
trade(uid, sl=False)            # stop-loss off
trade(uid, delta=0.2)           # sold too close
trade(uid, days=2)              # closed too soon
trade(uid, pnl=100)             # profit too small
got = [g for g in coins.evaluate(uid) if g["kind"] == "trade"]
check("only the disciplined profitable trade pays", len(got) == 1 and got[0]["coins"] == config.COIN_TRADE, got)
for _ in range(config.COIN_TRADE_PER_MONTH + 3):
    trade(uid)
paid = [g for g in coins.evaluate(uid) if g["kind"] == "trade"]
check("trade coins capped per month", len(paid) == config.COIN_TRADE_PER_MONTH - 1, len(paid))
check("paid once only", coins.evaluate(uid) == [])

with db.tx(uid) as c:
    c.run("INSERT INTO xp_ledger (user_id, points, reason, ref) VALUES (:u, 600, 'seed', 'seed')", u=uid)
got = [g for g in coins.evaluate(uid) if g["kind"] == "xp"]
check("every 250 XP pays", len(got) >= 2 and all(g["coins"] == config.COIN_XP for g in got), got)

# Exchange: one way, into capital, kept by a reset, not profit.
have, c0 = bal(uid), cap(uid)
r = coins.exchange(uid, 10)
check("exchange moves coins into capital", r["rupees"] == 10 * config.COIN_RUPEES and bal(uid) == have - 10
      and cap(uid) == c0 + 10 * config.COIN_RUPEES, (r, cap(uid)))
for bad in (0, -5, have + 1000):
    try:
        coins.exchange(uid, bad)
        check(f"exchange of {bad} refused", False)
    except coins.CoinError:
        check(f"exchange of {bad} refused", True)
check("return % ignores exchanged capital", virtual.get_account(uid)["return_pct"] == 0.0)
earned = cap(uid)
virtual.reset(uid)
check("reset keeps exchanged capital", cap(uid) == earned, (cap(uid), earned))
check("an exchange is never re-credited", coins.evaluate(uid) == [] and bal(uid) == have - 10)

s = coins.status(uid)
check("status: balance, rate, rules and history", s["balance"] == bal(uid) and s["rupees_per_coin"] == config.COIN_RUPEES
      and any(r["key"] == "trade" for r in s["rules"]) and s["history"], s["rules"][-2])
other = users.create_user("coin2@test.example", "Other", status="active")
with db.tx(other) as c:
    check("ledger is private (RLS)", c.all("SELECT * FROM coin_ledger WHERE user_id=:u", u=uid) == [])

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
