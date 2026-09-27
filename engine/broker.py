"""Real-broker RPC-facing functions (phase 1: Zerodha only, admin-gated, manual-confirm-only).

Mirrors engine/virtual.py's shape for the parts that are analogous (quote/margin pricing,
one-row-per-user connection state) but everything here talks to a real broker with real money,
so nothing here is reachable except through the guarded RPC entries in server.py:
  - broker_connect_url / broker_exchange_token: ADMIN_METHODS (phase-1 soft launch)
  - broker_status / broker_disconnect / broker_get_positions / broker_get_margins /
    broker_preview_order / broker_place_order: USER_METHODS

This app only sells options, so every leg placed here is a SELL, LIMIT order — no order-type or
transaction-type choice is exposed to the caller.
"""

import logging
import secrets as _secrets
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy.exc import IntegrityError

from . import auth, broker_crypto, cache, config, data_fetch, db, virtual
from .brokers import registry
from .brokers.base import BrokerSession

log = logging.getLogger("theta.broker")
CONFIRM_TTL = 60  # seconds a previewed order stays valid for confirmation
IST = timezone(timedelta(hours=5, minutes=30))  # db.Tx returns timestamps as "YYYY-MM-DD HH:MM:SS" in IST, not datetimes


def _parse_ist(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)


class AlreadyConnected(ValueError):
    pass


class _Inactive(ValueError):
    """Raised by _require_active; carries the row it found (or None) so a caller that needs the
    connection's last-known state (account_summary's approx fallback) doesn't have to fetch it
    again — every other caller just lets this propagate as a plain ValueError message."""

    def __init__(self, message: str, row: dict | None):
        super().__init__(message)
        self.row = row


def _row_to_session(row: dict) -> BrokerSession:
    return BrokerSession(access_token=broker_crypto.decrypt(row["access_token_enc"]),
                          broker_user_id=row["broker_user_id"],
                          public_token=broker_crypto.decrypt(row["public_token_enc"]) if row["public_token_enc"] else None)


def _latest_connection_row(user_id: int) -> dict | None:
    """The newest broker_connections row for this user, any status. A new connection is always a
    fresh INSERT (status transitions UPDATE the existing row, never re-activate an old one) and
    only one row per user can be status='active' (partial unique index), so whenever an active row
    exists it is always this one — the same row a `WHERE status='active'` query would find."""
    with db.tx(user_id) as c:
        return c.one("SELECT * FROM broker_connections WHERE user_id=:u ORDER BY id DESC LIMIT 1", u=user_id)


def _active_connection(user_id: int) -> dict | None:
    row = _latest_connection_row(user_id)
    return row if row and row["status"] == "active" else None


OAUTH_STATE_TTL = 600  # seconds a connect attempt's CSRF state stays valid


def connect_url(user_id: int, broker: str = "zerodha") -> dict:
    """Returns the Zerodha login URL plus a one-time `state` the caller must echo back to
    broker_exchange_token. Kite's own redirect doesn't forward custom query params, so the state
    is bound server-side to this admin's user_id and round-tripped by the frontend via
    sessionStorage (same browser tab, survives the redirect) rather than via the URL, closing a
    login-CSRF hole where an attacker could otherwise trick an admin into linking the attacker's
    own Zerodha account by submitting a request_token the attacker obtained themselves."""
    if broker not in registry.CONNECTABLE:
        raise ValueError(f"{broker} isn't connectable yet")
    state = _secrets.token_urlsafe(24)
    cache.set_json(f"broker_oauth_state:{user_id}", {"state": state, "broker": broker}, ttl=OAUTH_STATE_TTL)
    return {"url": registry.adapter(broker).login_url(), "state": state}


