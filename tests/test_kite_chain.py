"""Data plan D (#216): the Zerodha adapter builds an option chain from Kite quotes in the same columns
as the NSE and end-of-day chains, with the spot from the stock's own quote."""
import sys
from datetime import date, timedelta

import support  # noqa: F401
from engine.brokers import zerodha

fails = []
EXP = str(date.today() + timedelta(days=30))


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


class FakeKite:
    def __init__(self):
        self.calls = []

    def instruments(self, exchange):
        return [{"name": "SBIN", "expiry": EXP, "instrument_type": t, "strike": k, "tradingsymbol": f"SBIN{k:g}{t}"}
                for k in (800.0, 820.0) for t in ("CE", "PE")] + [
                {"name": "SBIN", "expiry": "2099-02-26", "instrument_type": "CE", "strike": 800.0, "tradingsymbol": "OTHER"}]

    def quote(self, keys):
        self.calls.append(keys)
        out = {"NSE:SBIN": {"last_price": 810.0}}
        for k in keys:
            if k.startswith("NFO:"):
                out[k] = {"last_price": 30.0, "oi": 500, "ohlc": {"close": 25.0},
                          "depth": {"buy": [{"price": 29.9}], "sell": [{"price": 30.1}]}}
        return out


kite = FakeKite()
a = zerodha.ZerodhaAdapter.__new__(zerodha.ZerodhaAdapter)
a._instruments_cache = None
a._client = lambda session=None: kite
spot, df = a.option_chain(None, "SBIN", EXP)
check("spot from the stock's quote", spot == 810.0, spot)
check("only that expiry's strikes", list(df["strikePrice"]) == [800.0, 820.0], list(df["strikePrice"]))
r = df.iloc[0]
check("bid / ask / ltp / oi from depth and quote", (r["PE_BID"], r["PE_ASK"], r["PE_LTP"], r["PE_OI"]) == (29.9, 30.1, 30.0, 500))
check("change vs yesterday's close", r["CE_PCHG"] == 20.0, r["CE_PCHG"])
check("IV worked out", r["CE_IV"] > 0, r["CE_IV"])
check("one quote call", len(kite.calls) == 1)
check("unknown expiry: None", a.option_chain(None, "SBIN", "2099-03-26") is None)

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
