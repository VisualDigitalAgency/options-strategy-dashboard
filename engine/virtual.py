"""Virtual (paper) trading account.

State lives in SQLite so it survives restarts and the SL monitor can run while the
dashboard is closed. Orders fill at the live NSE bid (sells) / ask (buys); margin is
blocked with SPAN + exposure per underlying/expiry group, same as the screener.
"""

import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from . import config, data_fetch, greeks_sr, risk_rules, span

DB_PATH = Path(__file__).parent / "data" / "virtual.db"
IST = timezone(timedelta(hours=5, minutes=30))  # fixed offset: Windows Python has no tz database
SL_MODES = ("auto", "alert", "off")
QUOTE_TTL = 30
MONITOR_INTERVAL = 60

_lock = threading.RLock()
_quote_cache: dict = {}
_exposure_cache: dict = {}

SCHEMA = """
CREATE TABLE IF NOT EXISTS account (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  starting_capital REAL NOT NULL,
  sl_mode_default TEXT NOT NULL DEFAULT 'auto',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL, expiry TEXT NOT NULL, side TEXT NOT NULL, strike REAL NOT NULL,
  qty INTEGER NOT NULL, avg_price REAL NOT NULL, lot_size INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'open', opened_at TEXT NOT NULL, closed_at TEXT,
  realized_pnl REAL NOT NULL DEFAULT 0, exit_price REAL,
  sl_mode TEXT NOT NULL DEFAULT 'off', sl_price REAL, sl_activates_on TEXT, sl_alert_at TEXT
);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL, symbol TEXT NOT NULL, expiry TEXT NOT NULL, side TEXT NOT NULL, strike REAL NOT NULL,
  action TEXT NOT NULL, qty INTEGER NOT NULL, price REAL NOT NULL, reason TEXT NOT NULL,
  position_id INTEGER, realized_pnl REAL NOT NULL DEFAULT 0, note TEXT
);
"""


# ---------- storage ----------

def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init(starting_capital: float = 1_000_000) -> None:
    with _lock, _conn() as c:
        c.executescript(SCHEMA)
        if not c.execute("SELECT 1 FROM account").fetchone():
            c.execute("INSERT INTO account VALUES (1, ?, 'auto', ?)", (starting_capital, _now()))


def _now() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")


def _today() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(IST).date())


def market_open() -> bool:
    now = datetime.now(IST)
    return now.weekday() < 5 and (9, 15) <= (now.hour, now.minute) < (15, 30)


# ---------- market data ----------

def _chain(symbol: str, expiry: str) -> tuple[float, pd.DataFrame]:
    key = (symbol, expiry)
    hit = _quote_cache.get(key)
    if hit and time.time() - hit[0] < QUOTE_TTL:
        return hit[1], hit[2]
    raw = data_fetch.fetch_option_chain(symbol, pd.Timestamp(expiry))
    spot = data_fetch.get_spot_price(raw)
    df = data_fetch.normalize_option_chain(raw).set_index("strikePrice")
    _quote_cache[key] = (time.time(), spot, df)
    return spot, df


def quote(symbol: str, expiry: str, side: str, strike: float) -> dict:
    spot, df = _chain(symbol, expiry)
    if strike not in df.index:
        raise ValueError(f"{symbol} {expiry} {strike:g} {side} not in the option chain")
    r = df.loc[strike]
    return {"spot": spot, "ltp": float(r[f"{side}_LTP"]), "bid": float(r[f"{side}_BID"]),
            "ask": float(r[f"{side}_ASK"]), "iv": float(r[f"{side}_IV"])}


def _fill_price(q: dict, action: str) -> tuple[float, str | None]:
    px = q["bid"] if action == "SELL" else q["ask"]
    if px > 0:
        return px, None
    if q["ltp"] > 0:
        return q["ltp"], "No live bid/ask (market closed or illiquid); filled at last traded price"
    raise ValueError("No price available for this contract")


def _exposure_pct(symbol: str) -> float:
    day = str(_today().date())
    hit = _exposure_cache.get(symbol)
    if hit and hit[0] == day:
        return hit[1]
    try:
        hist = data_fetch.fetch_price_history(f"{symbol}.NS", config.SR_LOOKBACK_DAYS)
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        pct = risk_rules._exposure_pct(hist)
    except Exception:
        pct = config.EXPOSURE_MIN_PCT
    _exposure_cache[symbol] = (day, pct)
    return pct


