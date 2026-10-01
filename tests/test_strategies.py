"""Saved strategies (issue #150): Level 5 unlocks them (and only the caller's own are visible),
saving under an existing name replaces it, the 50 limit, bad legs refused, expired flag, delete."""
import sys

import server
from engine import auth, db, strategies, users
from support import EXP

ORIGIN = "https://t.example"
server.ALLOWED_ORIGINS = {ORIGIN}
server.universe = lambda: ["SBIN", "INFY"]
fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def person(email, level):
    uid = users.create_user(email, email.split("@")[0], status="active")
    with db.tx(uid) as c:
        c.run("INSERT INTO user_levels (user_id, level) VALUES (:u, :l) ON CONFLICT (user_id) DO UPDATE SET level=:l",
              u=uid, l=level)
    return uid


def rpc(uid, method, params=None):
    c = server.app.test_client()
    c.set_cookie(server.COOKIE, auth.new_session(uid, "10.0.0.9", "ua"), domain="localhost")
    return c.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                  headers={"Origin": ORIGIN}).get_json()


LEGS = [{"side": "CE", "strike": 1100, "action": "SELL", "lots": 1, "delta": 0.1},
        {"side": "CE", "strike": 1200, "action": "BUY", "lots": 1, "delta": 0.04}]
low, a, b = person("l4@test.example", 4), person("a@test.example", 5), person("b@test.example", 5)

r = rpc(low, "strategy_save", {"name": "Condor", "symbol": "SBIN", "expiry": EXP, "legs": LEGS})
check("Level 4 can't save", r.get("error", {}).get("code") == server.FORBIDDEN, r)
check("...or list", rpc(low, "strategy_list").get("error", {}).get("code") == server.FORBIDDEN)

r = rpc(a, "strategy_save", {"name": "  Bear   call ", "symbol": "SBIN", "expiry": EXP, "legs": LEGS})
check("Level 5 saves (name tidied)", r.get("result", {}).get("name") == "Bear call" and not r["result"]["replaced"], r)
r = rpc(a, "strategy_save", {"name": "BEAR CALL", "symbol": "INFY", "expiry": EXP, "legs": LEGS[:1]})
check("same name, any case, replaces", r.get("result", {}).get("replaced") is True, r)
mine = rpc(a, "strategy_list")["result"]
check("one strategy, the replacement", len(mine) == 1 and mine[0]["symbol"] == "INFY" and len(mine[0]["legs"]) == 1, mine)
check("legs keep their delta", mine[0]["legs"][0]["delta"] == 0.1, mine[0]["legs"])
check("live expiry isn't expired", mine[0]["expired"] is False and mine[0]["expiry"] == EXP)
check("another user sees none of them", rpc(b, "strategy_list")["result"] == [])
with db.tx(b) as c:
    check("RLS: B can't read A's rows directly", c.value("SELECT count(*) FROM saved_strategies") == 0)
r = rpc(b, "strategy_delete", {"strategy_id": mine[0]["id"]})
check("B can't delete A's strategy", "error" in r, r)

for bad, why in (({"name": "", "legs": LEGS}, "empty name"), ({"name": "x" * 41, "legs": LEGS}, "long name"),
                 ({"name": "n", "legs": []}, "no legs"), ({"name": "n", "legs": LEGS * 5}, "too many legs"),
                 ({"name": "n", "legs": [{"side": "XX", "strike": 1, "action": "SELL", "lots": 1}]}, "bad side"),
                 ({"name": "n", "legs": [{"side": "CE", "strike": 1, "action": "SELL", "lots": 99}]}, "too many lots")):
    r = rpc(a, "strategy_save", {"symbol": "SBIN", "expiry": EXP, **bad})
    check(f"refused: {why}", "error" in r, r.get("error"))
r = rpc(a, "strategy_save", {"name": "n", "symbol": "SBIN", "expiry": EXP, "legs": [{**LEGS[0], "delta": 7}]})
check("refused: delta out of range (the RPC guard)", "delta" in r.get("error", {}).get("message", ""), r.get("error"))
r = rpc(a, "strategy_save", {"name": "n", "symbol": "ZZZZ", "expiry": EXP, "legs": LEGS})
check("refused: stock outside the Nifty 50", "error" in r, r.get("error"))

with db.tx(a) as c:
    c.run("UPDATE saved_strategies SET expiry='2020-01-30' WHERE user_id=:u", u=a)
check("past expiry flagged", rpc(a, "strategy_list")["result"][0]["expired"] is True)

for i in range(strategies.MAX_PER_USER - 1):
    strategies.save(a, f"s{i}", "SBIN", EXP, LEGS)
r = rpc(a, "strategy_save", {"name": "one too many", "symbol": "SBIN", "expiry": EXP, "legs": LEGS})
check("limit of 50", "up to 50" in r.get("error", {}).get("message", ""), r)
check("replacing still works at the limit", rpc(a, "strategy_save", {"name": "s0", "symbol": "SBIN", "expiry": EXP,
                                                                     "legs": LEGS}).get("result", {}).get("replaced"))
sid = rpc(a, "strategy_list")["result"][0]["id"]
check("delete", rpc(a, "strategy_delete", {"strategy_id": sid}).get("result") == {"deleted": sid})
check("now 49", len(rpc(a, "strategy_list")["result"]) == 49)

sys.exit(1 if fails else 0)
