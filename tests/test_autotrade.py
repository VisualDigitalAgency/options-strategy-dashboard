"""Auto-trade must not place the same setup twice while the first order is still waiting to fill.
Market closed, so the first run's SELL rests as an open order; then run again."""
import sys

from engine import autotrade, db, users, virtual
from support import EXP, SYM, stub

stub(False)  # market closed: orders rest as open limit orders
uid = users.create_user("auto@test.example", "Auto", status="active")
autotrade.set_settings(uid, min_pop=50, reserve_pct=0, max_trade_pct=50)
cand = [{"symbol": SYM, "expiry": EXP, "legs": [{"side": "PE", "strike": 900.0}],
         "strategy": {"pop": 95.0, "roi_pct": 1.5, "margin": 100_000.0}}]

runs = [autotrade.run(uid, cand, trigger="manual") for _ in range(2)]
with db.tx(uid) as c:
    orders = c.all("SELECT action, qty FROM pending_orders WHERE user_id=:u AND status='open'", u=uid)
for i, r in enumerate(runs, 1):
    print(f"run #{i}: placed={len(r['placed'])} skipped={[s['reason'] for s in r['skipped']]}")
print("open orders:", orders)
ok = len(runs[0]["placed"]) == 1 and len(runs[1]["placed"]) == 0 and len(orders) == 1
print("ALL PASS" if ok else "FAIL: the second run placed the same setup again")
sys.exit(0 if ok else 1)
