"""Floor pivots: formulas, which completed period each uses, ownership check on the RPC. With
LIVE_DATA=1 it also fetches real yfinance data."""
import os
import sys
from datetime import date, datetime, timedelta

import pandas as pd

import server
from engine import auth, data_fetch, db, pivots, users, virtual
from support import EXP, stub

fails = []


def check(name, cond, got):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


# ---- formulas, by hand for H=110 L=90 C=105: P=101.6667
lv = pivots.levels(110, 90, 105)
P = 305 / 3
want = {"P": P, "R1": 2 * P - 90, "S1": 2 * P - 110, "R2": P + 20, "S2": P - 20, "R3": 110 + 2 * (P - 90),
        "S3": 90 - 2 * (110 - P), "R4": 3 * P + 110 - 270, "S4": 3 * P - 330 + 90}
check("formulas", all(abs(lv[k] - round(v, 2)) < 1e-9 for k, v in want.items()), lv)
check("order R4>R3>R2>R1>P>S1>S2>S3>S4",
      [lv[k] for k in ["R4", "R3", "R2", "R1", "P", "S1", "S2", "S3", "S4"]] == sorted(lv.values(), reverse=True), lv)

# ---- periods: weekday bars Jul 1 .. Sep 25 2026, plus a still-forming bar on Wed Sep 23 case
days = pd.bdate_range("2026-07-01", "2026-09-25")
hist = pd.DataFrame({"High": [100 + i for i in range(len(days))], "Low": [90 + i for i in range(len(days))],
                     "Close": [95 + i for i in range(len(days))]}, index=days)


def expect(sub):
    return pivots.levels(float(sub["High"].max()), float(sub["Low"].min()), float(sub["Close"].iloc[-1]))


# Saturday Sep 26 -> next session Mon Sep 28: daily = Fri 25, weekly = 21-25 Sep, monthly = August
out = pivots.compute(hist, date(2026, 9, 28))
check("weekend: daily from Fri 25 Sep", (out["daily"]["from"], out["daily"]["to"]) == ("2026-09-25", "2026-09-25")
      and out["daily"]["levels"] == expect(hist.loc["2026-09-25":"2026-09-25"]), out["daily"]["from"])
check("weekend: weekly from 21-25 Sep", (out["weekly"]["from"], out["weekly"]["to"]) == ("2026-09-21", "2026-09-25")
      and out["weekly"]["levels"] == expect(hist.loc["2026-09-21":"2026-09-25"]), (out["weekly"]["from"], out["weekly"]["to"]))
check("weekend: monthly from August", (out["monthly"]["from"], out["monthly"]["to"]) == ("2026-08-01", "2026-08-31")
      and out["monthly"]["levels"] == expect(hist.loc["2026-08-01":"2026-08-31"]), (out["monthly"]["from"], out["monthly"]["to"]))

# Wed Sep 23 during market hours: that day's bar is partial and must be ignored
mid = hist.loc[:"2026-09-23"]
out = pivots.compute(mid, date(2026, 9, 23))
check("mid-session: daily from Tue 22 (not today's partial bar)", out["daily"]["to"] == "2026-09-22", out["daily"]["to"])
check("mid-session: weekly from 14-18 Sep", (out["weekly"]["from"], out["weekly"]["to"]) == ("2026-09-14", "2026-09-18"),
      (out["weekly"]["from"], out["weekly"]["to"]))
# Tue Sep 1: monthly must be August even though September has begun
out = pivots.compute(hist.loc[:"2026-09-01"], date(2026, 9, 1))
check("1st of month: monthly = previous month", out["monthly"]["to"] == "2026-08-31", out["monthly"]["to"])

# ---- RPC: only stocks the user holds; works for a stock outside the index
ORIGIN = "https://t.example"
server.ALLOWED_ORIGINS = {ORIGIN}
server.universe = lambda: ["SBIN"]
app = server.app.test_client()
stub(True)
calls = []
real_fetch = data_fetch.fetch_price_history
data_fetch.fetch_price_history = lambda s, n: calls.append(s) or hist.copy()
uid = users.create_user("pv@test.example", "Pv", status="active")
with db.tx(uid) as c:
    virtual._apply_trade(c, uid, "OLDCO", EXP, "CE", 1100.0, "SELL", 100, 5.0, 100, "manual", None, "auto")
app.set_cookie(server.COOKIE, auth.new_session(uid, "127.0.0.1", "t"))


def call(params):
    return app.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "va_price_levels", "params": params},
                    headers={"Origin": ORIGIN}).get_json()


j = call({"symbol": "OLDCO"})
check("held stock (outside the index) -> levels", "result" in j and set(j["result"]["pivots"]) == {"daily", "weekly", "monthly"}
      and len(j["result"]["history"]) == len(hist), j.get("error"))
call({"symbol": "OLDCO"})
check("second load served from Redis", calls == ["OLDCO.NS"], calls)
j = call({"symbol": "RELIANCE"})
check("stock not held -> refused, no fetch", j.get("error", {}).get("code") == -32000 and calls == ["OLDCO.NS"], j.get("error"))
j = call({"symbol": "OLDCO", "user_id": 99})
check("user_id can't be sent", j.get("error", {}).get("code") == -32602, j.get("error"))

# ---- real yfinance data (network; off by default so CI doesn't depend on Yahoo)
if os.environ.get("LIVE_DATA") == "1":
    data_fetch.fetch_price_history = real_fetch
    session = datetime.fromisoformat(virtual._valid_until()).date()
    prev_month = (session.replace(day=1) - timedelta(days=1)).replace(day=1)
    try:
        live = pivots.for_symbol("SUNPHARMA", session)
        m = live["pivots"]["monthly"]
        print("SUNPHARMA monthly", m["from"], "-", m["to"], "H/L/C", m["high"], m["low"], m["close"])
        check("real data: monthly = previous month", m["from"] == prev_month.isoformat(), (m["from"], m["to"]))
        check("real data: levels recompute", m["levels"] == pivots.levels(m["high"], m["low"], m["close"]), m["levels"])
    except Exception as e:
        check("real data fetch", False, repr(e))

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
