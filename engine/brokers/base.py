"""Broker-agnostic interface every adapter implements (engine/brokers/zerodha.py is the first).

A `BrokerSession` is whatever an adapter needs to make authenticated calls; it never leaves this
package as plaintext — `engine/brokers/registry.py`'s caller decrypts a stored access token into
one right before use and lets it go out of scope after.

This app only ever SELLs options (a selling screener), so `place_order` has no BUY/side param
for the transaction type: every order this app places is a sell. `side` here means the option
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
    def get_order_status(self, session: BrokerSession, broker_order_id: str) -> dict:
        """Returns at least {"status": ...}, broker-native status mapped by the caller."""

    @abstractmethod
    def get_positions(self, session: BrokerSession) -> list[dict]:
        ...

    @abstractmethod
    def get_margins(self, session: BrokerSession) -> dict:
        """Returns at least {"available_margin": float}."""
