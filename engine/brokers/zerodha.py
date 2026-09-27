"""Zerodha (Kite Connect) adapter — the first (and, for phase 1, only) connectable broker.

One Kite Connect app is registered by the Theta Desk operator (KITE_API_KEY/KITE_API_SECRET,
read like the DB/Redis passwords via engine.settings.secret()). Each user logs into THEIR OWN
Zerodha account through that one app's OAuth-style redirect, so only the per-user access token
needs to be stored (encrypted) — the api key/secret are operator-level, not per-user.

Kite access tokens expire once a day; there is no refresh token for this app type, so a user
must redo the browser login every trading day (engine/brokers/poller.py flips the connection to
'expired' rather than trying to silently refresh it).
"""

import logging
from datetime import datetime, timedelta, timezone

from kiteconnect import KiteConnect
from kiteconnect.exceptions import KiteException

from .. import settings
from .base import BrokerAdapter, BrokerOrderResult, BrokerSession

log = logging.getLogger("theta.brokers.zerodha")
IST = timezone(timedelta(hours=5, minutes=30))

# Kite access tokens are invalidated by the exchange each night; treat one as good until the
# next 6 AM IST regardless of when it was issued (a well-documented convention in the Kite
# Connect community — there is no "expires_in" field in generate_session's response).
_EXPIRY_HOUR_IST = 6


def _next_expiry(now: datetime | None = None) -> datetime:
    now = (now or datetime.now(IST)).astimezone(IST)
    cutoff = now.replace(hour=_EXPIRY_HOUR_IST, minute=0, second=0, microsecond=0)
    if now >= cutoff:
        cutoff += timedelta(days=1)
    return cutoff


def _credentials() -> tuple[str, str]:
    api_key = settings.secret("KITE_API_KEY")
    api_secret = settings.secret("KITE_API_SECRET")
    if not api_key or not api_secret:
        # Only admins can reach any code path that calls this (broker_connect_url/
        # broker_exchange_token are ADMIN_METHODS), so a ValueError surfacing the exact missing
        # var is safe and actionable — not an internal detail to hide behind a ref id.
        raise ValueError("Zerodha isn't configured on this server yet (KITE_API_KEY / "
                          "KITE_API_SECRET_FILE are not set) — set them and redeploy before connecting.")
    return api_key, api_secret


class ZerodhaAdapter(BrokerAdapter):
    name = "zerodha"

    def __init__(self):
        self._instruments_cache: tuple[float, list[dict]] | None = None

    def _client(self, session: BrokerSession | None = None) -> KiteConnect:
        api_key, _ = _credentials()
        kite = KiteConnect(api_key=api_key)
        if session:
            kite.set_access_token(session.access_token)
        return kite

    def login_url(self) -> str:
        return self._client().login_url()

    def exchange_request_token(self, request_token: str) -> tuple[BrokerSession, datetime]:
        api_key, api_secret = _credentials()
        kite = KiteConnect(api_key=api_key)
        try:
            data = kite.generate_session(request_token, api_secret=api_secret)
        except KiteException as e:
            raise ValueError(f"Zerodha login failed: {e}") from e
        session = BrokerSession(access_token=data["access_token"], broker_user_id=data.get("user_id"),
                                 public_token=data.get("public_token"))
        return session, _next_expiry()

    def invalidate(self, session: BrokerSession) -> None:
        try:
            self._client(session).invalidate_access_token()
        except Exception:
            # Best-effort only: the local broker_connections row is what actually gates this app's
            # own use of the token; failing to reach Zerodha here must not block disconnecting.
            log.warning("invalidate_access_token failed", exc_info=True)

    def _instruments(self, kite: KiteConnect) -> list[dict]:
        """Kite requires the exact tradingsymbol, not a strike/expiry tuple, to place an NFO order.
        Resolve it from the day's instrument dump rather than guessing the string format."""
        import time
        now = time.time()
        if self._instruments_cache and now - self._instruments_cache[0] < 3600:
            return self._instruments_cache[1]
        rows = kite.instruments("NFO")
        self._instruments_cache = (now, rows)
        return rows

    def _tradingsymbol(self, kite: KiteConnect, symbol: str, expiry, side: str, strike: float) -> str:
        want_expiry = expiry.isoformat() if hasattr(expiry, "isoformat") else str(expiry)
        for row in self._instruments(kite):
            if (row.get("name") == symbol and str(row.get("expiry")) == want_expiry
                    and row.get("instrument_type") == side and float(row.get("strike", -1)) == float(strike)):
                return row["tradingsymbol"]
        raise ValueError(f"No NFO contract found for {symbol} {expiry} {side} {strike} — check the "
                          f"expiry/strike are still listed at Zerodha")

    def place_sell_limit_order(self, session: BrokerSession, *, symbol: str, expiry, side: str,
                                strike: float, qty: int, limit_price: float) -> BrokerOrderResult:
        kite = self._client(session)
        try:
            tradingsymbol = self._tradingsymbol(kite, symbol, expiry, side, strike)
            order_id = kite.place_order(
                variety=kite.VARIETY_REGULAR, exchange=kite.EXCHANGE_NFO, tradingsymbol=tradingsymbol,
                transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=qty, order_type=kite.ORDER_TYPE_LIMIT,
                price=round(limit_price, 2), product=kite.PRODUCT_NRML, validity=kite.VALIDITY_DAY)
        except KiteException as e:
            return BrokerOrderResult(broker_order_id="", status="rejected", reject_reason=str(e))
        except ValueError as e:  # contract not found
            return BrokerOrderResult(broker_order_id="", status="rejected", reject_reason=str(e))
        return BrokerOrderResult(broker_order_id=str(order_id), status="open")

    def get_order_status(self, session: BrokerSession, broker_order_id: str) -> dict:
        kite = self._client(session)
        history = kite.order_history(broker_order_id)
        return history[-1] if history else {"status": "unknown"}

    def get_positions(self, session: BrokerSession) -> list[dict]:
        return self._client(session).positions().get("net", [])

    def get_margins(self, session: BrokerSession) -> dict:
        margins = self._client(session).margins("equity")
        available = margins.get("available", {})
        utilised = margins.get("utilised", {})
        cash = float(available.get("live_balance") or 0.0)
        collateral = float(available.get("collateral") or 0.0)
        used = float(utilised.get("debits") or 0.0)
        span = float(utilised.get("span") or 0.0)
        exposure = float(utilised.get("exposure") or 0.0)
        # cash + collateral is NOT real usable margin: SEBI caps how much of a margin
        # requirement can be met from non-cash collateral (currently 50%), so collateral isn't
        # simply additive to cash the way an earlier version of this function assumed — that
        # overstated available margin and would have let a real order through that the account
        # couldn't actually fund. available_margin (used to gate real orders) stays cash-only,
        # the conservative, always-safe number; collateral_margin/span/exposure are informational.
        return {"available_margin": cash, "cash_margin": cash,
                "collateral_margin": collateral, "used_margin": used,
                "span": span, "exposure": exposure, "raw": margins}
