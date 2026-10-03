"""Virtual trading opens only after the Level 1 lesson quizzes are passed (everyone but the owner).
Closing or reducing a position is never blocked, and auto-trade skips every candidate until then."""
import sys

from engine import autotrade, db, lessons, users, virtual

fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def f(side, strike, action, lots=1):
    return {"side": side, "strike": float(strike), "action": action, "qty": lots * 100, "price": 5.0}


def pass_lessons(uid, slugs):
    with db.tx(uid) as c:
        for s in slugs:
            c.run("INSERT INTO lesson_progress (user_id, slug, attempts, best_score, last_attempt_at, passed_at) "
                  "VALUES (:u, :s, 1, 100, now(), now())", u=uid, s=s)


level1 = [l["slug"] for l in lessons.list_lessons() if l["level"] == 1]
new = users.create_user("new@test.example", "N", status="active")
owner = users.create_user("own@test.example", "O", role="owner", status="active")
spread = [f("PE", 900, "SELL"), f("PE", 880, "BUY")]

why = virtual.lessons_lock(new)
check("new account: locked, says how many passed", why and f"0/{len(level1)} passed" in why, why)
check("opening a trade is refused", virtual._lessons_rule(new, [], spread) == why)
held = [{"side": "PE", "strike": 900.0, "qty": -100, "avg_price": 5.0}]
check("closing a position is never blocked", virtual._lessons_rule(new, held, [f("PE", 900, "BUY")]) is None)
check("adding to a position is refused", virtual._lessons_rule(new, held, [f("PE", 900, "SELL")]) is not None)
check("the owner is never locked", virtual.lessons_lock(owner) is None)

pass_lessons(new, level1[:-1])
check("one quiz short: still locked", virtual.lessons_lock(new) is not None)
pass_lessons(new, level1[-1:])
check("every Level 1 quiz passed: unlocked", virtual.lessons_lock(new) is None)

# Auto-trade: every candidate is skipped with the reason while the account is locked.
locked = users.create_user("auto@test.example", "A", status="active")
virtual.get_account = lambda u: {"account_value": 1e6, "available_margin": 1e6}
virtual.get_positions = lambda u: {"groups": []}
cand = {"symbol": "SBIN", "expiry": "2026-12-29", "dte": 60, "legs": [{"side": "PE", "strike": 900.0}],
        "strategy": {"margin": 50000, "pop": 90, "roi_pct": 2.0}}
try:
    run = autotrade._run(locked, [cand], "manual")
    reasons = [s["reason"] for s in run["skipped"]]
    check("auto-trade skips while locked", not run["placed"] and reasons and "Level 1" in reasons[0], reasons)
except Exception as e:  # noqa: BLE001
    check("auto-trade skips while locked", False, repr(e))

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
