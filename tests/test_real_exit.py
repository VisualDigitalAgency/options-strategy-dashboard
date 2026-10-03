"""Real account Portfolio: the broker's option positions grouped like the virtual ones, and "Exit group":
BUY LIMIT at the ask for every short (SELL LIMIT at the bid for a long), previewed then confirmed with a
one-time token that only the exit endpoint can redeem, checked against the live position before each leg."""
import sys
from datetime import datetime, timedelta, timezone

import server
from engine import auth, cache, db, users, virtual
from engine.brokers import registry
from engine.brokers.base import BrokerOrderResult, BrokerSession
from support import EXP, SYM, stub

fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


class Fake:
    name = "zerodha"
    supports_stop_alerts = True

    def __init__(self):
        self.orders, self.results, self.positions = [], [], []

    def login_url(self):
        return "https://kite.example/login"

    def exchange_request_token(self, request_token):
        return BrokerSession(access_token="tok", broker_user_id="ZF1"), datetime.now(timezone.utc) + timedelta(hours=6)

    def invalidate(self, session):
        pass

    def tradingsymbol(self, session, symbol, expiry, side, strike):
        return f"{symbol}{int(strike)}{side}"

    def contract(self, session, tsym):
        for side in ("CE", "PE"):
            if tsym.endswith(side) and tsym.startswith(SYM):
                return {"symbol": SYM, "expiry": EXP, "side": side, "strike": float(tsym[len(SYM):-2]), "lot_size": 100}
        return None

    def get_positions(self, session):
        return self.positions

    def get_margins(self, session):
        return {"available_margin": 1e9}

    def _place(self, action, kw):
        self.orders.append({"action": action, **kw})
        r = self.results.pop(0) if self.results else BrokerOrderResult(f"oid{len(self.orders)}", "open")
        if isinstance(r, Exception):
            raise r
        return r

    def place_buy_limit_order(self, session, **kw):
        return self._place("BUY", kw)

    def place_sell_limit_order(self, session, **kw):
        return self._place("SELL", kw)


fake = Fake()
registry.adapter = lambda name: fake
ORIGIN = "https://t.example"
server.ALLOWED_ORIGINS = {ORIGIN}
server.universe = lambda: [SYM]
stub(True)
# ask 5.3 / bid 5.0 for every contract
virtual.quote = lambda s, e, side, k, live=False: {"spot": 1000.0, "ltp": 5.0, "bid": 5.0, "ask": 5.3, "iv": 20.0, "oi": 10_000}


def call(method, params, client):
    r = client.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, headers={"Origin": ORIGIN})
    return r.get_json()


def client_for(uid):
    c = server.app.test_client()
    c.set_cookie(server.COOKIE, auth.new_session(uid, "127.0.0.1", "t"))
    return c


owner = users.create_user("o@test.example", "Owner", role="owner", status="active")
plain = users.create_user("p@test.example", "Plain", status="active")
oc, pc = client_for(owner), client_for(plain)
state = call("broker_connect_url", {}, oc)["result"]["state"]
check("connected", call("broker_exchange_token", {"request_token": "r", "state": state}, oc)["result"]["status"] == "active")


def snap(rows):
    fake.positions = rows
    cache.set_json(f"broker_snap:{owner}", {"positions": rows, "margins": {"available_margin": 1e9}}, ttl=120)


def pos(tsym, qty, avg=10.0, exchange="NFO"):
    return {"tradingsymbol": tsym, "exchange": exchange, "quantity": qty, "average_price": avg}


# 1. Grouping: option positions by stock and expiry, in the virtual group shape; others dropped.
snap([pos(f"{SYM}900PE", -100), pos(f"{SYM}1100CE", -100), pos(f"{SYM}950PE", 0), pos("RELIANCE", 10, exchange="NSE")])
j = call("broker_position_groups", {}, oc)
g = j["result"]["groups"][0] if j.get("result") and j["result"]["groups"] else {}
check("one group, two open legs", len(j["result"]["groups"]) == 1 and len(g["legs"]) == 2, j.get("error") or [l["id"] for l in g.get("legs", [])])
check("strategy label like the virtual one", g.get("strategy") == "Short strangle", g.get("strategy"))
check("priced like a virtual group", g["legs"][0]["ask"] == 5.3 and g["spot"] == 1000.0 and "greeks" in g and "pnl_exit" in g)