def exchange_token(admin_user_id: int, request_token: str, state: str, broker: str = "zerodha") -> dict:
    """Completes the OAuth-style redirect: exchanges Zerodha's one-time request_token for a
    per-user access token, and stores it encrypted. Enforces one active connection per user."""
    if broker not in registry.CONNECTABLE:
        raise ValueError(f"{broker} isn't connectable yet")
    pending = cache.get_json(f"broker_oauth_state:{admin_user_id}")
    cache.delete(f"broker_oauth_state:{admin_user_id}")  # one-time use, whether or not it matches
    if not pending or pending.get("broker") != broker or not _secrets.compare_digest(pending.get("state", ""), state):
        raise ValueError("This connect attempt has expired or is invalid; start connecting again")
    if _active_connection(admin_user_id):
        raise AlreadyConnected("You're already connected to another broker. Disconnect it first to connect this one.")
    session, expires_at = registry.adapter(broker).exchange_request_token(request_token)
    existing = _active_connection(admin_user_id)
    if existing:  # fast path: no need to touch the broker again if already connected
        raise AlreadyConnected("You're already connected to another broker. Disconnect it first to connect this one.")
    try:
        with db.tx(admin_user_id) as c:
            c.run("INSERT INTO broker_connections (user_id, broker, broker_user_id, access_token_enc, "
                  "public_token_enc, token_expires_at) VALUES (:u, :b, :bu, :at, :pt, :exp)",
                  u=admin_user_id, b=broker, bu=session.broker_user_id,
                  at=broker_crypto.encrypt(session.access_token),
                  pt=broker_crypto.encrypt(session.public_token) if session.public_token else None,
                  exp=expires_at)
    except IntegrityError:
        # broker_connections_one_active caught a genuine race (two tabs completing the redirect
        # at once) that the pre-check above couldn't see; same friendly error, not a 500.
        raise AlreadyConnected("You're already connected to another broker. Disconnect it first to connect this one.")
    auth.audit("broker_connected", actor_id=admin_user_id, target_user_id=admin_user_id, broker=broker)
    return {"status": "active", "broker": broker}


_STATUS_FIELDS = ("broker", "status", "broker_user_id", "connected_at", "token_expires_at", "last_synced_at")


def status(user_id: int) -> dict:
    row = _latest_connection_row(user_id)
    if not row:
        return {"broker": None, "status": "disconnected"}
    return {k: row[k] for k in _STATUS_FIELDS}  # never the raw row: access_token_enc/public_token_enc/id must not leave this module


def disconnect(user_id: int) -> dict:
    row = _active_connection(user_id)
    if not row:
        raise ValueError("No broker is connected")
    try:
        registry.adapter(row["broker"]).invalidate(_row_to_session(row))
    except Exception:
        log.warning("broker invalidate failed for user %s", user_id, exc_info=True)
    with db.tx(user_id) as c:
        c.run("UPDATE broker_connections SET status='disconnected', disconnected_at=now() "
              "WHERE id=:id", id=row["id"])
    cache.delete(f"broker_snap:{user_id}")
    auth.audit("broker_disconnected", actor_id=user_id, target_user_id=user_id, broker=row["broker"])
    return {"status": "disconnected"}


def _require_active(user_id: int) -> dict:
    row = _latest_connection_row(user_id)
    if not row or row["status"] != "active":
        raise _Inactive("No broker is connected", row)
    if row["token_expires_at"] and datetime.now(timezone.utc) >= _parse_ist(row["token_expires_at"]):
        with db.tx(user_id) as c:
            c.run("UPDATE broker_connections SET status='expired' WHERE id=:id", id=row["id"])
        raise _Inactive("Your broker connection has expired; please reconnect", {**row, "status": "expired"})
    return row


_EMPTY_MARGINS = {"available_margin": 0.0, "cash_margin": 0.0, "collateral_margin": 0.0, "used_margin": 0.0,
                   "span": 0.0, "exposure": 0.0, "collateral_liquid_used": 0.0, "collateral_equity_used": 0.0}


def get_positions(user_id: int) -> list[dict]:
    _require_active(user_id)
    return (cache.get_json(f"broker_snap:{user_id}") or {}).get("positions", [])


def get_margins(user_id: int) -> dict:
    _require_active(user_id)
    return (cache.get_json(f"broker_snap:{user_id}") or {}).get("margins", _EMPTY_MARGINS)


