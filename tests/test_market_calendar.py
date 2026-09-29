"""Market calendar: NSE holiday/event parsing, a blocked source keeps yesterday's copy, per-expiry event
filtering on screen rows, the RPC, and holidays skipped by the screen schedule."""
import sys
from datetime import datetime

from engine import batch, cache, data_fetch, market_calendar, risk_rules, virtual
from engine.worker import next_screen_at

fails = []


def check(name, cond, got):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


risk_rules.get_universe = lambda: ["SBIN", "INFY"]
HOLIDAYS = {"CM": [{"tradingDate": "02-Oct-2026", "weekDay": "Friday", "description": "Gandhi Jayanti"}],
            "FO": [{"tradingDate": "02-Oct-2026", "weekDay": "Friday", "description": "Gandhi Jayanti"},
                   {"tradingDate": "bad", "weekDay": "", "description": "x"}]}
BOARD = [{"symbol": "SBIN", "purpose": "Financial Results", "bm_desc": "Q2 results", "date": "14-Oct-2026"},
         {"symbol": "INFY", "purpose": "Fund raising", "date": "20-Nov-2026"},
         {"symbol": "TCS", "purpose": "Financial Results", "date": "09-Oct-2026"}]  # not in the universe
ACTIONS = [{"symbol": "INFY", "subject": "Interim Dividend - Rs 21 Per Share", "exDate": "24-Oct-2026"},
           {"symbol": "SBIN", "subject": "Face Value Split (Sub-Division) - From Rs 10/- To Rs 1/-", "exDate": "03-Dec-2026"},
           {"symbol": "SBIN", "subject": "Something else", "exDate": "05-Dec-2026"}]
data_fetch.fetch_holidays = lambda: HOLIDAYS
data_fetch.fetch_event_calendar = lambda: BOARD
data_fetch.fetch_corporate_actions = lambda a, b: ACTIONS

# ---- parsing
h = market_calendar.parse_holidays(HOLIDAYS)
check("FO holidays, bad dates dropped", h == [{"date": "2026-10-02", "day": "Friday", "description": "Gandhi Jayanti"}], h)
check("CM fallback", len(market_calendar.parse_holidays({"CM": HOLIDAYS["CM"]})) == 1, None)
check("garbage in -> empty", market_calendar.parse_holidays(None) == [] and market_calendar.parse_board_meetings(None, {"SBIN"}) == [], None)

data = market_calendar.refresh()
types = {(e["symbol"], e["type"]) for e in data["events"]}
check("results, dividend, split kept; other stocks and unknown subjects dropped",
      types == {("SBIN", "results"), ("INFY", "board_meeting"), ("INFY", "dividend"), ("SBIN", "split")}, types)
check("sorted by date", [e["date"] for e in data["events"]] == sorted(e["date"] for e in data["events"]), None)
check("stored in Redis", market_calendar.load()["events"] == data["events"] and not data["errors"], data["errors"])
check("not due right after a refresh", not market_calendar.due(), None)

# ---- a blocked source keeps yesterday's copy of that source only
data_fetch.fetch_event_calendar = lambda: (_ for _ in ()).throw(RuntimeError("403"))
data = market_calendar.refresh()
types = {(e["symbol"], e["type"]) for e in data["events"]}
check("failed source listed", data["errors"] == ["board meetings"], data["errors"])
check("failed source keeps last copy", ("SBIN", "results") in types and ("INFY", "dividend") in types, types)
data_fetch.fetch_event_calendar = lambda: BOARD

# ---- per-expiry filter
ev = market_calendar.load()["events"]
oct_ = market_calendar.events_until(ev, "SBIN", "2026-09-29", "2026-10-27")
check("Oct cycle sees only the Oct results", [(e["type"], e["days_away"], e["risky"]) for e in oct_] == [("results", 15, True)], oct_)
dec = market_calendar.events_until(ev, "SBIN", "2026-09-29", "2026-12-29")
check("Dec cycle also sees the split", [e["type"] for e in dec] == ["results", "split"], dec)
check("past events dropped", market_calendar.events_until(ev, "SBIN", "2026-10-15", "2026-10-27") == [], None)

# ---- screen rows and the RPC carry events
import server  # noqa: E402

batch.ScreenJob._load_cache = lambda self: None
job = batch.ScreenJob()
job.order = ["SBIN"]
job.results = {"SBIN": [{"symbol": "SBIN", "expiry": "2026-10-27", "dte": 28}, {"symbol": "SBIN", "expiry": "2026-12-29", "dte": 91}]}
job._publish(rows=True)
server.screen = batch.ScreenReader()
server._ist_today = lambda: "2026-09-29"
rows = server.get_screened_candidates()["candidates"]
check("screener rows: events per expiry", [len(r["events"]) for r in rows] == [1, 2], [r.get("events") for r in rows])
detail = server.get_trade_detail("SBIN", "2026-10-27")
check("detail carries events", [e["type"] for e in detail["events"]] == ["results"], detail.get("events"))
check("screen cache not mutated", "events" not in job.results["SBIN"][0], None)
cal = server.get_market_calendar()
check("calendar RPC", cal["holidays"][0]["date"] == "2026-10-02" and len(cal["events"]) == 4 and cal["today"] == "2026-09-29", cal)
check("calendar RPC lists the screened expiries", cal["expiries"] == ["2026-10-27", "2026-12-29"], cal["expiries"])

# ---- holidays skipped by the screen schedule (2026-10-02 is a Friday holiday)
IST = virtual.IST
ts = lambda *a: datetime(*a, tzinfo=IST).timestamp()
got = next_screen_at(ts(2026, 10, 1, 15, 50), ts(2026, 10, 2, 11, 0))
check("holiday: no market-hours screens, next is Monday", got == ts(2026, 10, 5, 9, 0), datetime.fromtimestamp(got, IST))
got = next_screen_at(ts(2026, 10, 1, 15, 50), ts(2026, 10, 2, 11, 0), holidays=set())
check("without the holiday list: Friday runs as normal", got < ts(2026, 10, 2, 11, 0), datetime.fromtimestamp(got, IST))

cache.delete(market_calendar.KEY)
check("no calendar yet -> empty, due", market_calendar.load()["events"] == [] and market_calendar.due(), None)

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
