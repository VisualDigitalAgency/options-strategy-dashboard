"""Read-only worker loop reconciling real broker state into a per-user Redis cache.

Runs only inside the worker's single-leader lock (see engine/worker.py), so at most one process
ever polls a given user's broker account. This loop must NEVER place, modify or cancel an order —
the only order-placing path is the RPC-triggered engine.broker.place_order, so a stalled or
duplicated poller can't ever fire a trade twice.
"""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from .. import broker_crypto, cache, db, users
from .base import BrokerSession
from .registry import adapter

log = logging.getLogger("theta.brokers.poller")
POLL_INTERVAL = 45
SNAP_TTL = 120
IST = timezone(timedelta(hours=5, minutes=30))  # db.Tx returns timestamps as "YYYY-MM-DD HH:MM:SS" in IST, not datetimes


def _parse_ist(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)


def _active_rows() -> list[dict]:
    # broker_connections is RLS-protected on user_id, so db.tx() with no user_id (no
    # app.user_id set) sees zero rows for every user, not "all rows" — there is no
    # cross-user read here. Loop per user like virtual.py's SL monitor does.
    rows = []
    for uid in users.active_user_ids():
        with db.tx(uid) as c:
            row = c.one("SELECT * FROM broker_connections WHERE user_id=:u AND status='active'", u=uid)
        if row:
            rows.append(row)
    return rows


def _session(row: dict) -> BrokerSession:
    return BrokerSession(access_token=broker_crypto.decrypt(row["access_token_enc"]),
                          broker_user_id=row["broker_user_id"],
                          public_token=broker_crypto.decrypt(row["public_token_enc"]) if row["public_token_enc"] else None)


def _poll_once() -> None:
    now = datetime.now(timezone.utc)
    for row in _active_rows():
        expires_at = row["token_expires_at"]
        if expires_at and now >= _parse_ist(expires_at):
            with db.tx(row["user_id"]) as c:
                c.run("UPDATE broker_connections SET status='expired' WHERE id=:id", id=row["id"])
            continue
        try:
            a = adapter(row["broker"])
            session = _session(row)
            positions = a.get_positions(session)
            margins = a.get_margins(session)
            cache.set_json(f"broker_snap:{row['user_id']}", {"positions": positions, "margins": margins}, ttl=SNAP_TTL)
            with db.tx(row["user_id"]) as c:
                c.run("UPDATE broker_connections SET last_synced_at=now() WHERE id=:id", id=row["id"])
        except Exception:
            # One user's broker hiccup (e.g. a slow Kite response) must not stop the others, and
            # must not crash the worker's single leader.
            log.warning("broker poll failed for user %s", row["user_id"], exc_info=True)


def start_poller() -> None:
    def loop():
        while True:
            try:
                _poll_once()
            except Exception:
                log.exception("broker poller pass failed")
            time.sleep(POLL_INTERVAL)

    threading.Thread(target=loop, daemon=True, name="broker-poller").start()
