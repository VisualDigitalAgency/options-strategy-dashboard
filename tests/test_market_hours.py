"""Market hours (issue #181): NSE trading holidays close the market like a weekend, on the server
(orders, stop-loss monitor, RMS, auto-trade) and in app_info for the browser's market clock."""
import sys
import time
from datetime import datetime

import server
from engine import pricing, virtual
from engine.pricing import IST

ORIGIN = "https://t.example"
server.ALLOWED_ORIGINS = {ORIGIN}
fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def at(y, mo, d, h=11, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=IST)


pricing._holidays.update(at=time.time(), dates=frozenset({"2026-10-02"}))
check("a weekday is a trading day", pricing.trading_day(at(2026, 10, 1)))
check("an NSE holiday is not", not pricing.trading_day(at(2026, 10, 2)))
check("a weekend is not", not pricing.trading_day(at(2026, 10, 3)))

real = pricing.datetime


class Clock(real):
    fixed = at(2026, 10, 2)

    @classmethod
    def now(cls, tz=None):
        return cls.fixed


pricing.datetime = Clock
virtual.datetime = Clock
check("holiday 11:00: market closed", not virtual.market_open() and not pricing.market_open())
check("holiday: outside the refresh window", not virtual.market_window())
check("holiday: the session counts as over", virtual._session_over())
Clock.fixed = at(2026, 10, 1)
check("trading day 11:00: market open", virtual.market_open() and pricing.market_open())
Clock.fixed = at(2026, 10, 1, 16, 0)
check("trading day 16:00: closed", not virtual.market_open())
pricing.datetime = real
virtual.datetime = real

pricing._holidays.update(at=time.time(), dates=frozenset())
check("no holiday list: weekdays stay open (never closed by mistake)", pricing.trading_day(at(2026, 10, 2)))

pricing._holidays.update(at=time.time(), dates=frozenset({"2026-10-02", "2026-11-09"}))
c = server.app.test_client()
info = c.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "app_info", "params": {}},
              headers={"Origin": ORIGIN}).get_json()["result"]
check("app_info sends the holidays for the market clock", info["holidays"] == ["2026-10-02", "2026-11-09"], info.get("holidays"))

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
