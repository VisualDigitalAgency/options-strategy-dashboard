"""Real broker connection (phase 1: Zerodha) — admin-only connect, single-active-connection
enforcement, encrypted token storage, and the preview/confirm/place order flow against a fake
adapter (never a real Zerodha call)."""
import sys
from datetime import datetime, timedelta, timezone

import server
from engine import auth, broker, broker_crypto, cache, db, users
from engine.brokers import registry
from engine.brokers.base import BrokerOrderResult, BrokerSession
from support import EXP, SYM, stub

fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


class FakeAdapter:
    """Never touches a network. `place_results` is consumed one result per call, in order, so a
    test can script "leg 1 fills, leg 2 is rejected by the broker"."""
    name = "zerodha"

    def __init__(self):
        self.place_results = []
        self.invalidated = []

    def login_url(self):
        return "https://kite.zerodha.com/connect/login?fake=1"

    def exchange_request_token(self, request_token):
        return BrokerSession(access_token=f"tok-{request_token}", broker_user_id="ZF1234",
                              public_token="pub-1"), datetime.now(timezone.utc) + timedelta(hours=6)

    def invalidate(self, session):
        self.invalidated.append(session.access_token)

    def place_sell_limit_order(self, session, **kw):
        return self.place_results.pop(0)

    def get_order_status(self, session, broker_order_id):
        return {"status": "COMPLETE"}

    def get_positions(self, session):
        return []

    def get_margins(self, session):
        return {"available_margin": 0.0}


fake = FakeAdapter()
registry.adapter = lambda name: fake  # engine.broker imported `registry`, not individual names

ORIGIN = "https://t.example"
server.ALLOWED_ORIGINS = {ORIGIN}
server.universe = lambda: [SYM]
app = server.app.test_client()
stub(True)  # market open: legs fill at once, simplest case for pricing


def call(method, params, client):
    r = client.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                     headers={"Origin": ORIGIN})
    return r.get_json()


def client_for(uid):
    c = server.app.test_client()
    c.set_cookie(server.COOKIE, auth.new_session(uid, "127.0.0.1", "t"))
    return c


# ---------- admin-only connect ----------

plain_uid = users.create_user("plain@test.example", "Plain", status="active")
admin_uid = users.create_user("admin@test.example", "Admin", role="admin", status="active")
plain_c, admin_c = client_for(plain_uid), client_for(admin_uid)

j = call("broker_connect_url", {}, plain_c)
check("non-admin is refused broker_connect_url", j.get("error", {}).get("code") == -32003, j.get("error"))

j = call("broker_connect_url", {}, admin_c)
check("admin gets a login url", j.get("result", {}).get("url") == fake.login_url(), j)
state = j["result"]["state"]

j = call("broker_exchange_token", {"request_token": "abc123", "state": "wrong-state"}, admin_c)
check("mismatched state is refused", j.get("error", {}).get("code") == -32000, j.get("error"))

j = call("broker_connect_url", {}, admin_c)
state = j["result"]["state"]
j = call("broker_exchange_token", {"request_token": "abc123", "state": state}, admin_c)
check("admin connects", j.get("result", {}).get("status") == "active", j)

with db.tx(admin_uid) as c:
    row = c.one("SELECT * FROM broker_connections WHERE user_id=:u AND status='active'", u=admin_uid)
check("one active row exists", row is not None, row)
check("access token stored encrypted, not in plain text", row and row["access_token_enc"] != b"tok-abc123", row and row["access_token_enc"])
check("stored token decrypts back correctly", row and broker_crypto.decrypt(row["access_token_enc"]) == "tok-abc123")

j = call("broker_connect_url", {}, admin_c)
state = j["result"]["state"]
j = call("broker_exchange_token", {"request_token": "xyz789", "state": state}, admin_c)
check("second connect is refused with the friendly message", "already connected" in (j.get("error", {}).get("message") or ""), j.get("error"))

j = call("broker_status", {}, admin_c)
check("broker_status reports active, no secrets", j["result"]["status"] == "active" and "access_token" not in j["result"], j["result"])

j = call("broker_status", {}, plain_c)
check("a user with no connection sees disconnected", j["result"]["status"] == "disconnected", j["result"])

# ---------- account_summary: real vs approx ----------

cache.set_json(f"broker_snap:{admin_uid}", {
    "positions": [{"tradingsymbol": "X", "quantity": -50}, {"tradingsymbol": "Y", "quantity": 0}],
    "margins": {"cash_margin": 500000.0, "collateral_margin": 120000.0, "used_margin": 300000.0,
                "span": 250000.0, "exposure": 40000.0},
}, ttl=60)
j = call("broker_account_summary", {}, admin_c)
r = j.get("result", {})
check("connected admin gets real figures", r.get("source") == "broker" and r.get("available_margin_total") == 620000.0
      and r.get("span") == 250000.0 and r.get("exposure") == 40000.0 and r.get("total_collateral") == 120000.0, r)
