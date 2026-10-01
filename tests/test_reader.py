"""Readers (issue #163): what a signed-out visitor may open is the owner's to switch (app_settings
reader_*); the public builder methods are limited per IP; signed-in users are never limited."""
import sys

import server
from engine import app_settings, auth, builder, users

ORIGIN = "https://t.example"
server.ALLOWED_ORIGINS = {ORIGIN}
server.universe = lambda: ["SBIN"]
server.READER_EVERY = 60  # one call per IP per minute, so the second call is always refused
builder.chain = lambda s, e=None: {"symbol": s, "expiry": e}
builder.levels = lambda s: {"symbol": s}
fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def call(method, params=None, token=None, ip="10.0.0.9"):
    client = server.app.test_client()
    if token:
        client.set_cookie(server.COOKIE, token, domain="localhost")
    return client.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                       headers={"Origin": ORIGIN}, environ_base={"REMOTE_ADDR": ip}).get_json()


err = lambda r: (r.get("error") or {}).get("message", "")  # noqa: E731

# 1. Defaults: all four reader pages on, and app_info says so.
r = call("app_info")["result"]
check("app_info lists the reader pages", r["reader_pages"] == ["builder", "learn", "progress", "leaderboard"], r)

# 2. The public builder works signed out, once per IP per window.
r = call("reader_chain", {"symbol": "SBIN"})
check("reader_chain signed out", r.get("result", {}).get("symbol") == "SBIN", r)
check("second call from the same IP refused", "Too many requests" in err(call("reader_chain", {"symbol": "SBIN"})))
check("another IP is not affected", "result" in call("reader_chain", {"symbol": "SBIN"}, ip="10.0.0.10"))
check("levels limited separately from the chain", "result" in call("reader_levels", {"symbol": "SBIN"}))
check("symbol still validated", "error" in call("reader_chain", {"symbol": "NOTREAL"}, ip="10.0.0.11"))
check("universe", call("reader_universe")["result"] == ["SBIN"])
lv = call("levels_overview")["result"]
check("levels overview: 10 levels with unlocks", len(lv) == 10 and lv[4]["level"] == 5 and lv[4]["unlocks"], lv[4])

# 3. Signed in: never limited.
uid = users.create_user("r@test.example", "R", status="active")
tok = auth.new_session(uid, "10.0.0.9", "ua")
check("signed-in user not limited", all("result" in call("reader_chain", {"symbol": "SBIN"}, tok) for _ in range(3)))

# 4. The owner switches pages off for readers.
owner = users.create_user("o@test.example", "O", status="active")
for k in ("reader_builder", "reader_learn", "reader_leaderboard", "reader_progress"):
    app_settings.set_value(owner, k, False)
check("app_info: no reader pages", call("app_info")["result"]["reader_pages"] == [])
check("builder off: refused", "Sign in" in err(call("reader_chain", {"symbol": "SBIN"}, ip="10.0.0.12")))
check("learn off: refused", "Sign in" in err(call("lessons_list")))
check("leaderboard off: refused", "Sign in" in err(call("leaderboard_get")))
check("progress off: refused", "Sign in" in err(call("levels_overview")))
check("signed-in users keep them", "result" in call("lessons_list", token=tok) and "result" in call("leaderboard_get", token=tok))

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
