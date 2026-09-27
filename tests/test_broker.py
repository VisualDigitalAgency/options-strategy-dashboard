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
    supports_stop_alerts = True

    def __init__(self):
        self.place_results = []
        self.invalidated = []
        self.order_status = {}
        self.alerts_created, self.alerts_deleted = [], []
        self.alert_error = None
        self.alert_state = {"status": "enabled", "alert_count": 0}

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
        return self.order_status.get(broker_order_id, {"status": "OPEN"})

    def tradingsymbol(self, session, symbol, expiry, side, strike):
        return f"{symbol}{int(strike)}{side}"

    def create_stop_alert(self, session, **kw):
        if self.alert_error:
            raise RuntimeError(self.alert_error)
        self.alerts_created.append(kw)
        return f"alert-{len(self.alerts_created)}"

    def get_alert(self, session, alert_id):
        return self.alert_state

    def delete_alert(self, session, alert_id):
        self.alerts_deleted.append(alert_id)

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
    "margins": {"available_margin": 320000.0, "cash_margin": 500000.0, "collateral_margin": 120000.0, "used_margin": 300000.0,
                "span": 250000.0, "exposure": 40000.0},
}, ttl=60)
j = call("broker_account_summary", {}, admin_c)
r = j.get("result", {})
check("connected admin gets real figures", r.get("source") == "broker" and r.get("available_margin_total") == 320000.0
      and r.get("span") == 250000.0 and r.get("exposure") == 40000.0 and r.get("total_collateral") == 120000.0, r)
check("connected admin's open_positions only counts non-zero-qty legs", r.get("open_positions") == 1, r)
check("admin's connectable list includes zerodha", r.get("connectable") == ["zerodha"], r)

j = call("broker_account_summary", {}, plain_c)
r = j.get("result", {})
check("a user with no connection gets an approximation from the virtual account", r.get("source") == "approx" and r.get("status") == "disconnected", r)
check("approx has no real collateral", r.get("total_collateral") == 0.0, r)
check("a non-admin's connectable list is empty (phase 1: admin-only)", r.get("connectable") == [], r)

# ---------- preview + margin check ----------

LEGS = [{"side": "CE", "strike": 1100.0, "action": "SELL", "lots": 1}]
cache.set_json(f"broker_snap:{admin_uid}", {"positions": [], "margins": {"available_margin": 0.0}}, ttl=60)
j = call("broker_preview_order", {"symbol": SYM, "expiry": EXP, "legs": LEGS}, admin_c)
check("insufficient real margin is refused before touching the broker", j.get("error", {}).get("code") == -32000 and "Insufficient" in j["error"]["message"], j.get("error"))

cache.set_json(f"broker_snap:{admin_uid}", {"positions": [], "margins": {"available_margin": 10_000_000.0}}, ttl=60)
j = call("broker_preview_order", {"symbol": SYM, "expiry": EXP, "legs": LEGS}, admin_c)
check("sufficient margin returns a confirm_token", "confirm_token" in j.get("result", {}), j.get("error") or j.get("result"))
token = j["result"]["confirm_token"]
need = j["result"]["margin"]["total"]

# ---------- issue #40: gating uses the broker's net figure, so collateral counts in full ----------

cache.set_json(f"broker_snap:{admin_uid}", {"positions": [], "margins": {
    "available_margin": need, "cash_margin": 0.0, "collateral_margin": need,
    "collateral_liquid_used": need, "collateral_equity_used": 0.0,
}}, ttl=60)
j = call("broker_preview_order", {"symbol": SYM, "expiry": EXP, "legs": LEGS}, admin_c)
check("zero cash but enough net margin from liquid collateral is allowed (#40)", "confirm_token" in j.get("result", {}), j.get("error") or j.get("result"))

cache.set_json(f"broker_snap:{admin_uid}", {"positions": [], "margins": {
    "available_margin": need - 1, "cash_margin": 0.0, "collateral_margin": need * 3,
}}, ttl=60)
j = call("broker_preview_order", {"symbol": SYM, "expiry": EXP, "legs": LEGS}, admin_c)
check("net margin just below the requirement is refused, however large gross collateral is",
      j.get("error", {}).get("code") == -32000 and "Insufficient" in j["error"]["message"], j.get("error"))

cache.set_json(f"broker_snap:{admin_uid}", {"positions": [], "margins": {"available_margin": 10_000_000.0}}, ttl=60)
j = call("broker_preview_order", {"symbol": SYM, "expiry": EXP, "legs": LEGS}, admin_c)
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

# ---------- issue #43: day-15 broker stop = a Kite ATO alert, installed once, never an edit ----------

IST = timezone(timedelta(hours=5, minutes=30))
filled = datetime.now(IST).replace(hour=10, minute=0, second=0, microsecond=0)
day = lambda n: filled + timedelta(days=n, hours=1)
fake.order_status = {"KITE1": {"status": "COMPLETE", "average_price": 30.0,
                               "exchange_timestamp": filled.strftime("%Y-%m-%d %H:%M:%S")}}
short = [{"tradingsymbol": f"{SYM}1100CE", "quantity": -100}]
sess = BrokerSession(access_token="t")


