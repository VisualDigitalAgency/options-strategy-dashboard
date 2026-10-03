"""Broker-agnostic interface every adapter implements (engine/brokers/zerodha.py is the first).

A `BrokerSession` is whatever an adapter needs to make authenticated calls; it never leaves this
package as plaintext — `engine/brokers/registry.py`'s caller decrypts a stored access token into
one right before use and lets it go out of scope after.

This app opens positions only by SELLing options (a selling screener); the one BUY it places is
the limit order that closes a short ("Exit group"). `side` here means the option
type (CE/PE), same as the rest of the codebase (see engine/virtual.py).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class BrokerSession:
    access_token: str
    broker_user_id: str | None = None
    public_token: str | None = None


@dataclass
class BrokerOrderResult:
    broker_order_id: str
    status: str  # 'open' (accepted, resting/executing) or 'rejected'
    reject_reason: str | None = None


class BrokerAdapter(ABC):
    name: str
    # Whether create_stop_alert is backed by a broker-held trigger order (Kite ATO alerts, GTT, ...).
    # Without one, day-15 stops are marked "not available" for the user to manage, never retried.
    supports_stop_alerts: bool = False

    @abstractmethod
    def login_url(self) -> str:
        """Where to send the browser so the user logs into their own broker account."""

    @abstractmethod
    def exchange_request_token(self, request_token: str) -> tuple[BrokerSession, datetime]:
        """Trades the redirect's one-time request_token for a session, plus when it expires."""

    @abstractmethod
    def invalidate(self, session: BrokerSession) -> None:
        """Best-effort: ends the session at the broker's end too. Never raises; log and move on."""

    @abstractmethod
    def place_sell_limit_order(self, session: BrokerSession, *, symbol: str, expiry, side: str,
                                strike: float, qty: int, limit_price: float) -> BrokerOrderResult:
        """Places one SELL, LIMIT order for one option leg (NFO segment)."""

    @abstractmethod
    def place_buy_limit_order(self, session: BrokerSession, *, symbol: str, expiry, side: str,
                               strike: float, qty: int, limit_price: float) -> BrokerOrderResult:
        """Places one BUY, LIMIT order for one option leg (NFO segment): the only way this app buys,
        used to close a short ("Exit group")."""

    @abstractmethod
    def contract(self, session: BrokerSession, tradingsymbol: str) -> dict | None:
        """{"symbol", "expiry" (ISO), "side" (CE/PE), "strike", "lot_size"} for one of the broker's
        option instruments (the inverse of `tradingsymbol`), or None if it isn't an option."""

    @abstractmethod
    def get_order_status(self, session: BrokerSession, broker_order_id: str) -> dict:
        """Returns at least {"status": ...}, broker-native status mapped by the caller."""

    @abstractmethod
    def tradingsymbol(self, session: BrokerSession, symbol: str, expiry, side: str, strike: float) -> str:
        """The broker's own instrument name for one option contract (matches get_positions rows)."""

    # Broker-side stop loss (issue #43): an alert held at the broker that places the closing BUY
    # itself when the option's LTP reaches the stop. Installed once, never edited.
    @abstractmethod
    def create_stop_alert(self, session: BrokerSession, *, tradingsymbol: str, qty: int,
                           trigger_price: float, limit_price: float) -> str:
        """Installs the alert; returns its broker id. Raises on failure."""

    @abstractmethod
    def get_alert(self, session: BrokerSession, alert_id: str) -> dict:
        """Returns at least {"status": 'enabled'|'disabled'|'deleted', "alert_count": int}."""

    @abstractmethod
    def delete_alert(self, session: BrokerSession, alert_id: str) -> None:
        ...

    @abstractmethod
    def get_positions(self, session: BrokerSession) -> list[dict]:
        ...

    def option_chain(self, session: BrokerSession, symbol: str, expiry: str):
        """(spot, chain) for one stock and expiry from the user's own market data, in
        data_fetch.normalize_option_chain's columns. Data plan D (#216)."""
        raise NotImplementedError

    @abstractmethod
    def get_margins(self, session: BrokerSession) -> dict:
        """Returns at least {"available_margin": float}."""
