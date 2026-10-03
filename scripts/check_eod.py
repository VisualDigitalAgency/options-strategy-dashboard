"""Check NSE's end-of-day F&O file before anything prices from it (data plan, PR A).

Run where the app runs (it needs NSE's archive site):
    python scripts/check_eod.py            # the latest trading day, walking back up to 6 days
    python scripts/check_eod.py 2026-10-01 # one day
    python scripts/check_eod.py --save     # also save it where the worker would

Prints how many stocks the file has, then SBIN's nearest expiry next to the money: settlement
price, IV worked out from it, open interest. Compare a few rows with NSE's website or your broker.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import eod  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
day = date.fromisoformat(args[0]) if args else date.today()
blob = None
for _ in range(1 if args else 6):
    blob = eod.download(day)
    if blob:
        break
    day -= timedelta(days=1)
if not blob:
    sys.exit(f"No bhavcopy found for {day} (or the days before it)")
data = eod.parse(blob)
print(f"{day}: {len(data['symbols'])} stocks with options; file date {data['date']}")
sym = "SBIN" if "SBIN" in data["symbols"] else next(iter(data["symbols"]))
s = data["symbols"][sym]
expiry = sorted(s["chains"])[0]
spot, df = eod.chain(sym, expiry, data)
print(f"{sym} spot {spot}, lot {s['lot']}, expiry {expiry}, {len(df)} strikes")
near = df.iloc[(df["strikePrice"] - spot).abs().argsort()[:6]].sort_values("strikePrice")
print(near[["strikePrice", "CE_LTP", "CE_IV", "CE_OI", "PE_LTP", "PE_IV", "PE_OI"]].to_string(index=False))
if "--save" in sys.argv:
    print("saved", eod.save(day, data))