check("connected admin's open_positions only counts non-zero-qty legs", r.get("open_positions") == 1, r)

j = call("broker_account_summary", {}, plain_c)
r = j.get("result", {})
check("a user with no connection gets an approximation from the virtual account", r.get("source") == "approx" and r.get("status") == "disconnected", r)
check("approx has no real collateral", r.get("total_collateral") == 0.0, r)

# ---------- preview + margin check ----------

LEGS = [{"side": "CE", "strike": 1100.0, "action": "SELL", "lots": 1}]
cache.set_json(f"broker_snap:{admin_uid}", {"positions": [], "margins": {"available_margin": 0.0}}, ttl=60)
j = call("broker_preview_order", {"symbol": SYM, "expiry": EXP, "legs": LEGS}, admin_c)
check("insufficient real margin is refused before touching the broker", j.get("error", {}).get("code") == -32000 and "Insufficient" in j["error"]["message"], j.get("error"))

cache.set_json(f"broker_snap:{admin_uid}", {"positions": [], "margins": {"available_margin": 10_000_000.0}}, ttl=60)
j = call("broker_preview_order", {"symbol": SYM, "expiry": EXP, "legs": LEGS}, admin_c)
check("sufficient margin returns a confirm_token", "confirm_token" in j.get("result", {}), j.get("error") or j.get("result"))
token = j["result"]["confirm_token"]

j = call("broker_place_order", {"confirm_token": "not-a-real-token"}, admin_c)
check("an unknown confirm_token is refused", j.get("error", {}).get("code") == -32000, j.get("error"))

fake.place_results = [BrokerOrderResult(broker_order_id="KITE1", status="open")]
j = call("broker_place_order", {"confirm_token": token}, admin_c)
check("order placed, one broker_orders row written", len(j.get("result", {}).get("placed", [])) == 1, j)

with db.tx(admin_uid) as c:
    rows = c.all("SELECT * FROM broker_orders WHERE user_id=:u ORDER BY id", u=admin_uid)
check("broker_orders has exactly one row", len(rows) == 1, len(rows))
check("that row's status is 'open'", rows[0]["status"] == "open", rows[0]["status"] if rows else None)

j = call("broker_place_order", {"confirm_token": token}, admin_c)
check("a confirm_token is one-time use", j.get("error", {}).get("code") == -32000, j.get("error"))

# ---------- partial-leg-failure: stop after the first success, no rollback ----------

MULTI_LEGS = [{"side": "CE", "strike": 1100.0, "action": "SELL", "lots": 1},
              {"side": "PE", "strike": 900.0, "action": "SELL", "lots": 1}]
j = call("broker_preview_order", {"symbol": SYM, "expiry": EXP, "legs": MULTI_LEGS}, admin_c)
token2 = j["result"]["confirm_token"]
fake.place_results = [BrokerOrderResult(broker_order_id="KITE2", status="open"),
                       BrokerOrderResult(broker_order_id="", status="rejected", reject_reason="RMS: margin exceeded")]
j = call("broker_place_order", {"confirm_token": token2}, admin_c)
check("partial failure surfaces as an error naming the failed leg", "Leg 2 of 2" in (j.get("error", {}).get("message") or ""), j.get("error"))
check("the error says the already-placed leg is live and must be managed manually", "manage them manually" in (j.get("error", {}).get("message") or ""), j.get("error"))

with db.tx(admin_uid) as c:
    rows = c.all("SELECT status FROM broker_orders WHERE user_id=:u ORDER BY id", u=admin_uid)
check("first leg's row stays 'open', second is 'rejected', no third leg attempted",
      [r["status"] for r in rows] == ["open", "open", "rejected"], [r["status"] for r in rows])

# ---------- disconnect ----------

j = call("broker_disconnect", {}, admin_c)
check("disconnect succeeds", j.get("result", {}).get("status") == "disconnected", j)
check("adapter.invalidate was called (best-effort)", len(fake.invalidated) == 1, fake.invalidated)
j = call("broker_status", {}, admin_c)
check("status now disconnected", j["result"]["status"] == "disconnected", j["result"])

# Reconnecting after a clean disconnect must work (the partial unique index only blocks a
# *second active* row, not a new one after the old one is disconnected).
j = call("broker_connect_url", {}, admin_c)
state = j["result"]["state"]
j = call("broker_exchange_token", {"request_token": "again1", "state": state}, admin_c)
check("can reconnect after disconnecting", j.get("result", {}).get("status") == "active", j)

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
