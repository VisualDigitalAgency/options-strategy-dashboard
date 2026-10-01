"""Learning-path progress (issue #122): entry delta saved on shorts, every closed leg logged to
trade_results and scored into the XP ledger (rules, penalties, capped profit bonus, quick flips score
nothing, never twice), metrics, level gates with minimum time, resets keep XP, RLS, and the RPC."""
import sys
from datetime import datetime, timedelta, timezone

import server
from engine import auth, config, db, lessons, progress, virtual
from support import EXP, new_user, stub

ORIGIN = "https://t.example"
server.ALLOWED_ORIGINS = {ORIGIN}
server.universe = lambda: ["SBIN"]
fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def ledger(uid):
    with db.tx(uid) as c:
        return c.all("SELECT points, reason, ref FROM xp_ledger WHERE user_id=:u ORDER BY id", u=uid)


def results(uid):
    with db.tx(uid) as c:
        return c.all("SELECT * FROM trade_results WHERE user_id=:u ORDER BY id", u=uid)


def sell(uid, strike, side="CE"):
    virtual.place_order(uid, "SBIN", EXP, [{"side": side, "strike": strike, "action": "SELL", "lots": 1}])
    with db.tx(uid) as c:
        return c.one("SELECT * FROM positions WHERE user_id=:u AND status='open' AND strike=:k AND side=:s",
                     u=uid, k=strike, s=side)


def age(uid, pid, days=1):
    with db.tx(uid) as c:
        c.run("UPDATE positions SET opened_at = now() - make_interval(days => :d) WHERE id=:i", d=days, i=pid)


stub(True)  # spot 1,000, IV 20%, bid 5.00 / ask 5.10
uid = new_user("learner@test.example", 1_000_000)

# 1. Entry delta is saved on short legs.
far = sell(uid, 1200.0)
check("far OTM short saves a small entry delta", far["entry_delta"] is not None and 0 < float(far["entry_delta"]) < 0.15,
      far["entry_delta"])

# 2. A disciplined short (stop-loss on, delta < 0.15), held a day, closed at a loss: logged and +20 only.
age(uid, far["id"])
virtual.exit_position(uid, far["id"])
r = results(uid)
check("closed leg logged", len(r) == 1 and r[0]["short"] and r[0]["had_sl"] and r[0]["lots"] == 1
      and r[0]["exit_reason"] == "manual" and float(r[0]["realized_pnl"]) < 0, r)
check("rule-following trade earns XP, no profit bonus on a loss",
      [(x["points"], x["reason"]) for x in ledger(uid)] == [(config.XP_TRADE_OK, "trade_ok")], ledger(uid))

# 3. Near the money with the stop-loss off: two penalties, no reward.
near = sell(uid, 1020.0)
check("near-the-money short saves a high delta", float(near["entry_delta"]) >= 0.15, near["entry_delta"])
virtual.set_sl_mode(uid, "off", near["id"])
age(uid, near["id"])
virtual.exit_position(uid, near["id"])
reasons = [x["reason"] for x in ledger(uid)][1:]
check("no stop-loss and high delta are both penalised", sorted(reasons) == ["high_delta", "no_sl"], ledger(uid))

# 4. Profitable disciplined leg: +20 and the profit bonus.
win = sell(uid, 1200.0)
age(uid, win["id"])
stub(True, bid=4.0)  # premium decayed: buy back below the ₹5 sold (tight spread, fills now)
virtual.exit_position(uid, win["id"])
last = [(x["points"], x["reason"]) for x in ledger(uid)][-2:]
check("profitable leg earns trade XP and the bonus", sorted(last) == sorted([(config.XP_TRADE_OK, "trade_ok"),
                                                                            (config.XP_PROFIT_BONUS, "profit_bonus")]), last)

# 5. Quick flips are logged but score nothing.
stub(True)
n = len(ledger(uid))
flip = sell(uid, 1200.0)
virtual.exit_position(uid, flip["id"])
check("quick flip logged", len(results(uid)) == 4)
check("quick flip scores nothing", len(ledger(uid)) == n, ledger(uid)[n:])

# 6. The same event never scores twice.
with db.tx(uid) as c:
    progress._award(c, uid, 20, "trade_ok", f"trade:{results(uid)[0]['id']}")
check("ledger refuses a duplicate award", len(ledger(uid)) == n)

# 7. Profit bonus is capped per month.
with db.tx(uid) as c:
    c.run("INSERT INTO xp_ledger (user_id, points, reason, ref) VALUES (:u, :p, 'profit_bonus', 'seed')",
          u=uid, p=config.XP_PROFIT_CAP - config.XP_PROFIT_BONUS)
win2 = sell(uid, 1200.0)
age(uid, win2["id"])
stub(True, bid=4.0)
virtual.exit_position(uid, win2["id"])
stub(True)
with db.tx(uid) as c:
    bonus = c.value("SELECT SUM(points) FROM xp_ledger WHERE user_id=:u AND reason='profit_bonus'", u=uid)
check("monthly profit bonus stops at the cap", bonus == config.XP_PROFIT_CAP, bonus)

