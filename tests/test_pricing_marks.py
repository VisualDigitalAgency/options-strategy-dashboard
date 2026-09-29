"""Stale-LTP slippage (DRREDDY 1400 CE: sold at the 3.40 bid, LTP 6.00 showed -₹1,625 unbooked).
Covers engine/pricing, the screener's bid premium + illiquid pass-over, positions marked at mid with
the closing cost beside it, the ticket defaulting to mid on a wide book, the illiquid confirm, and
the stop loss judging the mid rather than the ask."""
import sys
from datetime import date, timedelta

import pandas as pd

from engine import autotrade, cache, db, pricing, risk_rules, users, virtual
from support import EXP, SYM, new_user, stub

fails = []


def check(name, cond, got):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


# ---- pricing helpers
check("mid", pricing.mid(3.40, 3.60) == 3.5, pricing.mid(3.40, 3.60))
check("spread % of mid", pricing.spread_pct(3.40, 3.60) == 5.7, pricing.spread_pct(3.40, 3.60))
check("no book -> no spread", pricing.spread_pct(0, 3.6) is None, None)
check("stale LTP gap", pricing.ltp_gap_pct(3.40, 3.60, 6.00) == 68.6, pricing.ltp_gap_pct(3.40, 3.60, 6.00))
check("mark at mid", pricing.mark(3.40, 3.60, 6.00) == (3.5, "mid"), pricing.mark(3.40, 3.60, 6.00))
check("one-sided: LTP held under the ask", pricing.mark(0, 3.60, 6.00) == (3.6, "ltp"), pricing.mark(0, 3.60, 6.00))
check("sell premium is the bid", pricing.sell_premium(3.40, 3.60, 6.00, True) == (3.4, "bid"), None)
check("after hours, no book: LTP stands in", pricing.sell_premium(0, 0, 6.00, False) == (6.0, "ltp"), None)
liq = pricing.liquidity(3.40, 3.60, 6.00, 50_000, True)
check("stale LTP is illiquid", liq["ok"] is False and "stale" in liq["reason"], liq)
check("tight, fresh book is fine", pricing.liquidity(3.40, 3.60, 3.50, 50_000, True)["ok"] is True, None)
check("wide spread is illiquid", pricing.liquidity(3.0, 4.0, 3.5, 50_000, True)["ok"] is False, None)
check("no book in session is illiquid", pricing.liquidity(0, 0, 3.5, 50_000, True)["ok"] is False, None)
check("no book after hours: unknown", pricing.liquidity(0, 0, 3.5, 50_000, False)["ok"] is None, None)

# ---- screener: premium at the bid, illiquid strike passed over for the next by OI
chain = pd.DataFrame({
    "strikePrice": [1350.0, 1400.0, 1450.0],
    "CE_OI": [20_000, 90_000, 5_000], "CE_OI_CHG": [0, 0, 0],
    "CE_LTP": [9.10, 6.00, 1.80], "CE_BID": [9.00, 3.40, 1.75], "CE_ASK": [9.30, 3.60, 1.85],
    "CE_IV": [22.0, 24.0, 26.0],
})
leg, over = risk_rules._pick_leg(chain, 1251.9, 55, "CE", in_session=True)
check("stale 1400 passed over", leg and leg["strike"] != 1400.0 and any("1400" in o for o in over), (leg and leg["strike"], over))
check("premium is the bid", leg and leg["premium"] == leg["bid"] and leg["premium_src"] == "bid", leg and leg["premium"])
fresh = chain.assign(CE_LTP=[9.10, 3.50, 1.80])
leg, over = risk_rules._pick_leg(fresh, 1251.9, 55, "CE", in_session=True)
check("liquid 1400 picked at bid 3.40, not LTP", leg["strike"] == 1400.0 and leg["premium"] == 3.40 and not over, leg["premium"])
closed = chain.assign(CE_BID=[0.0, 0.0, 0.0], CE_ASK=[0.0, 0.0, 0.0])
leg, _ = risk_rules._pick_leg(closed, 1251.9, 55, "CE", in_session=False)
check("after hours with no book: LTP premium, flagged", leg["strike"] == 1400.0 and leg["premium_src"] == "ltp"
      and leg["liquidity"]["ok"] is None, leg["premium_src"])

# ---- positions: marked at mid, closing cost beside it
uid = new_user("marks@example.com", 1_000_000)


def quotes(bid, ask, ltp):
    virtual.quote = lambda s, e, side, k: {"spot": 1251.9, "ltp": ltp, "bid": bid, "ask": ask, "iv": 24.0, "oi": 90_000}


stub(market=True, bid=3.40)
quotes(3.40, 3.60, 3.50)
virtual.place_order(uid, SYM, EXP, [{"side": "CE", "strike": 1400.0, "action": "SELL", "lots": 1, "price": 3.40}])
quotes(3.40, 3.60, 6.00)  # the last trade goes stale above the book
g = virtual.get_positions(uid)["groups"][0]
leg = g["legs"][0]
check("filled at the bid", leg["avg_price"] == 3.40, leg["avg_price"])
check("marked at mid, not the 6.00 LTP", leg["mark"] == 3.5 and leg["mark_src"] == "mid", (leg["mark"], leg["mark_src"]))
check("unbooked = half the spread, not -260", leg["pnl"] == round((3.5 - 3.4) * -100, 2), leg["pnl"])
check("if closed now = at the ask", leg["pnl_exit"] == round((3.6 - 3.4) * -100, 2) and g["pnl_exit"] == leg["pnl_exit"], g["pnl_exit"])
check("stale LTP flagged", leg["ltp_gap_pct"] > 15, leg["ltp_gap_pct"])
check("account unbooked uses the mark", virtual.get_account(uid)["unrealized_pnl"] == leg["pnl"], None)

