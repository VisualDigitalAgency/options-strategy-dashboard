"""Strategy builder (issue #137): the chain endpoint, the buy-leg rule (protective buys below
Level 6, any buy from Level 6), premium paid counted as margin for longs, and the long stop."""
import sys

import pandas as pd

import server
from engine import auth, builder, data_fetch, db, market_calendar, span, virtual
from support import EXP, new_user, stub

real_group_margin = virtual.group_margin
ORIGIN = "https://t.example"
server.ALLOWED_ORIGINS = {ORIGIN}
server.universe = lambda: ["SBIN"]
fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def legs(*spec):
    return [{"side": s, "strike": k, "action": a, "lots": n} for s, k, a, n in spec]


def refused(uid, order, why):
    try:
        virtual.place_order(uid, "SBIN", EXP, order)
        check(f"refused: {why}", False)
        return ""
    except ValueError as e:
        check(f"refused: {why}", True, e)
        return str(e)


stub(market=True)

# 1. Margin: a long blocks the premium paid; with no short that is all it blocks.
m = real_group_margin("SBIN", EXP, [{"side": "CE", "strike": 1100.0, "qty": 100, "price": 5.1}], 1000.0)
check("long-only margin is the premium paid", m == {"span": 0.0, "exposure": 0.0, "premium_paid": 510.0, "total": 510.0}, m)
span.load, span.scan_risk_positions = (lambda u: None), (lambda *a: 4000.0)
virtual._exposure_pct = lambda s: 2.0
m = real_group_margin("SBIN", EXP, [{"side": "CE", "strike": 1100.0, "qty": -100, "avg_price": 5.0},
                                     {"side": "CE", "strike": 1200.0, "qty": 100, "avg_price": 1.0}], 1000.0)
check("spread margin = SPAN + exposure + premium paid", m["total"] == 4000.0 + 2000.0 + 100.0, m)

# 2. Buy-leg rule below Level 6.
uid = new_user("b1@test.example", 1_000_000)
msg = refused(uid, legs(("CE", 1100, "BUY", 1)), "naked buy below Level 6")
check("says it unlocks at Level 6", "Level 6" in msg, msg)
refused(uid, legs(("CE", 1100, "SELL", 1), ("CE", 1050, "BUY", 1)), "long nearer the money than the short")
refused(uid, legs(("PE", 900, "SELL", 1), ("PE", 950, "BUY", 1)), "put long above the short put")
refused(uid, legs(("CE", 1100, "SELL", 1), ("CE", 1200, "BUY", 2)), "more long than short")
refused(uid, legs(("PE", 900, "SELL", 1), ("CE", 1200, "BUY", 1)), "a call can't protect a put")
r = virtual.place_order(uid, "SBIN", EXP, legs(("CE", 1100, "SELL", 1), ("CE", 1200, "BUY", 1),
                                                  ("PE", 900, "SELL", 1), ("PE", 800, "BUY", 1)))
check("iron condor allowed below Level 6", len(r["filled"]) == 4, r)
p = virtual.preview_order(uid, "SBIN", EXP, legs(("CE", 1100, "BUY", 1)))
check("buying back a short is not a new long", p["buy_rule"] is None, p["buy_rule"])
p = virtual.preview_order(uid, "SBIN", EXP, legs(("CE", 1300, "BUY", 1)))
check("adding a protective long to an existing short counts the position", p["buy_rule"] is not None,
      p["buy_rule"])  # 1200 CE already protects the only 1-lot short; a 2nd long is too many
virtual.place_order(uid, "SBIN", EXP, legs(("CE", 1150, "SELL", 1), ("CE", 1300, "BUY", 1)))
check("protecting a second short with the position held", True)

# 3. The RPC refuses too (the server, not just the page).
c = server.app.test_client()
c.set_cookie(server.COOKIE, auth.new_session(uid, "127.0.0.1", "t"), domain="localhost")
j = c.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "va_place_order",
                         "params": {"symbol": "SBIN", "expiry": EXP, "legs": legs(("PE", 700, "BUY", 1))}},
           headers={"Origin": ORIGIN}).get_json()
check("va_place_order refuses a naked buy", "Level 6" in j.get("error", {}).get("message", ""), j)

# 4. Level 6: any buy, with a 50% stop that acts while the group has no short.
pro = new_user("b6@test.example", 1_000_000)
with db.tx(pro) as cx:
    cx.run("INSERT INTO user_levels (user_id, level) VALUES (:u, 6)", u=pro)
r = virtual.place_order(pro, "SBIN", EXP, legs(("CE", 1100, "BUY", 1)))
check("naked buy allowed at Level 6", len(r["filled"]) == 1, r)
with db.tx(pro) as cx:
    pos = cx.one("SELECT * FROM positions WHERE user_id=:u AND status='open'", u=pro)
check("long stop is 50% of the 5.10 paid, live today", float(pos["sl_price"]) == 2.55
      and str(pos["sl_activates_on"]) == str(virtual._today().date()), (pos["sl_price"], pos["sl_activates_on"]))
