"""Multi-expiry screening: which cycles are picked, one bad cycle doesn't blank the others, the
screen stores and serves one row per cycle, and a screen saved in the old one-row-per-stock
format still reads."""
import sys

import pandas as pd

from engine import batch, cache, config, data_fetch, filters, risk_rules, span

fails = []


def check(name, cond, got):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


today = pd.Timestamp("2026-09-29")
exps = [today + pd.Timedelta(days=d) for d in (100, 8, 29, 57, 92, 85)]

# ---- eligible_expiries: [floor, ceil], nearest first, capped
got = filters.eligible_expiries(exps, today, 20, 90, 4)
check("cycles in [20, 90], sorted", [(e - today).days for e in got] == [29, 57, 85], got)
got = filters.eligible_expiries(exps, today, 20, 90, 2)
check("capped at limit", [(e - today).days for e in got] == [29, 57], got)
check("nearest_valid_expiry keeps MIN_DTE", (filters.nearest_valid_expiry(exps, today) - today).days == 57,
      filters.nearest_valid_expiry(exps, today))

# ---- evaluate_symbol_cycles: one row per cycle, a failing cycle becomes its own ERROR row
data_fetch.fetch_expiries = lambda s: exps
hist = pd.DataFrame({"Close": [100.0, 101.0]})


def fake_eval(symbol, expiry, dte, today, price_hist):
    if dte == 57:
        raise RuntimeError("chain fetch failed")
    assert price_hist is hist
    return {"symbol": symbol, "action": "SKIP", "legs": [], "checks": [],
            "expiry": expiry.strftime("%Y-%m-%d"), "dte": dte}


risk_rules._evaluate_for_expiry = fake_eval
rows = risk_rules.evaluate_symbol_cycles("SBIN", "SBIN.NS", today=today, price_hist=hist)
check("three cycles back", [r["dte"] for r in rows] == [29, 57, 85], [r.get("dte") for r in rows])
check("failed cycle is its own ERROR row", rows[1]["action"] == "ERROR" and rows[1]["expiry"] == "2026-11-25", rows[1])
check("other cycles survive", rows[0]["action"] == rows[2]["action"] == "SKIP", rows)

data_fetch.fetch_expiries = lambda s: [today + pd.Timedelta(days=5)]
rows = risk_rules.evaluate_symbol_cycles("SBIN", "SBIN.NS", today=today, price_hist=hist)
check("no cycle in range -> one SKIP row", len(rows) == 1 and rows[0]["checks"][0]["rule"] == "Expiry", rows)

# ---- pick_cycle: exact expiry, else the nearest cycle at or past MIN_DTE
cyc = [{"expiry": "2026-10-28", "dte": config.MIN_DTE - 1}, {"expiry": "2026-11-25", "dte": config.MIN_DTE + 27}]
check("pick exact expiry", risk_rules.pick_cycle(cyc, "2026-10-28") is cyc[0], risk_rules.pick_cycle(cyc, "2026-10-28"))
check("no expiry -> MIN_DTE default", risk_rules.pick_cycle(cyc) is cyc[1], risk_rules.pick_cycle(cyc))
check("rolled-off expiry -> MIN_DTE default", risk_rules.pick_cycle(cyc, "2026-09-30") is cyc[1], None)
check("nothing past MIN_DTE -> nearest", risk_rules.pick_cycle(cyc[:1]) is cyc[0], None)

# ---- ScreenJob / ScreenReader: lists per stock, flattened snapshot, expiry-aware get
batch.ScreenJob._load_cache = lambda self: None
job = batch.ScreenJob()
job.order = ["SBIN", "INFY"]
job.results = {"SBIN": cyc, "INFY": [{"symbol": "INFY", "expiry": "2026-11-25", "dte": 57}]}
job._publish(rows=True)
reader = batch.ScreenReader()
check("snapshot flattens every cycle", [r.get("symbol", "SBIN") for r in reader.snapshot()] == ["SBIN", "SBIN", "INFY"],
      reader.snapshot())
check("reader get by expiry", reader.get("SBIN", "2026-10-28")["dte"] == config.MIN_DTE - 1, reader.get("SBIN", "2026-10-28"))
check("job get default", job.get("SBIN")["expiry"] == "2026-11-25", job.get("SBIN"))

# A worker still on the old code (or an old Redis blob) publishes one dict per stock.
cache.set_json(batch.LATEST, {"version": "old", "order": ["SBIN"], "results": {"SBIN": {"symbol": "SBIN", "dte": 40}}})
cache.set_json(batch.META, {**batch._empty_state(), "version": "old"})
reader = batch.ScreenReader()
check("old one-dict format still reads", reader.snapshot() == [{"symbol": "SBIN", "dte": 40}]
      and reader.get("SBIN")["dte"] == 40, reader.snapshot())

# ---- a full ScreenJob run: month by month, fresh skips reused, Refresh refetches everything
config.SCREEN_BATCH_PAUSE_SECONDS = 0
config.SCREEN_BATCH_SIZE = 2
risk_rules.get_universe = lambda: ["AAA", "BBB", "CCC"]
span.load = lambda symbols: {"source": "stub"}
data_fetch.fetch_price_history_batch = lambda syms, n: {s: hist for s in syms}
now = pd.Timestamp.today().normalize()
oct_, nov, dec = (now + pd.Timedelta(days=d) for d in (25, 53, 88))
data_fetch.fetch_expiries = lambda s: [oct_, nov] if s == "CCC" else [oct_, nov, dec]
calls = []
failing = set()


def fake_eval2(symbol, expiry, dte, today, price_hist):
    calls.append((symbol, dte))
    if (symbol, dte) in failing:
        raise RuntimeError("nse down")
    trade = symbol == "AAA"  # AAA is actionable in every cycle, the others skip
    return {"symbol": symbol, "action": "SELL PE ONLY" if trade else "SKIP", "legs": [{"side": "PE"}] if trade else [],
            "checks": [], "expiry": expiry.strftime("%Y-%m-%d"), "dte": dte}


risk_rules._evaluate_for_expiry = fake_eval2
job = batch.ScreenJob()
job._run()
check("month by month: all Oct, then all Nov, then Dec", [d for _, d in calls] == [25, 25, 25, 53, 53, 53, 88, 88], calls)
check("rows per stock", [len(job.results[s]) for s in ("AAA", "BBB", "CCC")] == [3, 3, 2], job.results)
check("rows stamped", all("screened_at" in r for rows in job.results.values() for r in rows), None)

calls.clear()
failing.add(("AAA", 53))
job._run()
check("second run refetches only actionable cycles", sorted(set(calls)) == [("AAA", 25), ("AAA", 53), ("AAA", 88)], calls)
nov_key = nov.strftime("%Y-%m-%d")
check("failed refetch keeps the last good row", job.get("AAA", nov_key)["action"] == "SELL PE ONLY", job.get("AAA", nov_key))

calls.clear()
failing.clear()
for r in job.results["BBB"]:
    r["screened_at"] -= config.SCREEN_SKIP_REFRESH_SECONDS + 1
job._run()
check("stale skips are refetched", {c for c in calls if c[0] == "BBB"} == {("BBB", 25), ("BBB", 53), ("BBB", 88)}, calls)

calls.clear()
job._run(full=True)
check("full run refetches everything", len(calls) == 8, calls)

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