def stop_rows():
    with db.tx(admin_uid) as c:
        return c.all("SELECT kite_order_id, status, sl_price, sl_alert_status, sl_alert_uuid, sl_alert_error "
                     "FROM broker_orders WHERE user_id=:u AND kite_order_id IS NOT NULL ORDER BY id", u=admin_uid)


n = broker.sync_stop_alerts(admin_uid, "zerodha", sess, short, _now=day(3))
r = stop_rows()
check("a filled entry is recorded with its stop at the fill price, no alert before day 15",
      n["filled"] == 1 and r[0]["status"] == "complete" and float(r[0]["sl_price"]) == 30.0
      and r[0]["sl_alert_status"] == "pending" and not fake.alerts_created, (n, r[0]))
check("an entry still open at the broker is left alone", r[1]["status"] == "open" and r[1]["sl_alert_status"] == "pending", r[1])
check("no order is placed by the sync", fake.place_results == [], fake.place_results)

fake.alert_error = "Kite: alerts limit reached"
n = broker.sync_stop_alerts(admin_uid, "zerodha", sess, short, _now=day(15))
check("a failed install is recorded, not retried on the next pass",
      n["failed"] == 1 and stop_rows()[0]["sl_alert_error"] == "Kite: alerts limit reached", (n, stop_rows()[0]))
fake.alert_error = None
n = broker.sync_stop_alerts(admin_uid, "zerodha", sess, short, _now=day(15) + timedelta(minutes=5))
check("retry waits for BROKER_SL_RETRY_SECONDS", n["installed"] == 0 and not fake.alerts_created, n)

n = broker.sync_stop_alerts(admin_uid, "zerodha", sess, short, _now=day(15) + timedelta(hours=2))
a = fake.alerts_created[0] if fake.alerts_created else {}
check("day 15: one ATO alert installed for the leg", n["installed"] == 1 and len(fake.alerts_created) == 1, n)
check("alert triggers at the original premium and buys back the full qty with a capped limit",
      a.get("tradingsymbol") == f"{SYM}1100CE" and a.get("qty") == 100 and a.get("trigger_price") == 30.0
      and a.get("limit_price") == 33.0, a)
check("the alert is tracked on the order", stop_rows()[0]["sl_alert_status"] == "enabled"
      and stop_rows()[0]["sl_alert_uuid"] == "alert-1" and stop_rows()[0]["sl_alert_error"] is None, stop_rows()[0])

broker.sync_stop_alerts(admin_uid, "zerodha", sess, short, _now=day(16))
check("an installed alert is never created again", len(fake.alerts_created) == 1, len(fake.alerts_created))

j = call("broker_stop_alerts", {}, admin_c)
rows = j.get("result", [])
mine = [x for x in rows if x["sl_alert_status"] == "enabled"]
check("broker_stop_alerts lists the leg with its stop and activation date",
      len(mine) == 1 and mine[0]["sl_price"] == 30.0
      and mine[0]["sl_activates_on"] == str((filled + timedelta(days=15)).date()), rows)

fake.alert_state = {"status": "enabled", "alert_count": 1}
n = broker.sync_stop_alerts(admin_uid, "zerodha", sess, short, _now=day(17))
check("a fired alert is marked triggered", n["updated"] == 1 and stop_rows()[0]["sl_alert_status"] == "triggered", stop_rows()[0])

# The position was closed by hand after the alert went in: remove the alert so it can't open a long.
with db.tx(admin_uid) as c:
    c.run("UPDATE broker_orders SET sl_alert_status='enabled' WHERE user_id=:u AND kite_order_id='KITE1'", u=admin_uid)
n = broker.sync_stop_alerts(admin_uid, "zerodha", sess, [], _now=day(18))
check("alert deleted when the leg is no longer short at the broker",
      n["cancelled"] == 1 and fake.alerts_deleted == ["alert-1"] and stop_rows()[0]["sl_alert_status"] == "cancelled", (n, stop_rows()[0]))

# A leg closed before day 15 never gets an alert.
fake.order_status["KITE2"] = {"status": "COMPLETE", "average_price": 12.0,
                              "exchange_timestamp": filled.strftime("%Y-%m-%d %H:%M:%S")}
n = broker.sync_stop_alerts(admin_uid, "zerodha", sess, [], _now=day(15) + timedelta(hours=3))
check("a leg already closed at day 15 is skipped, no alert", n["installed"] == 0
      and stop_rows()[1]["sl_alert_status"] == "skipped" and len(fake.alerts_created) == 1, stop_rows()[1])

# A broker without broker-held trigger orders: marked for the user to manage, never retried.
fake.supports_stop_alerts = False
with db.tx(admin_uid) as c:
    c.run("UPDATE broker_orders SET sl_alert_status='pending', sl_alert_uuid=NULL, sl_alert_error=NULL "
          "WHERE user_id=:u AND kite_order_id='KITE1'", u=admin_uid)
n = broker.sync_stop_alerts(admin_uid, "zerodha", sess, short, _now=day(19))
check("no stop-alert support: skipped with a clear reason, nothing created",
      n["installed"] == 0 and n["failed"] == 0 and len(fake.alerts_created) == 1
      and stop_rows()[0]["sl_alert_status"] == "skipped"
      and "manage the stop yourself" in (stop_rows()[0]["sl_alert_error"] or ""), stop_rows()[0])
fake.supports_stop_alerts = True

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