def group_margin(symbol: str, expiry: str, legs: list[dict], spot: float) -> dict:
    """legs: [{side, strike, qty}] signed. Returns SPAN + exposure on short legs."""
    legs = [l for l in legs if l["qty"] != 0]
    if not legs:
        return {"span": 0.0, "exposure": 0.0, "total": 0.0}
    span.load(risk_rules.get_universe())
    sp = span.scan_risk_positions(symbol, pd.Timestamp(expiry).strftime("%Y%m%d"), legs)
    if sp is None:
        raise ValueError(f"{symbol} {expiry} contract not found in NSE SPAN file")
    pct = _exposure_pct(symbol)
    exposure = sum(spot * -l["qty"] * pct / 100 for l in legs if l["qty"] < 0)
    return {"span": sp, "exposure": round(exposure, 2), "total": round(sp + exposure, 2)}


# ---------- queries ----------

def _open_rows(c, symbol=None, expiry=None):
    sql, args = "SELECT * FROM positions WHERE status='open'", []
    if symbol:
        sql += " AND symbol=? AND expiry=?"
        args += [symbol, expiry]
    return [dict(r) for r in c.execute(sql + " ORDER BY id", args)]


def _account_row(c) -> dict:
    return dict(c.execute("SELECT * FROM account WHERE id=1").fetchone())


def _groups(rows: list[dict]) -> dict:
    g: dict = {}
    for r in rows:
        g.setdefault((r["symbol"], r["expiry"]), []).append(r)
    return g


def _strategy_label(legs: list[dict]) -> str:
    shorts = sorted({l["side"] for l in legs if l["qty"] < 0})
    longs = sorted({l["side"] for l in legs if l["qty"] > 0})
    if not longs and shorts == ["CE", "PE"]:
        return "Short strangle" if len({l["strike"] for l in legs}) > 1 else "Short straddle"
    if not longs and shorts:
        return "Short call" if shorts == ["CE"] else "Short put"
    if not shorts and longs:
        return "Long call" if longs == ["CE"] else ("Long put" if longs == ["PE"] else "Long strangle")
    return "Custom"


def _sl_status(r: dict, today: pd.Timestamp) -> str:
    if r["qty"] > 0:
        return "n/a"
    if r["sl_mode"] == "off":
        return "off"
    if r["sl_alert_at"]:
        return "alert"
    return "armed" if today >= pd.Timestamp(r["sl_activates_on"]) else "waiting"


def get_positions() -> dict:
    with _lock, _conn() as c:
        rows = _open_rows(c)
    today = _today()
    groups, totals = [], {"pnl": 0.0, "margin": 0.0, "delta": 0.0, "theta": 0.0, "vega": 0.0, "gamma": 0.0}
    for (symbol, expiry), legs in _groups(rows).items():
        dte = max((pd.Timestamp(expiry) - today).days, 0)
        spot, out_legs, err = None, [], None
        for r in legs:
            leg = {k: r[k] for k in ("id", "side", "strike", "qty", "avg_price", "lot_size", "sl_mode",
                                     "sl_price", "sl_activates_on", "sl_alert_at", "opened_at")}
            leg["lots"] = abs(r["qty"]) // r["lot_size"]
            leg["sl_status"] = _sl_status(r, today)
            try:
                q = quote(symbol, expiry, r["side"], r["strike"])
                spot = q["spot"]
                g = greeks_sr.bs_greeks(spot, r["strike"], max(dte, 1), q["iv"], r["side"]) if q["iv"] > 0 else {}
                leg.update(ltp=q["ltp"], bid=q["bid"], ask=q["ask"], iv=q["iv"],
                           pnl=round((q["ltp"] - r["avg_price"]) * r["qty"], 2),
                           **{k: round(v * r["qty"], 4) for k, v in g.items()})
            except Exception as e:
                err = str(e)
                leg.update(ltp=None, pnl=0.0)
            out_legs.append(leg)
        try:
            m = group_margin(symbol, expiry, legs, spot) if spot else None
        except Exception as e:
            m, err = None, str(e)
        pnl = round(sum(l["pnl"] for l in out_legs), 2)
        greeks = {k: round(sum(l.get(k, 0) for l in out_legs), 3) for k in ("delta", "theta", "vega", "gamma")}
        premium = round(sum(-l["qty"] * l["avg_price"] for l in out_legs), 2)
        groups.append({"symbol": symbol, "expiry": expiry, "dte": dte, "spot": spot, "legs": out_legs,
                       "strategy": _strategy_label(legs), "pnl": pnl, "net_premium": premium,
                       "margin": m, "greeks": greeks, "error": err})
        totals["pnl"] += pnl
        totals["margin"] += m["total"] if m else 0
        for k in greeks:
            totals[k] += greeks[k]
    return {"groups": groups, "totals": {k: round(v, 2) for k, v in totals.items()},
            "market_open": market_open(), "account": get_account(_positions=groups)}


