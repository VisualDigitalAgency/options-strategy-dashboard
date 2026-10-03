"""Shared stubs for the integration tests. Market data (NSE quotes, lot sizes, SPAN) is replaced
with fixed values; Postgres and Redis are real. tests/run.py gives every test file a fresh database."""
from datetime import date, timedelta

from engine import data_fetch, db, users, virtual

SYM = "SBIN"


def _expiry() -> str:
    """Last Tuesday of the month after next: always ahead of today, so the tests don't age."""
    d = (date.today().replace(day=1) + timedelta(days=62)).replace(day=1) + timedelta(days=31)
    d = d.replace(day=1) - timedelta(days=1)
    while d.weekday() != 1:
        d -= timedelta(days=1)
    return d.isoformat()


EXP = _expiry()


def stub(market: bool, bid: float = 5.0, oi: int = 10_000):
    """Every contract quotes `bid` / bid+0.1 with spot 1,000; lot size 100; margin 1,000 per short unit
    (so one 100-qty lot needs 1 lakh). `oi` defaults well above the liquidity gate (#80)."""
    virtual.quote = lambda s, e, side, k: {"spot": 1000.0, "ltp": 5.0, "bid": bid, "ask": bid + 0.1 if bid else 0.0,
                                            "iv": 20.0, "oi": oi}
    virtual.market_open = lambda: market
    # Order-mechanics tests sell naked from Level 1 accounts; the strategy gate (#170) has its own
    # test (test_strategy_gate.py), which doesn't use this stub.
    virtual._strategy_rule = lambda *a: None
    virtual.lessons_lock = lambda user_id: None  # the Level 1 lessons gate; tests that need it restore it
    data_fetch.fetch_lot_size = lambda s, e: 100

    def gm(symbol, expiry, legs, spot):
        t = sum(-l["qty"] * 1000.0 for l in legs if l["qty"] < 0)
        return {"span": t, "exposure": 0.0, "total": t}
    virtual.group_margin = gm


def new_user(email: str, capital: float):
    uid = users.create_user(email, "Test", status="active")
    with db.tx(uid) as c:
        c.run("UPDATE accounts SET starting_capital=:c WHERE user_id=:u", c=capital, u=uid)
    return uid