check("long shows as armed", virtual._sl_status(pos, virtual._today()) == "armed")
virtual.run_checks(pro)
with db.tx(pro) as cx:
    check("no exit above the stop", cx.value("SELECT count(*) FROM positions WHERE user_id=:u AND status='open'", u=pro) == 1)
stub(market=True, bid=2.0)  # mid 2.05 <= 2.55
virtual.run_checks(pro)
with db.tx(pro) as cx:
    closed = cx.one("SELECT status, realized_pnl FROM positions WHERE id=:i", i=pos["id"])
check("long closes at its stop, sold at the bid", closed["status"] == "closed"
      and float(closed["realized_pnl"]) == round((2.0 - 5.1) * 100, 2), closed)

# A hedged long falling never fires the long stop: its short is the trade.
virtual.run_checks(uid)
with db.tx(uid) as cx:
    check("hedged longs untouched by the long stop",
          cx.value("SELECT count(*) FROM positions WHERE user_id=:u AND status='open' AND qty > 0", u=uid) == 3)
stub(market=True)

# 5. builder_chain.
cache_exps = [EXP, str((pd.Timestamp(EXP) + pd.Timedelta(days=28)).date())]
data_fetch.fetch_expiries = lambda s: [pd.Timestamp(e) for e in ["2020-01-30", *cache_exps]]
df = pd.DataFrame([
    {"strikePrice": 1000.0, "CE_LTP": 30.0, "CE_BID": 29.5, "CE_ASK": 30.5, "CE_IV": 20.0, "CE_OI": 500, "CE_OI_CHG": 120, "CE_PCHG": 12.345,
     "PE_OI_CHG": -40,
     "PE_LTP": 25.0, "PE_BID": 24.5, "PE_ASK": 25.5, "PE_IV": 20.0, "PE_OI": 400},
    {"strikePrice": 1200.0, "CE_LTP": 1.0, "CE_BID": 0.9, "CE_ASK": 1.1, "CE_IV": 25.0, "CE_OI": 900,
     "PE_LTP": 0.0, "PE_BID": 0.0, "PE_ASK": 0.0, "PE_IV": 0.0, "PE_OI": 0},
]).set_index("strikePrice")
virtual._chain = lambda s, e: (1000.0, df)
market_calendar.load = lambda: {"events": [{"symbol": "SBIN", "date": str(virtual._today().date()), "type": "results"}]}
j = c.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "builder_chain", "params": {"symbol": "SBIN"}},
           headers={"Origin": ORIGIN}).get_json()["result"]
check("free account gets the chain (no Pro needed)", j["symbol"] == "SBIN" and len(j["rows"]) == 2, j.get("rows"))
check("past expiries dropped", "2020-01-30" not in j["expiries"], j["expiries"])
check("deltas computed; a dead side is null", j["rows"][1]["PE"] is None and 0 < j["rows"][1]["CE"]["delta"] < 0.15, j["rows"][1])
check("OI change per side (#154)", j["rows"][0]["CE"]["oi_chg"] == 120 and j["rows"][0]["PE"]["oi_chg"] == -40, j["rows"][0])
check("price % change rounded; missing is null (#156)", j["rows"][0]["CE"]["pchg"] == 12.35 and j["rows"][0]["PE"]["pchg"] is None, j["rows"][0])
sm = j["summary"]
check("footer: PCR, max pain, ATM IV (#158)", sm["pcr"] == round(400 / 1400, 2) and sm["max_pain"] in (1000.0, 1200.0)
      and sm["atm_strike"] == 1000.0 and sm["atm_iv"] == 20.0, sm)
check("missing OI change is null, not 0", j["rows"][1]["CE"]["oi_chg"] is None, j["rows"][1]["CE"])
check("results date listed", j["events"] and j["events"][0]["type"] == "results", j["events"])
check("rules for warnings", j["rules"]["min_dte"] == 30 and j["rules"]["delta_max_abs"] == 0.15, j["rules"])
try:
    builder.chain("SBIN", "2099-01-01")
    check("unknown expiry refused", False)
except ValueError:
    check("unknown expiry refused", True)

# Builder levels: monthly pivots and swing zones for any Nifty 50 stock, from the shared pivots cache.
idx = pd.bdate_range(end=pd.Timestamp(virtual._today().date()) - pd.Timedelta(days=1), periods=90)
wave = [1000 + 6 * abs((i % 20) - 10) for i in range(len(idx))]
data_fetch.fetch_price_history = lambda s, n: pd.DataFrame(
    {"High": [w + 5 for w in wave], "Low": [w - 5 for w in wave], "Close": wave}, index=idx)
lv = c.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "builder_levels", "params": {"symbol": "SBIN"}},
            headers={"Origin": ORIGIN}).get_json()
res = lv.get("result") or {}
check("levels: monthly pivots", set(res.get("pivots", {})) >= {"P", "R1", "S1"}, lv)
check("levels: swing zones typed", res.get("zones") and all(z["type"] in ("support", "resistance") for z in res["zones"]),
      res.get("zones"))
bad = c.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "builder_levels", "params": {"symbol": "ZZZ"}},
             headers={"Origin": ORIGIN}).get_json()
check("levels: only Nifty 50 symbols", "error" in bad, bad)

sys.exit(1 if fails else 0)