def get_account(_positions: list | None = None) -> dict:
    with _lock, _conn() as c:
        acct = _account_row(c)
        realized = c.execute("SELECT COALESCE(SUM(realized_pnl),0) FROM positions").fetchone()[0]
        n_open = c.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]
    groups = _positions if _positions is not None else (get_positions()["groups"] if n_open else [])
    unrealized = sum(g["pnl"] for g in groups)
    used = sum(g["margin"]["total"] for g in groups if g["margin"])
    value = acct["starting_capital"] + realized + unrealized
    return {
        "starting_capital": acct["starting_capital"], "created_at": acct["created_at"],
        "sl_mode_default": acct["sl_mode_default"],
        "realized_pnl": round(realized, 2), "unrealized_pnl": round(unrealized, 2),
        "account_value": round(value, 2), "used_margin": round(used, 2),
        "available_margin": round(value - used, 2),
        "return_pct": round((value / acct["starting_capital"] - 1) * 100, 2),
        "open_positions": n_open,
    }


def get_orders(limit: int = 200) -> list[dict]:
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,))]


def get_closed(limit: int = 200) -> list[dict]:
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM positions WHERE status='closed' ORDER BY closed_at DESC LIMIT ?", (limit,))]


# ---------- trading ----------

def _apply_trade(c, symbol, expiry, side, strike, action, qty, price, lot, reason, note, sl_mode):
    """Nets the trade into the open position for this contract and records the order."""
    signed = qty if action == "BUY" else -qty
    row = c.execute("SELECT * FROM positions WHERE status='open' AND symbol=? AND expiry=? AND side=? AND strike=?",
                    (symbol, expiry, side, strike)).fetchone()
    realized, pid = 0.0, None
    if row is None or (row["qty"] > 0) == (signed > 0):
        if row is None:
            sl = {"mode": sl_mode if signed < 0 else "off", "price": price if signed < 0 else None,
                  "on": str((_today() + timedelta(days=config.SL_GRACE_DAYS)).date()) if signed < 0 else None}
            cur = c.execute(
                "INSERT INTO positions (symbol, expiry, side, strike, qty, avg_price, lot_size, opened_at,"
                " sl_mode, sl_price, sl_activates_on) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (symbol, expiry, side, strike, signed, price, lot, _now(), sl["mode"], sl["price"], sl["on"]))
            pid = cur.lastrowid
        else:
            new_qty = row["qty"] + signed
            avg = (row["avg_price"] * abs(row["qty"]) + price * qty) / abs(new_qty)
            # Adding to a short raises the collected premium, so the breakeven SL moves with it.
            sl_price = avg if new_qty < 0 else row["sl_price"]
            c.execute("UPDATE positions SET qty=?, avg_price=?, sl_price=? WHERE id=?", (new_qty, avg, sl_price, row["id"]))
            pid = row["id"]
    else:
        closing = min(abs(row["qty"]), qty)
        direction = 1 if row["qty"] > 0 else -1
        realized = round((price - row["avg_price"]) * closing * direction, 2)
        new_qty = row["qty"] + signed
        pid = row["id"]
        if new_qty == 0:
            c.execute("UPDATE positions SET qty=0, status='closed', closed_at=?, exit_price=?,"
                      " realized_pnl=realized_pnl+? WHERE id=?", (_now(), price, realized, pid))
        elif (new_qty > 0) == (row["qty"] > 0):
            c.execute("UPDATE positions SET qty=?, realized_pnl=realized_pnl+? WHERE id=?", (new_qty, realized, pid))
        else:  # position flipped sides: close the old one, open the remainder fresh
            c.execute("UPDATE positions SET qty=0, status='closed', closed_at=?, exit_price=?,"
                      " realized_pnl=realized_pnl+? WHERE id=?", (_now(), price, realized, pid))
            flip = abs(new_qty)
            _apply_trade(c, symbol, expiry, side, strike, action, flip, price, lot, reason, note, sl_mode)
            qty -= flip
    c.execute("INSERT INTO orders (ts, symbol, expiry, side, strike, action, qty, price, reason, position_id,"
              " realized_pnl, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              (_now(), symbol, expiry, side, strike, action, qty, price, reason, pid, round(realized, 2), note))


def preview_order(symbol: str, expiry: str, legs: list[dict]) -> dict:
    """legs: [{side, strike, action: 'BUY'|'SELL', lots}]. Returns fills and margin impact."""
    lot = data_fetch.fetch_lot_size(symbol, pd.Timestamp(expiry))
    if not lot:
        raise ValueError(f"Lot size for {symbol} {expiry} not found")
    fills, notes = [], set()
    for l in legs:
        if l["action"] not in ("BUY", "SELL") or int(l["lots"]) < 1:
            raise ValueError("Each leg needs action BUY/SELL and at least 1 lot")
        q = quote(symbol, expiry, l["side"], float(l["strike"]))
        px, note = _fill_price(q, l["action"])
        if note:
            notes.add(note)
        fills.append({**l, "strike": float(l["strike"]), "qty": int(l["lots"]) * lot, "price": px, "spot": q["spot"]})
    spot = fills[0]["spot"]

    with _lock, _conn() as c:
        existing = _open_rows(c, symbol, expiry)
        default_sl = _account_row(c)["sl_mode_default"]
    before = [{"side": r["side"], "strike": r["strike"], "qty": r["qty"]} for r in existing]
    after = {(b["side"], b["strike"]): b["qty"] for b in before}
    for f in fills:
        k = (f["side"], f["strike"])
        after[k] = after.get(k, 0) + (f["qty"] if f["action"] == "BUY" else -f["qty"])
    after_legs = [{"side": s, "strike": k, "qty": q} for (s, k), q in after.items()]
    m_before = group_margin(symbol, expiry, before, spot)["total"]
    m_after = group_margin(symbol, expiry, after_legs, spot)
    acct = get_account()
    premium = sum(f["price"] * f["qty"] * (1 if f["action"] == "SELL" else -1) for f in fills)
    return {
        "symbol": symbol, "expiry": expiry, "lot_size": lot, "fills": fills,
        "premium": round(premium, 2), "margin_after": m_after, "margin_change": round(m_after["total"] - m_before, 2),
        "available_margin": acct["available_margin"], "sl_mode_default": default_sl,
        "sufficient": m_after["total"] - m_before <= acct["available_margin"],
        "notes": sorted(notes), "market_open": market_open(),
    }


def place_order(symbol: str, expiry: str, legs: list[dict], sl_mode: str | None = None) -> dict:
    p = preview_order(symbol, expiry, legs)
    if not p["sufficient"]:
        raise ValueError(f"Insufficient margin: needs ₹{p['margin_change']:,.0f}, "
                         f"available ₹{p['available_margin']:,.0f}")
    mode = sl_mode if sl_mode in SL_MODES else p["sl_mode_default"]
    note = "; ".join(p["notes"]) or None
    with _lock, _conn() as c:
        for f in p["fills"]:
            _apply_trade(c, symbol, expiry, f["side"], f["strike"], f["action"], f["qty"], f["price"],
                         p["lot_size"], "manual", note, mode)
    return {"filled": p["fills"], "premium": p["premium"], "notes": p["notes"]}


def _exit_rows(rows: list[dict], reason: str, price_override: dict | None = None) -> list[dict]:
    done = []
    with _lock, _conn() as c:
        for r in rows:
            action = "BUY" if r["qty"] < 0 else "SELL"
            if price_override and r["id"] in price_override:
                px, note = price_override[r["id"]], None
            else:
                px, note = _fill_price(quote(r["symbol"], r["expiry"], r["side"], r["strike"]), action)
            _apply_trade(c, r["symbol"], r["expiry"], r["side"], r["strike"], action, abs(r["qty"]),
                         px, r["lot_size"], reason, note, r["sl_mode"])
            done.append({"id": r["id"], "price": px})
    return done


def exit_position(position_id: int) -> list[dict]:
    with _lock, _conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM positions WHERE id=? AND status='open'", (position_id,))]
    if not rows:
        raise ValueError("Position not found or already closed")
    return _exit_rows(rows, "manual")


def exit_group(symbol: str, expiry: str) -> list[dict]:
    with _lock, _conn() as c:
        rows = _open_rows(c, symbol, expiry)
    return _exit_rows(rows, "manual")


def set_sl_mode(mode: str, position_id: int | None = None) -> dict:
    if mode not in SL_MODES:
        raise ValueError(f"SL mode must be one of {SL_MODES}")
    with _lock, _conn() as c:
        if position_id is None:
            c.execute("UPDATE account SET sl_mode_default=? WHERE id=1", (mode,))
        else:
            c.execute("UPDATE positions SET sl_mode=?, sl_alert_at=NULL WHERE id=? AND qty<0", (mode, position_id))
    return {"ok": True}


def dismiss_alert(position_id: int) -> dict:
    with _lock, _conn() as c:
        c.execute("UPDATE positions SET sl_alert_at=NULL WHERE id=?", (position_id,))
    return {"ok": True}


def reset(starting_capital: float = 1_000_000) -> dict:
    if starting_capital < 10_000:
        raise ValueError("Starting capital must be at least ₹10,000")
    with _lock, _conn() as c:
        c.execute("DELETE FROM positions")
        c.execute("DELETE FROM orders")
        c.execute("UPDATE account SET starting_capital=?, created_at=? WHERE id=1", (starting_capital, _now()))
    return get_account()


# ---------- monitor: stop loss + expiry ----------

def run_checks() -> dict:
    """Applies each short leg's SL mode and settles expired contracts. Safe to call any time."""
    today = _today()
    exited, alerted, settled = [], [], []
    with _lock, _conn() as c:
        rows = _open_rows(c)

    expired = [r for r in rows if pd.Timestamp(r["expiry"]) < today]
    for r in expired:
        try:
            hist = data_fetch.fetch_price_history(f"{r['symbol']}.NS", 10)
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.get_level_values(0)
            closes = hist["Close"].dropna()
            spot = float(closes[closes.index <= pd.Timestamp(r["expiry"])].iloc[-1])
            intrinsic = max(0.0, spot - r["strike"]) if r["side"] == "CE" else max(0.0, r["strike"] - spot)
            _exit_rows([r], "expiry", {r["id"]: round(intrinsic, 2)})
            settled.append(r["id"])
        except Exception:
            continue  # retry on the next pass

    if market_open():
        for r in rows:
            if r in expired or r["qty"] >= 0 or r["sl_mode"] == "off" or r["sl_alert_at"]:
                continue
            if today < pd.Timestamp(r["sl_activates_on"]):
                continue
            try:
                q = quote(r["symbol"], r["expiry"], r["side"], r["strike"])
            except Exception:
                continue
            buyback = q["ask"] if q["ask"] > 0 else q["ltp"]
            if buyback < r["sl_price"]:
                continue
            if r["sl_mode"] == "auto":
                _exit_rows([r], "sl_auto", {r["id"]: buyback})
                exited.append(r["id"])
            else:
                with _lock, _conn() as c:
                    c.execute("UPDATE positions SET sl_alert_at=? WHERE id=?", (_now(), r["id"]))
                alerted.append(r["id"])
    return {"exited": exited, "alerted": alerted, "settled": settled}


def start_monitor() -> None:
    def loop():
        while True:
            try:
                with _lock, _conn() as c:
                    has_open = c.execute("SELECT 1 FROM positions WHERE status='open' LIMIT 1").fetchone()
                if has_open:
                    run_checks()
            except Exception:
                pass  # monitor must never die; next pass retries
            time.sleep(MONITOR_INTERVAL)

    threading.Thread(target=loop, daemon=True, name="virtual-sl-monitor").start()