virtual.market_open = lambda: False
quotes(0.0, 0.0, 6.00)  # after the close NSE clears the book; LTP is the stale last trade
leg = virtual.get_positions(uid)["groups"][0]["legs"][0]
check("after close: last in-session mid", leg["mark"] == 3.5 and leg["mark_src"] == "close", (leg["mark"], leg["mark_src"]))
cache.delete(f"mark:{SYM}:{EXP}:CE:1400")
leg = virtual.get_positions(uid)["groups"][0]["legs"][0]
check("no kept mark and no book: LTP", leg["mark"] == 6.0 and leg["mark_src"] == "ltp", leg["mark_src"])
virtual.market_open = lambda: True

# ---- ticket: mid on a wide book; illiquid needs a confirm; auto-trade path sees the flag
quotes(3.00, 3.30, 3.10)  # 9.5% spread: under the 10% gate, over the 3% mid threshold
p = virtual.preview_order(uid, SYM, EXP, [{"side": "CE", "strike": 1400.0, "action": "SELL", "lots": 1}])
check("wide book: default limit at mid", p["fills"][0]["limit"] == 3.15 and not p["fills"][0]["fills_now"], p["fills"][0]["limit"])
quotes(3.40, 3.50, 3.45)
p = virtual.preview_order(uid, SYM, EXP, [{"side": "CE", "strike": 1400.0, "action": "SELL", "lots": 1}])
check("tight book: default at the bid, fills now", p["fills"][0]["limit"] == 3.40 and p["fills"][0]["fills_now"], p["fills"][0])
quotes(3.40, 3.60, 6.00)
legs = [{"side": "CE", "strike": 1400.0, "action": "SELL", "lots": 1, "price": 3.40}]
p = virtual.preview_order(uid, SYM, EXP, legs)
check("stale LTP flagged on a limit order too", len(p["illiquid"]) == 1 and "stale" in p["illiquid"][0]["reason"], p["illiquid"])
try:
    virtual.place_order(uid, SYM, EXP, legs, confirm_waiting=True)
    check("illiquid refused without confirm", False, "placed")
except ValueError as e:
    check("illiquid refused without confirm", "Confirm to place anyway" in str(e), str(e))
r = virtual.place_order(uid, SYM, EXP, legs, confirm_waiting=True, confirm_illiquid=True)
check("confirm places it", len(r["filled"]) == 1, r["filled"])

# ---- stop loss judges the mid; the exit fills at the ask
with db.tx(uid) as c:
    c.run("UPDATE positions SET sl_activates_on=:d, sl_mode='auto' WHERE user_id=:u",
          d=(date.today() - timedelta(days=1)).isoformat(), u=uid)
with db.tx(uid) as c:
    c.run("UPDATE positions SET sl_price=3.50 WHERE user_id=:u", u=uid)
quotes(3.30, 3.60, 3.45)  # the ask (3.60) is past the 3.50 stop, the mid (3.45) is not
res = virtual.run_checks(uid)
check("ask over the stop, mid under it: no exit", not res["exited"] and len(virtual.get_positions(uid)["groups"]) == 1, res)
quotes(3.50, 3.70, 3.60)  # mid 3.60 is past the 3.50 stop
res = virtual.run_checks(uid)
check("mid past the stop: exits", len(res["exited"]) >= 1 and not virtual.get_positions(uid)["groups"], res)
with db.tx(uid) as c:
    px = c.value("SELECT price FROM orders WHERE user_id=:u AND reason='sl_auto' ORDER BY id DESC LIMIT 1", u=uid)
check("stop exit fills at the ask", float(px) == 3.70, px)

# ---- auto-trade skips an illiquid strike instead of selling it
uid3 = users.create_user("auto-liq@example.com", "Auto", status="active")
autotrade.set_settings(uid3, min_pop=50, reserve_pct=0, max_trade_pct=50)
dte = (date.fromisoformat(EXP) - date.today()).days
cand = [{"symbol": SYM, "expiry": EXP, "dte": dte, "legs": [{"side": "CE", "strike": 1400.0}],
         "strategy": {"pop": 95.0, "roi_pct": 1.5, "margin": 50_000.0}}]
quotes(3.40, 3.60, 6.00)
r = autotrade.run(uid3, cand, trigger="manual")
check("auto-trade skips the stale strike", not r["placed"] and "Illiquid" in r["skipped"][0]["reason"], r["skipped"])
quotes(3.40, 3.45, 3.42)
r = autotrade.run(uid3, cand, trigger="manual")
check("auto-trade sells a liquid one", len(r["placed"]) == 1, r["skipped"])

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