# 8. Metrics.
t = [{"capital": 100_000, "realized_pnl": p} for p in (2000, -3000, 1000, 4000)]
m = progress.metrics(t)
check("return %", m["return_pct"] == 4.0, m)
check("max drawdown on the equity curve", m["max_dd_pct"] == round(3000 / 102_000 * 100, 2), m)
check("return ÷ drawdown and win rate", m["ret_dd"] == round(4.0 / m["max_dd_pct"], 2) and m["win_rate"] == 75.0, m)
check("clean record doesn't divide by zero", progress.metrics([{"capital": 100_000, "realized_pnl": 500}])["ret_dd"] == 0.5)
now = datetime(2026, 10, 15, tzinfo=timezone.utc)
streak_trades = [{"month": mo, "realized_pnl": p} for mo, p in (("2026-07", 100), ("2026-08", 50), ("2026-09", 10), ("2026-10", -999))]
check("profitable-month streak counts complete months", progress._profitable_streak(streak_trades, now) == 3)

# 9. Levels: XP, minimum time and the gate all have to pass; one step at a time.
lv = new_user("climber@test.example", 1_000_000)
with db.tx(lv) as c:
    for l in lessons.list_lessons():
        if l["level"] == 1:
            c.run("INSERT INTO lesson_progress (user_id, slug, attempts, best_score, passed_at) VALUES (:u, :s, 1, 100, now())",
                  u=lv, s=l["slug"])
    for i in range(5):
        c.run("INSERT INTO trade_results (user_id, symbol, expiry, side, strike, short, lots, avg_price, realized_pnl,"
              " capital, opened_at, exit_reason, had_sl, entry_delta) VALUES (:u, 'SBIN', :e, 'CE', 1200, true, 1, 5, 100,"
              " 1000000, now(), 'manual', true, 0.05)", u=lv, e=EXP)
    c.run("INSERT INTO xp_ledger (user_id, points, reason, ref) VALUES (:u, 60, 'seed', 'seed')", u=lv)
s = progress.evaluate(lv)
check("lesson passes score XP once", sum(x["points"] for x in ledger(lv) if x["reason"] == "lesson") == 4 * config.XP_LESSON)
check("starts at Level 1 Learner", s["level"] == 1 and s["title"] == "Learner" and s["xp"] == 100, s)
checks = {ch["label"]: ch["ok"] for ch in s["next"]["checks"]}
check("XP and gate met, but not the minimum time", checks["100 XP"] and not checks["60 days at this level"]
      and checks["Pass every Level 1 lesson quiz"] and checks["Close 5 trades"] and not s["next"]["ready"], checks)
s = progress.evaluate(lv, _now=datetime.now(timezone.utc) + timedelta(days=61))
check("after 60 days: Level 2 Apprentice", s["leveled_up"] == 2 and s["level"] == 2 and s["title"] == "Apprentice", s)
check("next level reports its XP band and days for the progress page",
      s["next"]["xp_from"] == 100 and s["next"]["xp_needed"] == 400 and s["next"]["days"] == 0 and s["next"]["min_days"] == 60, s["next"])
check("auth_me carries the level for the nav badge", auth.me(lv)["level"] == 2)
s = progress.evaluate(lv, _now=datetime.now(timezone.utc) + timedelta(days=200))
check("no second jump: Level 2's own gate isn't met", s["level"] == 2 and not s["next"]["ready"], s["next"])
with db.tx() as c:
    up = c.one("SELECT detail FROM audit_log WHERE action='level_up' AND target_user_id=:u", u=lv)
check("level-up audited", up and up["detail"]["level"] == 2, up)

# 10. A reset restarts the gate but keeps XP and the trade log.
xp_before = progress.evaluate(uid)["xp"]
virtual.reset(uid)
s = progress.evaluate(uid)
check("reset keeps XP", s["xp"] == xp_before, (xp_before, s["xp"]))
check("reset keeps the trade log", len(results(uid)) == 5)
check("reset restarts the gate's trade count", s["metrics"]["trades"] == 0, s["metrics"])

# 11. Level 6's gate has real checks now (#146; the details are in test_gates.py).
with db.tx(lv) as c:
    c.run("UPDATE user_levels SET level=6 WHERE user_id=:u", u=lv)
s = progress.evaluate(lv, _now=datetime.now(timezone.utc) + timedelta(days=400))
labels = [ch["label"] for ch in s["next"]["checks"]]
check("Level 6 gate: volatile month and the Adjustments course", s["level"] == 6 and not s["next"]["ready"]
      and any("volatile month" in x for x in labels) and any("Adjustments" in x for x in labels), labels)

# 12. Privacy and the RPC.
other = new_user("other@test.example", 1_000_000)
with db.tx(other) as c:
    seen = c.all("SELECT * FROM trade_results") + c.all("SELECT * FROM xp_ledger")
check("RLS hides other users' log and XP", seen == [], seen)
app = server.app.test_client()
app.set_cookie(server.COOKIE, auth.new_session(uid, "127.0.0.1", "t"), domain="localhost")


def call(method, params=None):
    return app.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                    headers={"Origin": ORIGIN}).get_json()


r = call("progress_get")
check("progress_get returns level, XP and next checks", "result" in r and r["result"]["level"] == 1 and r["result"]["next"]["checks"], r)
r = call("progress_get", {"_now": "2030-01-01T00:00:00Z"})
check("client can't move the clock", r.get("error", {}).get("code") == -32602, r)
r = call("progress_history", {"limit": 3})
check("progress_history lists the newest XP entries", "result" in r and len(r["result"]) == 3, r)

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