def _usable_collateral_for(margin_total: float, collateral_total: float, collateral_used: float) -> float:
    """How much of a real order's own margin an exchange lets non-cash collateral fund: the
    account's unused collateral capacity (total collateral minus what's already backing other
    open positions), capped at config.COLLATERAL_UTILISATION_CAP of *this order's* margin — never
    a blanket cash+collateral sum (see the a15bedd fix this replaces)."""
    remaining = collateral_total - collateral_used
    return min(max(remaining, 0.0), margin_total * config.COLLATERAL_UTILISATION_CAP)


def connectable_brokers(user_id: int) -> list[str]:
    """Which brokers this specific user may connect right now (phase 1: admins only). The single
    source of truth for "can this user connect broker X" — frontend components read this instead
    of each re-deriving role-and-broker checks locally."""
    user = auth.active_user(user_id)
    return sorted(registry.CONNECTABLE) if user and user["role"] == "admin" else []


def account_summary(user_id: int) -> dict:
    """Unified real-or-approx shape for every place that shows margin figures for real trading:
    the broker account page, the broker connect banner, and the order ticket's real-order side.
    Real figures when an active, unexpired connection exists (reusing _require_active, so an
    expired connection is flipped to 'expired' here the same as everywhere else that checks it);
    otherwise the virtual account's own numbers stand in as an approximation, clearly flagged via
    `source`. Both branches feed the same margin-shaped dict `m` into one return statement instead
    of duplicating the 10-key result. The fallback reads the connection row off the _Inactive
    exception rather than querying it again via status()."""
    try:
        row = _require_active(user_id)
        snap = cache.get_json(f"broker_snap:{user_id}") or {}
        m = snap.get("margins", _EMPTY_MARGINS)
        source, broker, conn_status = "broker", row["broker"], "active"
        open_positions = sum(1 for p in snap.get("positions", []) if p.get("quantity"))
        synced_at = row.get("last_synced_at")
    except _Inactive as e:
        row = e.row
        pos = virtual.get_positions(user_id)
        acct = pos["account"]
        m = {
            "cash_margin": acct["available_margin"], "used_margin": acct["used_margin"],
            "collateral_margin": 0.0, "collateral_liquid_used": 0.0, "collateral_equity_used": 0.0,
            "span": round(sum(g["margin"]["span"] for g in pos["groups"] if g["margin"]), 2),
            "exposure": round(sum(g["margin"]["exposure"] for g in pos["groups"] if g["margin"]), 2),
        }
        source = "approx"
        broker, conn_status = (row["broker"], row["status"]) if row else (None, "disconnected")
        open_positions, synced_at = acct["open_positions"], None
    return {
        "source": source, "broker": broker, "status": conn_status,
        "connectable": connectable_brokers(user_id),
        "available_margin_total": round(m.get("cash_margin", 0.0) + m.get("collateral_margin", 0.0), 2),
        "available_cash": m.get("cash_margin", 0.0),
        "used_margin": m.get("used_margin", 0.0),
        "span": m.get("span", 0.0), "exposure": m.get("exposure", 0.0),
        "total_collateral": m.get("collateral_margin", 0.0),
        "collateral_liquid_used": m.get("collateral_liquid_used", 0.0),
        "collateral_equity_used": m.get("collateral_equity_used", 0.0),
        "open_positions": open_positions,
        "synced_at": synced_at,
    }


