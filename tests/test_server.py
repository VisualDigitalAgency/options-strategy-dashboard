"""server.py error handling and rpc_guard number checks (Flask test client, real Postgres + Redis,
real session)."""
import sys

import requests

import server
from engine import auth, users, virtual
from support import EXP

ORIGIN = "https://t.example"
server.ALLOWED_ORIGINS = {ORIGIN}
server.universe = lambda: ["SBIN"]  # no NSE call for the index list
app = server.app.test_client()
fails = []


def call(method, params=None, cookie=None):
    if cookie:
        app.set_cookie(server.COOKIE, cookie)
    r = app.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                 headers={"Origin": ORIGIN})
    return r.status_code, r.get_json(silent=True)


def check(name, cond, got):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


uid = users.create_user("srv@test.example", "Server Test", role="beta", status="active")  # beta has the screener (#136)
token = auth.new_session(uid, "127.0.0.1", "test")

# 1. NaN / Infinity / huge numbers never reach the engine
for label, body in (("NaN", '{"starting_capital": NaN}'), ("Infinity", '{"starting_capital": Infinity}')):
    app.set_cookie(server.COOKIE, token)
    r = app.post("/rpc", data='{"jsonrpc":"2.0","id":1,"method":"va_reset","params":' + body + '}',
                 content_type="application/json", headers={"Origin": ORIGIN})
    j = r.get_json()
    check(f"reset {label} refused", j.get("error", {}).get("code") == -32602, j.get("error"))
s, j = call("va_reset", {"starting_capital": 1e15}, token)
check("reset 1e15 refused", j.get("error", {}).get("code") == -32000, j.get("error"))
s, j = call("calc_margin", {"symbol": "SBIN", "expiry": EXP,
                            "legs": [{"side": "PE", "strike": float("inf")}]}, token)
check("Infinity strike refused", j is not None and j.get("error", {}).get("code") in (-32602, -32603), j and j.get("error"))

# 2. Non-RPC errors are JSON, not HTML
r = app.get("/rpc")
check("GET /rpc -> JSON 405", r.status_code == 405 and r.is_json, (r.status_code, r.content_type))
r = app.post("/rpc", data="x" * 70_000, content_type="application/json", headers={"Origin": ORIGIN})
check("oversized body -> JSON 413", r.status_code == 413 and r.is_json, (r.status_code, r.content_type))

# 3. A crash inside validate (universe fetch) -> JSON error with a ref
orig_universe = server.universe
server.universe = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
s, j = call("get_trade_detail", {"symbol": "SBIN"}, token)
check("validate crash -> JSON -32603 with ref", s == 200 and j["error"]["code"] == -32603 and "ref" in j["error"]["message"],
      j["error"])
server.universe = orig_universe

# 4. NSE down -> friendly upstream message (also for a JSON decode error, which is a ValueError)
for exc in (requests.ConnectionError("nse down"), requests.exceptions.JSONDecodeError("Expecting value", "", 0)):
    def cfg(_e=exc):
        raise _e
    server.METHODS["get_config"] = cfg
    s, j = call("get_config", {}, token)
    check(f"{type(exc).__name__} -> upstream message", j["error"]["message"] == server.UPSTREAM_MESSAGE, j["error"])
server.METHODS["get_config"] = server.get_config

# 5. Committed change + failing re-price -> still reported as success
virtual.refresh_positions = lambda user_id: (_ for _ in ()).throw(requests.ConnectionError("nse down"))
s, j = call("va_set_sl_mode", {"mode": "alert"}, token)
check("failed re-price after commit -> success", j.get("result") == {"ok": True}, j)

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
