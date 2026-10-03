"""Data plan B (#216): end-of-day mode. Off by default. When on, prices come from the end-of-day file,
nothing fills during the day, a user's order fills at the settlement of the first session that opens
after it was placed, exits always fill at the next settlement, and the daily pass runs once per file."""
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd

import support
from engine import app_settings, builder, data_fetch, db, eod, risk_rules, users, virtual
from engine.progress import IST

fails = []
real_quote, real_open = virtual.quote, virtual.market_open
support.stub(market=True)
virtual.quote, virtual.market_open = real_quote, real_open  # the real path, now reading the end-of-day file
EXP, SYM = support.EXP, support.SYM


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def file_for(day, pe900):
    rows = [{"strike": 900.0, "side": "PE", "settle": pe900, "close": pe900, "prev_close": pe900, "oi": 5000, "oi_chg": 0,
             "volume": 100},
            {"strike": 1100.0, "side": "CE", "settle": 8.0, "close": 8.0, "prev_close": 8.0, "oi": 5000, "oi_chg": 0, "volume": 100}]
    return {"date": day, "symbols": {SYM: {"spot": 1000.0, "lot": 100, "chains": {EXP: rows}}}}


def mode(on):
    app_settings.set_value(owner, "eod_prices", on)
    virtual._eod_flag["at"] = 0.0


eod.DIR = Path(tempfile.mkdtemp()) / "eod"
owner = users.create_user("o@test.example", "O", role="owner", status="active")
uid = support.new_user("e@test.example", 1_000_000)

# 1. The fill day: the first session that opens after the order.
mon8, mon10 = datetime(2026, 10, 5, 8, 0, tzinfo=IST), datetime(2026, 10, 5, 10, 0, tzinfo=IST)
fri16, sat = datetime(2026, 10, 9, 16, 0, tzinfo=IST), datetime(2026, 10, 10, 11, 0, tzinfo=IST)
check("before 09:15: that day's settlement", virtual.eod_fill_day(mon8) == "2026-10-05")
check("during the session: the next day's, never the one running", virtual.eod_fill_day(mon10) == "2026-10-06")
check("Friday evening and Saturday: Monday's", virtual.eod_fill_day(fri16) == virtual.eod_fill_day(sat) == "2026-10-12")

# 2. Off by default: nothing changes.
check("off by default", app_settings.get("eod_prices") is False and virtual.eod_mode() is False)

# 3. On: prices from the file, nothing fills now, the order waits for its settlement.
mode(True)
day = virtual.eod_fill_day(datetime.now(IST))
eod.save(datetime.fromisoformat(day).date(), file_for(day, 10.0))
check("market reads closed outside the daily pass", virtual.market_open() is False)
q = virtual.quote(SYM, EXP, "PE", 900.0)
check("quotes come from the file (bid = ask = settlement)", q["bid"] == q["ask"] == 10.0 and q["spot"] == 1000.0, q)
p = virtual.preview_order(uid, SYM, EXP, [{"side": "PE", "strike": 900, "action": "SELL", "lots": 1}])
check("nothing fills now", not p["fills"][0]["fills_now"])
check("the ticket says when it fills", any("closing settlement" in n for n in p["notes"]), p["notes"])
r = virtual.place_order(uid, SYM, EXP, [{"side": "PE", "strike": 900, "action": "SELL", "lots": 1}])
later = virtual.place_order(uid, SYM, EXP, [{"side": "CE", "strike": 1100, "action": "SELL", "lots": 1}], confirm_waiting=True)
with db.tx(uid) as c:
    c.run("UPDATE pending_orders SET valid_until = CAST(:d AS date) + 7 WHERE id=:i", d=day, i=later["open_ids"][0])
    vu = c.value("SELECT valid_until FROM pending_orders WHERE id=:i", i=r["open_ids"][0])
check("booked as an order for that session", str(vu) == day and not r["filled"], (vu, day))
check("outside the pass the monitor fills nothing", virtual.match_pending(uid) == [])

# 4. The daily pass: fills at the settlement, once per file; a later session's order waits.
check("the pass runs for the user", virtual.run_eod_pass() >= 1)
with db.tx(uid) as c:
    pos = c.all("SELECT side, strike, qty, avg_price FROM positions WHERE user_id=:u AND status='open'", u=uid)
    st = {o["id"]: o["status"] for o in c.all("SELECT id, status FROM pending_orders WHERE user_id=:u", u=uid)}
check("filled at the settlement price", [(p["side"], float(p["strike"]), p["qty"], float(p["avg_price"])) for p in pos]
      == [("PE", 900.0, -100, 10.0)], pos)
check("the later session's order still waits", st[later["open_ids"][0]] == "open", st)
check("one pass per file", virtual.run_eod_pass() == 0)

# 5. Exit outside the pass: fills at the next settlement whatever it is.
pid = virtual.get_positions(uid)["groups"][0]["legs"][0]["id"]
out = virtual.exit_position(uid, pid)
check("exit waits for the next settlement, no made-up price shown", out[0]["status"] == "open" and out[0]["price"] is None, out)
nxt = "2099-01-02"
with db.tx(uid) as c:
    c.run("UPDATE pending_orders SET valid_until=:d WHERE id=:i", d=nxt, i=out[0]["order_id"])
eod.save(datetime.fromisoformat(nxt).date(), file_for(nxt, 14.0))  # the price rose against the short
virtual.run_eod_pass()
with db.tx(uid) as c:
    closed = c.one("SELECT exit_price, realized_pnl FROM positions WHERE id=:i", i=pid)
check("exit filled at the next settlement even though it moved against", float(closed["exit_price"]) == 14.0, closed)

# 6. Data plan C: the screener and builder read the same file, never the live API.
def no_live(*a, **k):
    raise AssertionError("live NSE call in end-of-day mode")
saved = data_fetch.fetch_option_chain, data_fetch.fetch_expiries, data_fetch.fetch_lot_size
data_fetch.fetch_option_chain = data_fetch.fetch_expiries = data_fetch.fetch_lot_size = no_live
check("expiries and lot from the file", builder.expiries(SYM) == [EXP] and virtual.lot_size(SYM, EXP) == 100)
b = builder.chain(SYM, EXP)
check("builder chain is labelled with the file's date", b["as_of"] == nxt and b["lot_size"] == 100, b["as_of"])
days = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=120)
closes = [1000 + 30 * ((i % 20) - 10) / 10 for i in range(len(days))]
hist = pd.DataFrame({"Open": closes, "High": [c + 5 for c in closes], "Low": [c - 5 for c in closes], "Close": closes,
                     "Volume": 1000}, index=days)
today = pd.Timestamp.today().normalize()
row = risk_rules._evaluate_for_expiry(SYM, pd.Timestamp(EXP), (pd.Timestamp(EXP) - today).days, today, hist)
check("screen row priced from the file, stamped as_of", row["as_of"] == nxt and row["spot"] == 1000.0 and row["lot_size"] == 100,
      {k: row.get(k) for k in ("as_of", "spot", "lot_size", "action")})
data_fetch.fetch_option_chain, data_fetch.fetch_expiries, data_fetch.fetch_lot_size = saved

# 7. Off again: back to the live path.
mode(False)
check("off: market hours are live again", virtual.eod_mode() is False and virtual.market_open() == real_open())

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
