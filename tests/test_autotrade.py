"""Auto-trade must not place the same setup twice while the first order is still waiting to fill.
Market closed, so the first run's SELL rests as an open order; then run again. With several expiry
cycles screened for one stock, it opens at most one: the best-scoring cycle at least MIN_DTE out."""
import sys
from datetime import date

from engine import autotrade, config, db, users, virtual
from support import EXP, SYM, stub

stub(False)  # market closed: orders rest as open limit orders
uid = users.create_user("auto@test.example", "Auto", status="active")
autotrade.set_settings(uid, min_pop=50, reserve_pct=0, max_trade_pct=50)
DTE = (date.fromisoformat(EXP) - date.today()).days
cand = [{"symbol": SYM, "expiry": EXP, "dte": DTE, "legs": [{"side": "PE", "strike": 900.0}],
         "strategy": {"pop": 95.0, "roi_pct": 1.5, "margin": 100_000.0}}]

runs = [autotrade.run(uid, cand, trigger="manual") for _ in range(2)]
with db.tx(uid) as c:
    orders = c.all("SELECT action, qty FROM pending_orders WHERE user_id=:u AND status='open'", u=uid)
for i, r in enumerate(runs, 1):
    print(f"run #{i}: placed={len(r['placed'])} skipped={[s['reason'] for s in r['skipped']]}")
print("open orders:", orders)
fails = []
if not (len(runs[0]["placed"]) == 1 and len(runs[1]["placed"]) == 0 and len(orders) == 1):
    fails.append("the second run placed the same setup again")

# ---- several cycles of one stock: one order, on the best cycle at or past MIN_DTE
uid2 = users.create_user("auto2@test.example", "Auto2", status="active")
autotrade.set_settings(uid2, min_pop=50, reserve_pct=0, max_trade_pct=50)
legs = [{"side": "PE", "strike": 900.0}]
cycles = [
    # Scores highest, but inside the entry floor: never auto-traded.
    {"symbol": SYM, "expiry": "2099-01-01", "dte": config.MIN_DTE - 5, "legs": legs,
     "strategy": {"pop": 99.0, "roi_pct": 9.0, "margin": 100_000.0}},
    {"symbol": SYM, "expiry": EXP, "dte": DTE, "legs": legs,
     "strategy": {"pop": 95.0, "roi_pct": 2.0, "margin": 100_000.0}},
    {"symbol": SYM, "expiry": "2099-02-01", "dte": DTE + 30, "legs": legs,
     "strategy": {"pop": 95.0, "roi_pct": 1.0, "margin": 100_000.0}},
]
r = autotrade.run(uid2, cycles, trigger="manual")
with db.tx(uid2) as c:
    exps = [o["expiry"] for o in c.all("SELECT DISTINCT expiry FROM pending_orders WHERE user_id=:u", u=uid2)]
print("multi-cycle run:", r["placed"], "orders on", exps)
if not (len(r["placed"]) == 1 and [str(e) for e in exps] == [EXP]):
    fails.append("multi-cycle stock: expected exactly one order, on the best cycle at or past MIN_DTE")

print("ALL PASS" if not fails else f"FAIL: {fails}")
sys.exit(1 if fails else 0)
