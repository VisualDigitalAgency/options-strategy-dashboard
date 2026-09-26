"""(a) Exit all works for a stock that left the Nifty 50, and opening a trade in it is still refused.
(b) After a worker restart, the API process picks up the new screen instead of keeping stale rows."""
import sys

import server
from engine import auth, batch, db, users, virtual
from support import EXP, stub

fails = []


def check(name, cond, got):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


# ---- (a) exits outside the index
ORIGIN = "https://t.example"
server.ALLOWED_ORIGINS = {ORIGIN}
server.universe = lambda: ["SBIN", "HDFCBANK"]  # OLDCO has left the index
app = server.app.test_client()
stub(True)
uid = users.create_user("idx@test.example", "Idx", status="active")
with db.tx(uid) as c:  # a short put bought back when OLDCO was still in the Nifty 50
    virtual._apply_trade(c, uid, "OLDCO", EXP, "PE", 900.0, "SELL", 100, 5.0, 100, "manual", None, "auto")
app.set_cookie(server.COOKIE, auth.new_session(uid, "127.0.0.1", "t"))


def call(method, params):
    r = app.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, headers={"Origin": ORIGIN})
    return r.get_json()


j = call("va_exit_group", {"symbol": "OLDCO", "expiry": EXP})
check("exit all for OLDCO (left the index)", "result" in j and j["result"][0]["status"] == "filled", j.get("error") or j.get("result"))
j = call("va_place_order", {"symbol": "OLDCO", "expiry": EXP, "legs": [{"side": "PE", "strike": 900.0, "action": "SELL", "lots": 1}]})
check("new order in OLDCO still refused", j.get("error", {}).get("code") == -32602, j.get("error"))
j = call("va_exit_group", {"symbol": "OLDCO", "expiry": EXP})
check("exit all with nothing open -> clear error", j.get("error", {}).get("code") == -32000, j.get("error"))

# ---- (b) screen version across a worker restart
batch.ScreenJob._load_cache = lambda self: None  # no disk cache in this container
old_worker = batch.ScreenJob()
old_worker.order, old_worker.results = ["SBIN"], {"SBIN": {"symbol": "SBIN", "tag": "old"}}
old_worker._publish(rows=True)
reader = batch.ScreenReader()
first = reader.get("SBIN")["tag"]
new_worker = batch.ScreenJob()  # the worker restarted (deploy, lock loss)
new_worker.order, new_worker.results = ["SBIN"], {"SBIN": {"symbol": "SBIN", "tag": "new"}}
new_worker._publish(rows=True)
second = reader.get("SBIN")["tag"]
check("API sees the restarted worker's screen", (first, second) == ("old", "new"), (first, second))

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
