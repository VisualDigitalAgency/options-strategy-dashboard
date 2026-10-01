"""A second manual order on a stock/expiry whose earlier order is still waiting needs confirmation."""
import sys
import threading

import server
from engine import auth
from support import EXP, SYM, new_user, stub

fails = []


def check(name, cond, got):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


ORIGIN = "https://t.example"
server.ALLOWED_ORIGINS = {ORIGIN}
server.universe = lambda: [SYM, "HDFCBANK"]
app = server.app.test_client()
stub(False)  # market closed, like Saturday: every order waits
uid = new_user("wait@test.example", 1_000_000)  # ₹10 lakh: each stubbed order blocks ₹1 lakh (#47 made ₹2 lakh the default)
app.set_cookie(server.COOKIE, auth.new_session(uid, "127.0.0.1", "t"))
LEGS = [{"side": "CE", "strike": 1100.0, "action": "SELL", "lots": 1}]


def call(method, params, client=app):
    r = client.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                    headers={"Origin": ORIGIN})
    return r.get_json()


def n_open():
    return len(call("va_get_open_orders", {}).get("result") or [])


j = call("va_preview_order", {"symbol": SYM, "expiry": EXP, "legs": LEGS})
check("preview: nothing waiting yet", j["result"]["waiting"] == [], j["result"]["waiting"])
j = call("va_place_order", {"symbol": SYM, "expiry": EXP, "legs": LEGS})
check("first order placed (waits)", "result" in j and len(j["result"]["open"]) == 1, j.get("error"))
j = call("va_preview_order", {"symbol": SYM, "expiry": EXP, "legs": LEGS})
w = j["result"]["waiting"]
check("preview lists the waiting order", len(w) == 1 and w[0]["strike"] == 1100.0 and w[0]["qty"] == 100, w)
j = call("va_place_order", {"symbol": SYM, "expiry": EXP, "legs": LEGS})
check("second order refused without confirmation", j.get("error", {}).get("code") == -32000, j.get("error"))
check("still one open order", n_open() == 1, n_open())
j = call("va_place_order", {"symbol": SYM, "expiry": EXP, "legs": LEGS, "confirm_waiting": True})
check("second order placed once confirmed", "result" in j, j.get("error"))
check("two open orders", n_open() == 2, n_open())
j = call("va_place_order", {"symbol": SYM, "expiry": EXP, "legs": LEGS, "confirm_waiting": "yes"})
check("confirm_waiting must be a boolean", j.get("error", {}).get("code") == -32602, j.get("error"))
j = call("va_place_order", {"symbol": "HDFCBANK", "expiry": EXP, "legs": LEGS})
check("other stock not affected", "result" in j, j.get("error"))

# Double click: two requests at once with nothing waiting -> exactly one gets through.
uid2 = new_user("dbl@test.example", 1_000_000)
tok = auth.new_session(uid2, "127.0.0.1", "t")
res = []


def click():
    c = server.app.test_client()
    c.set_cookie(server.COOKIE, tok)
    res.append(call("va_place_order", {"symbol": SYM, "expiry": EXP, "legs": LEGS}, c))


ts = [threading.Thread(target=click) for _ in range(2)]
[t.start() for t in ts]
[t.join() for t in ts]
ok = sum("result" in r for r in res)
check("double click: one placed, one refused", ok == 1, [r.get("error", {}).get("message", "ok") for r in res])

# Once the market is open and the order fills right away, nothing is left waiting: no prompt.
stub(True)
uid3 = new_user("fill@test.example", 1_000_000)
c3 = server.app.test_client()
c3.set_cookie(server.COOKIE, auth.new_session(uid3, "127.0.0.1", "t"))
a = call("va_place_order", {"symbol": SYM, "expiry": EXP, "legs": LEGS}, c3)
b = call("va_place_order", {"symbol": SYM, "expiry": EXP, "legs": LEGS}, c3)
check("filled orders never prompt", "result" in a and "result" in b and a["result"]["filled"], (a.get("error"), b.get("error")))

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