# 2. Preview: shorts bought back at the ask; a long is sold at the bid, last.
snap([pos(f"{SYM}900PE", -100), pos(f"{SYM}1100CE", 100), pos(f"{SYM}1000CE", -100)])
j = call("broker_preview_exit_group", {"symbol": SYM, "expiry": EXP}, oc)
legs = j["result"]["legs"]
check("shorts first, long last", [l["action"] for l in legs] == ["BUY", "BUY", "SELL"], [l["action"] for l in legs])
check("BUY at the ask, SELL at the bid", [l["limit_price"] for l in legs] == [5.3, 5.3, 5.0], [l["limit_price"] for l in legs])
check("full quantity", all(l["qty"] == 100 for l in legs))
tok = j["result"]["confirm_token"]
check("nothing sent at preview", fake.orders == [])

# 3. The exit token can't place a sell order, and a sell token can't place an exit.
j2 = call("broker_place_order", {"confirm_token": tok}, oc)
check("place_order refuses an exit token", "expired" in (j2.get("error", {}).get("message") or ""), j2.get("error"))
check("still nothing sent", fake.orders == [])

# 4. Place: legs go out in order; the token is one use.
j = call("broker_place_exit_group", {"confirm_token": tok}, oc)
check("all legs placed", len(j.get("result", {}).get("placed", [])) == 3, j)
check("BUY LIMIT at the ask, then SELL LIMIT", [(o["action"], o["limit_price"]) for o in fake.orders] == [("BUY", 5.3), ("BUY", 5.3), ("SELL", 5.0)], fake.orders)
j = call("broker_place_exit_group", {"confirm_token": tok}, oc)
check("token is one use", "expired" in (j.get("error", {}).get("message") or ""), j.get("error"))
check("no second round of orders", len(fake.orders) == 3)

# 5. A position that changed since the preview stops the exit before anything else is sent.
fake.orders.clear()
snap([pos(f"{SYM}900PE", -100)])
tok = call("broker_preview_exit_group", {"symbol": SYM, "expiry": EXP}, oc)["result"]["confirm_token"]
fake.positions = [pos(f"{SYM}900PE", -200)]  # sold more at Zerodha after the preview
j = call("broker_place_exit_group", {"confirm_token": tok}, oc)
check("changed position: refused, nothing sent", "changed since the preview" in (j.get("error", {}).get("message") or "") and fake.orders == [], j.get("error"))

# 6. A rejected leg stops the rest; an unanswered one says so.
snap([pos(f"{SYM}900PE", -100), pos(f"{SYM}1100CE", -100)])
tok = call("broker_preview_exit_group", {"symbol": SYM, "expiry": EXP}, oc)["result"]["confirm_token"]
fake.orders.clear()
fake.results = [BrokerOrderResult("", "rejected", "RMS: insufficient margin")]
j = call("broker_place_exit_group", {"confirm_token": tok}, oc)
check("rejected first leg: stop, one attempt", "rejected" in (j.get("error", {}).get("message") or "") and len(fake.orders) == 1, j.get("error"))
tok = call("broker_preview_exit_group", {"symbol": SYM, "expiry": EXP}, oc)["result"]["confirm_token"]
fake.orders.clear()
fake.results = [BrokerOrderResult("o1", "open"), TimeoutError("gateway")]
j = call("broker_place_exit_group", {"confirm_token": tok}, oc)
check("unanswered leg: stop and say so", "didn't answer" in (j.get("error", {}).get("message") or "") and len(fake.orders) == 2, j.get("error"))

# 7. Access: the exit endpoints need live_trading and an open position.
j = call("broker_preview_exit_group", {"symbol": SYM, "expiry": EXP}, pc)
check("a plain user is refused", j.get("error", {}).get("code") == -32003, j.get("error"))
snap([])
j = call("broker_preview_exit_group", {"symbol": SYM, "expiry": EXP}, oc)
check("no position: nothing to exit", "No open" in (j.get("error", {}).get("message") or ""), j.get("error"))
with db.tx() as c:
    rows = c.all("SELECT detail FROM audit_log WHERE action='broker_exit_placed' ORDER BY id")
check("every placed leg is audited with its order id", len(rows) >= 4 and all("broker_order_id" in r["detail"] for r in rows), len(rows))

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
