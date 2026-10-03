"""End-of-day bhavcopy ingest (data plan, PR A): parse NSE's UDiFF F&O file, keep stock options, build
a chain in the live chain's columns with IV worked out from the settlement price, save and prune per
day, and fetch only after EOD_READY_IST on a trading day."""
import io
import sys
import tempfile
import zipfile
from datetime import date, datetime
from pathlib import Path

from engine import config, data_fetch, eod, greeks_sr
from engine.progress import IST

fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


HEAD = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,"
        "FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,"
        "TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4")
SPOT, EXP = 800.0, "2026-10-27"
ce = round(greeks_sr.bs_price(SPOT, 850, 26, 22.0, "CE"), 2)  # priced at 22% IV, 26 days before expiry
pe = round(greeks_sr.bs_price(SPOT, 750, 26, 25.0, "PE"), 2)


def row(tp, sym, strike, side, settle, oi=1000):
    return (f"2026-10-01,2026-10-01,FO,NSE,{tp},1,,{sym},,{EXP},{EXP},{strike},{side},X,1,1,1,{settle},{settle},{settle * 0.9:.2f},"
            f"{SPOT},{settle},{oi},50,10,1,1,F1,750,,,,,")


rows = [row("STO", "SBIN", 850, "CE", ce), row("STO", "SBIN", 750, "PE", pe), row("STO", "SBIN", 850, "PE", 51.0),
        row("STF", "SBIN", "", "", 801.0), row("IDO", "NIFTY", 25000, "CE", 120.0)]
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("BhavCopy_NSE_FO_0_0_0_20261001_F_0000.csv", "\n".join([HEAD, *rows]))
blob = buf.getvalue()

# 1. Parse: stock options only, spot and lot from the file.
data = eod.parse(blob)
check("stock options only (futures and index options dropped)", list(data["symbols"]) == ["SBIN"], list(data["symbols"]))
s = data["symbols"]["SBIN"]
check("spot, lot and date from the file", s["spot"] == SPOT and s["lot"] == 750 and data["date"] == "2026-10-01", (s["spot"], s["lot"], data["date"]))
check("three contracts kept", len(s["chains"][EXP]) == 3)

# 2. Chain: the live chain's columns; IV recovered from the settlement price.
spot, df = eod.chain("SBIN", EXP, data)
live_cols = set(data_fetch.normalize_option_chain({"records": {"data": [{"strikePrice": 1, "CE": {}, "PE": {}}]}}).columns)
check("same columns as the live chain", set(df.columns) == live_cols, sorted(set(df.columns) ^ live_cols))
r850 = df.set_index("strikePrice").loc[850]
check("bid = ask = settlement (no order book in the file)", r850["CE_BID"] == r850["CE_ASK"] == r850["CE_LTP"] == ce)
check("IV worked out from the settlement price", abs(r850["CE_IV"] - 22.0) < 0.2, r850["CE_IV"])
check("a strike with one side fills the other with zeros", df.set_index("strikePrice").loc[750]["CE_LTP"] == 0.0)
check("unknown stock or expiry: None", eod.chain("INFY", EXP, data) is None and eod.chain("SBIN", "2027-01-28", data) is None)
check("IV below intrinsic is 0, not an error", greeks_sr.implied_vol(1.0, 800, 700, 20, "CE") == 0.0)

# 3. Save, prune, latest.
eod.DIR = Path(tempfile.mkdtemp()) / "eod"
for d in range(1, 8):
    eod.save(date(2026, 9, d), data)
kept = sorted(p.name for p in eod.DIR.glob("*.json"))
check(f"keeps the newest {eod.KEEP_DAYS} days", len(kept) == eod.KEEP_DAYS and kept[-1] == "2026-09-07.json", kept)
check("latest() reads the newest", eod.latest()["symbols"]["SBIN"]["spot"] == SPOT)

# 4. When to fetch: after EOD_READY_IST on a trading day, once.
thu = datetime(2026, 10, 1, 19, 0, tzinfo=IST)
check("before the ready time: nothing", eod.due(thu.replace(hour=17)) is None)
check("after it on a trading day: today", eod.due(thu) == date(2026, 10, 1))
check("weekend: nothing", eod.due(datetime(2026, 10, 3, 20, 0, tzinfo=IST)) is None)
eod.download = lambda d: None
check("not published yet: retried later", eod.refresh(thu) is None)
eod.download = lambda d: blob
check("published: saved", eod.refresh(thu) == "2026-10-01" and eod.path_for(date(2026, 10, 1)).exists())
check("already saved: not fetched again", eod.due(thu) is None)
check("ready time from config", config.EOD_READY_IST == "18:30")

try:
    eod.parse(zipfile_bytes := (lambda b: (zipfile.ZipFile(b, "w").writestr("x.csv", HEAD), b.getvalue())[1])(io.BytesIO()))
    check("a file with no stock options is an error", False)
except ValueError:
    check("a file with no stock options is an error", True)

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
