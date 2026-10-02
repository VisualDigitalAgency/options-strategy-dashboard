"""Virtual-account RMS (issue #178): orders that would push margin used to the warning level are
refused; at the square-off level waiting orders are cancelled and whole groups closed, largest
margin first, each order charged; nothing closes with the market shut; the end-of-day shortfall
penalty follows the exchange's bands and escalation; charges reduce value and return %."""
import sys
from datetime import date, timedelta

from engine import config, db, rms, virtual
from support import EXP, SYM, new_user, stub

fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def sell(uid, strike, lots=1, side="PE"):
    return virtual.place_order(uid, SYM, EXP, [{"side": side, "strike": strike, "action": "SELL", "lots": lots}])


stub(market=True)  # 1 lot = 100 qty; margin 1,000 per short unit, so 1 lot blocks ₹1 lakh

# 1. Orders that would push margin used to RMS_WARN_PCT are refused.
uid = new_user("rms@test.example", 200_000)
sell(uid, 900.0)
a = virtual.get_account(uid)
check("one lot: 50% used, status ok", a["margin_status"] == "ok" and a["margin_used_pct"] == 50.0, a["margin_used_pct"])
p = virtual.preview_order(uid, SYM, EXP, [{"side": "PE", "strike": 850.0, "action": "SELL", "lots": 1}])
check("second lot would be 100%: refused with the RMS reason", p["buy_rule"] and "limit 80%" in p["buy_rule"], p["buy_rule"])
p = virtual.preview_order(uid, SYM, EXP, [{"side": "PE", "strike": 900.0, "action": "BUY", "lots": 1}])
check("closing is never refused", not p["buy_rule"], p["buy_rule"])

# 2. Square-off: at RMS_SQUAREOFF_PCT the biggest group closes first, until under the warning level.
uid2 = new_user("rms2@test.example", 1_000_000)
sell(uid2, 900.0, lots=2)                                # ₹2 lakh group
virtual.place_order(uid2, "HDFCBANK", EXP, [{"side": "PE", "strike": 900.0, "action": "SELL", "lots": 1}])  # ₹1 lakh
with db.tx(uid2) as c:
    c.run("UPDATE accounts SET starting_capital = 310000 WHERE user_id=:u", u=uid2)  # ~97% used
check("flagged for square-off", virtual.get_account(uid2)["margin_status"] == "squareoff")
virtual.market_open = lambda: False
r = rms.check(uid2)
check("market shut: flagged, nothing closed", r["status"] == "squareoff" and not r["closed"], r)
virtual.market_open = lambda: True
r = rms.check(uid2)
check("largest-margin group closed first, then stops", [g["symbol"] for g in r["closed"]] == [SYM], r)
a = virtual.get_account(uid2)
check("back under the warning level", a["margin_status"] == "ok", a["margin_used_pct"])
with db.tx(uid2) as c:
    ch = c.all("SELECT kind, amount FROM account_charges WHERE user_id=:u", u=uid2)
    xp = c.value("SELECT COALESCE(SUM(points),0) FROM xp_ledger WHERE user_id=:u AND reason='rms_squareoff'", u=uid2)
    why = c.value("SELECT note FROM orders WHERE user_id=:u AND reason='rms_squareoff' LIMIT 1", u=uid2)
check("square-off charges: ₹50 per order", ch == [{"kind": "rms_charge", "amount": config.RMS_CHARGE}], ch)
check("XP penalty for the square-off", xp == config.XP_RMS_SQUAREOFF, xp)
check("the order history says why", why and why.startswith("RMS square-off"), why)
check("charges reduce account value", a["charges"] == config.RMS_CHARGE)

# 3. Waiting orders are cancelled before anything closes.
uid3 = new_user("rms3@test.example", 1_000_000)
sell(uid3, 900.0)
with db.tx(uid3) as c:
    c.run("INSERT INTO pending_orders (user_id, symbol, expiry, side, strike, action, qty, lot_size, limit_price,"
          " reason, sl_mode, valid_until, blocked_margin) VALUES (:u, :s, :e, 'CE', 1100, 'SELL', 100, 100, 50,"
          " 'manual', 'auto', now() + interval '1 day', 100000)", u=uid3, s=SYM, e=EXP)
    c.run("UPDATE accounts SET starting_capital = 150000 WHERE user_id=:u", u=uid3)
r = rms.check(uid3)
check("waiting orders cancelled first", r["cancelled"] == 1, r)

# 4. The end-of-day penalty: bands and escalation.
check("small shortfall: 0.5%", rms.penalty_rate(50_000, 1_000_000, 1, 1) == config.PENALTY_LOW_PCT)
check("large shortfall: 1%", rms.penalty_rate(150_000, 1_000_000, 1, 1) == config.PENALTY_PCT)
check("over 10% of the margin required: 1%", rms.penalty_rate(50_000, 200_000, 1, 1) == config.PENALTY_PCT)
check("short 4 days running: 5%", rms.penalty_rate(50_000, 1_000_000, 4, 4) == config.PENALTY_REPEAT_PCT)
check("short 6 days in a month: 5%", rms.penalty_rate(50_000, 1_000_000, 1, 6) == config.PENALTY_REPEAT_PCT)
uid4 = new_user("rms4@test.example", 1_000_000)
d = date(2026, 9, 10)  # a Thursday
with db.tx(uid4) as c:
    for back in (0, 1, 2, 3):  # Thu, Wed, Tue, Mon: four trading days running
        c.run("INSERT INTO margin_shortfalls (user_id, day, peak, required) VALUES (:u, :d, 20000, 1000000)",
              u=uid4, d=d - timedelta(days=back))
first = rms.apply_penalties(uid4, d - timedelta(days=3))
check("first day: 0.5% of ₹20k = ₹100", first and first["amount"] == 100.0, first)
last = rms.apply_penalties(uid4, d)
check("fourth day running: 5%", last and last["rate"] == config.PENALTY_REPEAT_PCT, last)
check("a penalty is charged once", rms.apply_penalties(uid4, d) is None)
check("no shortfall, no penalty", rms.apply_penalties(uid4, d + timedelta(days=1)) is None)
acct = virtual.get_account(uid4)
check("penalties reduce return %", acct["charges"] > 0 and acct["return_pct"] < 0, (acct["charges"], acct["return_pct"]))
check("charges listed newest first", rms.charges(uid4)[0]["kind"] == "margin_penalty")

# 5. Shortfall peak is recorded during the day.
uid5 = new_user("rms5@test.example", 1_000_000)
sell(uid5, 900.0)
with db.tx(uid5) as c:
    c.run("UPDATE accounts SET starting_capital = 80000 WHERE user_id=:u", u=uid5)
virtual.market_open = lambda: False
rms.check(uid5)
with db.tx(uid5) as c:
    peak = c.value("SELECT peak FROM margin_shortfalls WHERE user_id=:u", u=uid5)
check("peak shortfall recorded", peak and float(peak) > 0, peak)

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
