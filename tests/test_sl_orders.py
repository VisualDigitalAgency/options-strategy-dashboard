"""Stop-loss orders (issue #183): SL-M and SL on an open leg, triggered by the monitor; wrong-side
triggers refused; one stop per leg; nothing fires with the market shut; the day-15 group stop
leaves a leg with its own stop alone; an Exit replaces the stop."""
import sys

from engine import db, virtual
from support import EXP, SYM, new_user, stub

fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def price(bid, ask=None, ltp=None):
    ask = bid + 0.1 if ask is None else ask
    virtual.quote = lambda s, e, side, k: {"spot": 1000.0, "ltp": ltp or bid, "bid": bid, "ask": ask, "iv": 20.0, "oi": 10_000}


def short(uid, strike=900.0):
    virtual.place_order(uid, SYM, EXP, [{"side": "PE", "strike": strike, "action": "SELL", "lots": 1}])
    with db.tx(uid) as c:
        return c.value("SELECT id FROM positions WHERE user_id=:u AND strike=:k AND status='open'", u=uid, k=strike)


def status(uid, oid):
    with db.tx(uid) as c:
        return c.one("SELECT status, fill_price, triggered_at FROM pending_orders WHERE id=:i AND user_id=:u", i=oid, u=uid)


def is_open(uid, pid):
    with db.tx(uid) as c:
        return c.value("SELECT status FROM positions WHERE id=:i AND user_id=:u", i=pid, u=uid) == "open"


stub(market=True)
uid = new_user("sl@test.example", 1_000_000)
price(5.0)
pid = short(uid)

# 1. Placing: wrong side refused, one per leg.
for bad, why in ((4.0, "below the price for a sold leg"), (5.0, "at the price")):
    try:
        virtual.place_stop(uid, pid, bad)
        check(f"trigger {why} refused", False)
    except ValueError as e:
        check(f"trigger {why} refused", "above the current price" in str(e), e)
r = virtual.place_stop(uid, pid, 8.0)
check("SL-M on a sold leg: a BUY stop", r["action"] == "BUY" and r["trigger"] == 8.0, r)
try:
    virtual.place_stop(uid, pid, 9.0)
    check("a second stop on the same leg refused", False)
except ValueError as e:
    check("a second stop on the same leg refused", "already has a stop-loss" in str(e), e)
oo = virtual.get_open_orders(uid)
check("listed with its type and trigger", oo[0]["order_type"] == "slm" and oo[0]["trigger_price"] == 8.0, oo[0])

# 2. Not triggered below the trigger, or with the market shut.
price(7.0)
virtual.match_pending(uid)
check("below the trigger: waits", status(uid, r["order_id"])["status"] == "open" and is_open(uid, pid))
price(9.0)
virtual.market_open = lambda: False
virtual.match_pending(uid)
check("market shut: nothing fires", status(uid, r["order_id"])["status"] == "open")
virtual.market_open = lambda: True
virtual.match_pending(uid)
st = status(uid, r["order_id"])
check("SL-M triggered: filled at the ask, leg closed", st["status"] == "filled" and st["fill_price"] == 9.1
      and not is_open(uid, pid), st)
with db.tx(uid) as c:
    reason = c.value("SELECT reason FROM orders WHERE user_id=:u ORDER BY id DESC LIMIT 1", u=uid)
check("order history says it was the stop", reason == "sl_order", reason)

# 3. SL: triggers into a limit that may wait.
price(5.0)
pid2 = short(uid, 850.0)
try:
    virtual.place_stop(uid, pid2, 8.0, "sl", 7.5)
    check("SL limit below the trigger (BUY) refused", False)
except ValueError as e:
    check("SL limit below the trigger (BUY) refused", "at or above the trigger" in str(e), e)
s2 = virtual.place_stop(uid, pid2, 8.0, "sl", 8.5)
price(9.0)
virtual.match_pending(uid)
st = status(uid, s2["order_id"])
check("SL triggered past its limit: waits as a limit", st["status"] == "open" and st["triggered_at"] and is_open(uid, pid2), st)
price(8.3)
virtual.match_pending(uid)
st = status(uid, s2["order_id"])
check("price back within the limit: fills at the limit", st["status"] == "filled" and st["fill_price"] == 8.5, st)

# 4. The day-15 group stop leaves a leg with its own stop alone.
price(5.0)
pid3 = short(uid, 800.0)
virtual.place_stop(uid, pid3, 12.0)
with db.tx(uid) as c:
    c.run("UPDATE positions SET sl_activates_on = CURRENT_DATE - 1 WHERE id=:i AND user_id=:u", i=pid3, u=uid)
price(7.0)  # above the 5.00 entry, where the group stop would fire
virtual.run_checks(uid)
check("own stop set: the group stop doesn't fire", is_open(uid, pid3))

# 5. Exit replaces the stop.
virtual.exit_position(uid, pid3)
with db.tx(uid) as c:
    left = c.value("SELECT count(*) FROM pending_orders WHERE user_id=:u AND status='open'", u=uid)
check("exit closes the leg and its stop goes with it", not is_open(uid, pid3) and left == 0, left)

# 6. A bought leg's stop is a SELL that triggers at or below.
check("SELL stop triggers at or below", virtual._triggered({"action": "SELL", "trigger_price": 3.0}, {"bid": 2.9, "ask": 3.0, "ltp": 3.0})
      and not virtual._triggered({"action": "SELL", "trigger_price": 3.0}, {"bid": 3.5, "ask": 3.6, "ltp": 3.5}))

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