def preview_order(user_id: int, symbol: str, expiry: str, legs: list[dict]) -> dict:
    """Prices every leg (all SELL) and checks the total margin required against the broker's own
    real available funds — never against the virtual account. Returns a one-time confirm_token;
    nothing is sent to the broker until broker_place_order redeems it."""
    row = _require_active(user_id)
    if not legs:
        raise ValueError("At least one leg is required")
    lot = data_fetch.fetch_lot_size(symbol, pd.Timestamp(expiry))
    if not lot:
        raise ValueError(f"Lot size for {symbol} {expiry} not found")
    priced, signed = [], []
    spot = None
    for leg in legs:
        if leg.get("action", "SELL") != "SELL":
            raise ValueError("Only sell orders are supported")
        q = virtual.quote(symbol, expiry, leg["side"], float(leg["strike"]))
        spot = q["spot"]
        limit_price = virtual.tick(q["bid"] or q["ltp"])
        if limit_price <= 0:
            raise ValueError(f"No price available for {symbol} {leg['strike']} {leg['side']}")
        lots = int(leg["lots"])
        if lots <= 0:
            raise ValueError("Lots must be a positive integer")
        qty = lot * lots
        priced.append({"side": leg["side"], "strike": float(leg["strike"]), "qty": qty, "limit_price": limit_price})
        signed.append({"side": leg["side"], "strike": float(leg["strike"]), "qty": -qty})
    margin = virtual.group_margin(symbol, expiry, signed, spot)
    m = get_margins(user_id)
    cash = m["available_margin"]
    usable_collateral = _usable_collateral_for(
        margin["total"], m.get("collateral_margin", 0.0),
        m.get("collateral_liquid_used", 0.0) + m.get("collateral_equity_used", 0.0))
    available = cash + usable_collateral
    if margin["total"] > available:
        raise ValueError(f"Insufficient broker margin: needs ~₹{margin['total']:,.0f}, "
                          f"₹{available:,.0f} available (₹{cash:,.0f} cash + ₹{usable_collateral:,.0f} collateral)")
    token = _secrets.token_urlsafe(24)
    payload = {"user_id": user_id, "symbol": symbol, "expiry": expiry, "legs": priced}
    cache.set_json(f"broker_confirm:{token}", payload, ttl=CONFIRM_TTL)
    return {"confirm_token": token, "legs": priced, "margin": margin, "expires_in": CONFIRM_TTL}


def place_order(user_id: int, confirm_token: str) -> dict:
    """The only function that calls the broker. Redeems a one-time preview; places every leg as a
    SELL LIMIT order sequentially. Kite Connect has no atomic multi-leg order: if a leg fails
    after an earlier one already placed, this stops immediately and does not roll anything back —
    an automatic square-off would itself be a new, unconfirmed real-money order."""
    payload = cache.get_json(f"broker_confirm:{confirm_token}")
    cache.delete(f"broker_confirm:{confirm_token}")  # one-time use, whether or not it existed
    if not payload or payload["user_id"] != user_id:
        raise ValueError("This order preview has expired; preview it again before confirming")
    row = _require_active(user_id)
    adapter = registry.adapter(row["broker"])
    session = _row_to_session(row)
    placed, failed = [], None
    for i, leg in enumerate(payload["legs"]):
        result = adapter.place_sell_limit_order(
            session, symbol=payload["symbol"], expiry=payload["expiry"], side=leg["side"],
            strike=leg["strike"], qty=leg["qty"], limit_price=leg["limit_price"])
        with db.tx(user_id) as c:
            new_id = c.value(
                "INSERT INTO broker_orders (user_id, broker, kite_order_id, symbol, expiry, side, "
                "strike, qty, limit_price, leg_index, status, reject_reason) "
                "VALUES (:u, :b, :koid, :sym, :exp, :side, :strike, :qty, :px, :i, :status, :reason) "
                "RETURNING id",
                u=user_id, b=row["broker"], koid=result.broker_order_id or None, sym=payload["symbol"],
                exp=payload["expiry"], side=leg["side"], strike=leg["strike"], qty=leg["qty"],
                px=leg["limit_price"], i=i, status=result.status, reason=result.reject_reason)
        if result.status == "rejected":
            failed = {"leg_index": i, "reason": result.reject_reason}
            auth.audit("broker_order_failed", actor_id=user_id, target_user_id=user_id,
                       broker=row["broker"], leg_index=i, reason=result.reject_reason)
            break
        placed.append({"id": new_id, "leg_index": i, "broker_order_id": result.broker_order_id})
        auth.audit("broker_order_placed", actor_id=user_id, target_user_id=user_id,
                   broker=row["broker"], leg_index=i, broker_order_id=result.broker_order_id)
    if failed:
        raise ValueError(
            f"Leg {failed['leg_index'] + 1} of {len(payload['legs'])} failed to place "
            f"({failed['reason'] or 'rejected by broker'}). "
            + (f"{len(placed)} leg(s) already placed are live in your broker account — "
               f"check Zerodha and manage them manually." if placed else
               "No legs were placed."))
    return {"placed": placed}
