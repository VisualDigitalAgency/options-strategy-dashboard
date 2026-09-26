"""Broker name -> adapter instance. Phase 1 only registers Zerodha; a second broker later adds
one line here plus its own engine/brokers/<name>.py, with no changes needed to the RPC or DB layers."""

from .base import BrokerAdapter
from .zerodha import ZerodhaAdapter

_ADAPTERS: dict[str, BrokerAdapter] = {"zerodha": ZerodhaAdapter()}

CONNECTABLE = {"zerodha"}  # brokers users may actually connect to right now (others stay "coming soon")


def adapter(broker: str) -> BrokerAdapter:
    try:
        return _ADAPTERS[broker]
    except KeyError:
        raise ValueError(f"Unknown broker: {broker}") from None
