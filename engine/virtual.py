"""Virtual (paper) trading account, one per user.

State lives in PostgreSQL (engine/db.py) so it survives restarts, and the worker's SL monitor
runs while the dashboard is closed. Quotes and priced snapshots are shared through Redis.

Limit orders only, as on the live account. A limit that the market already meets (a sell at or
below the bid, a buy at or above the ask) fills at once at that bid or ask. Any other limit rests
as an open order: the worker fills it at its limit once the market reaches it, and it expires at
the close of its session. Orders placed outside market hours wait for the next session. Every public function takes the acting `user_id` first; the
RPC layer injects it from the session, never from client params. Orders fill at the live NSE
bid (sells) / ask (buys); margin is blocked with SPAN + exposure per underlying/expiry group,
same as the screener.
"""

import threading
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import cache, config, data_fetch, db, greeks_sr, pivots, pricing, progress, risk_rules, span, users

IST = timezone(timedelta(hours=5, minutes=30))  # fixed offset: Windows Python has no tz database
SL_MODES = ("auto", "alert", "off")
QUOTE_TTL = 60  # seconds an option chain is shared before the next NSE fetch
TICK = 0.05     # NSE tick size for stock options
MONITOR_INTERVAL = 60

_lock = threading.RLock()  # serialises trades in this process; the account row lock covers other processes
_quote_cache: dict = {}
_exposure_cache: dict = {}


# ---------- storage ----------

def _now() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")


def _today() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(IST).date())


def market_open() -> bool:
    now = datetime.now(IST)
    return now.weekday() < 5 and (9, 15) <= (now.hour, now.minute) < (15, 30)


def market_window() -> bool:
    """Pre-open through a little after the close: the stretch worth refreshing often."""
    now = datetime.now(IST)
    return now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) < (15, 45)


# ---------- market data ----------

def _chain(symbol: str, expiry: str) -> tuple[float, pd.DataFrame]:
    """Option chain, cached QUOTE_TTL (60 s) in this process and in Redis (`quote:{sym}:{expiry}`), so every
    user and process holding the same contract shares one NSE call."""
    key = (symbol, expiry)
    hit = _quote_cache.get(key)
    if hit and time.time() - hit[0] < QUOTE_TTL:
        return hit[1], hit[2]
    shared = cache.get_json(f"quote:{symbol}:{expiry}")
    if shared:
        df = pd.DataFrame(shared["chain"]).set_index("strikePrice")
        _quote_cache[key] = (shared["at"], shared["spot"], df)
        return shared["spot"], df
    raw = data_fetch.fetch_option_chain(symbol, pd.Timestamp(expiry))
    spot = data_fetch.get_spot_price(raw)
    df = data_fetch.normalize_option_chain(raw).set_index("strikePrice")
    now = time.time()
    _quote_cache[key] = (now, spot, df)
    cache.set_json(f"quote:{symbol}:{expiry}", {"at": now, "spot": spot, "chain": df.reset_index().to_dict(orient="list")},
                   ttl=QUOTE_TTL)
    return spot, df


def quote(symbol: str, expiry: str, side: str, strike: float) -> dict:
    spot, df = _chain(symbol, expiry)
    if strike not in df.index:
        raise ValueError(f"{symbol} {expiry} {strike:g} {side} not in the option chain")
    r = df.loc[strike]
    return {"spot": spot, "ltp": float(r[f"{side}_LTP"]), "bid": float(r[f"{side}_BID"]),
            "ask": float(r[f"{side}_ASK"]), "iv": float(r[f"{side}_IV"]), "oi": int(r[f"{side}_OI"])}


def tick(price: float) -> float:
    return round(round(float(price) / TICK) * TICK, 2)


MARK_TTL = 5 * 86400  # an in-session mark stands in until the next session, weekends included


def mark(symbol: str, expiry: str, side: str, strike: float, q: dict) -> tuple[float | None, str]:
    """Fair value of an open leg (engine/pricing.mark): the bid/ask mid. In session each mid is kept
    in Redis; out of session NSE often clears or freezes the book, so that last in-session mid is
    used ("close") instead of a stale LTP."""
    key = f"mark:{symbol}:{expiry}:{side}:{float(strike):g}"
    if market_open() and pricing.has_book(q["bid"], q["ask"]):
        px = pricing.mid(q["bid"], q["ask"])
        cache.set_json(key, {"px": px}, ttl=MARK_TTL)
        return px, "mid"
    if not market_open():
        kept = cache.get_json(key)
        if kept:
            return float(kept["px"]), "close"
    return pricing.mark(q["bid"], q["ask"], q["ltp"])


def _touch(q: dict, action: str) -> float:
    """The price a marketable limit fills at: the bid for a sell, the ask for a buy (0 if none)."""
    return q["bid"] if action == "SELL" else q["ask"]


def _default_limit(q: dict, action: str) -> float:
    """Ticket default: the touch price on a tight book; the mid when the spread is wider than
    TICKET_MID_SPREAD_PCT (it may rest instead of filling, but doesn't give the spread away);
    the last traded price when there is no bid/ask."""
    sp = pricing.spread_pct(q["bid"], q["ask"])
    if sp is not None and sp > config.TICKET_MID_SPREAD_PCT:
        return tick(pricing.mid(q["bid"], q["ask"]))
    px = _touch(q, action) or q["ltp"]
    if px <= 0:
        raise ValueError("No price available for this contract")
    return tick(px)


def _marketable(q: dict, action: str, limit: float) -> bool:
    px = _touch(q, action)
    if not market_open() or px <= 0:
        return False
    return px >= limit if action == "SELL" else px <= limit


def _fill_price(q: dict, action: str) -> tuple[float, str | None]:
    """Exit price for the rules: a limit at the touch, which fills at once. No bid/ask means no
    exit this pass; the next pass retries."""
    px = _touch(q, action)
    if px > 0:
        return px, None
    raise ValueError("No live bid/ask for this contract; the exit waits for one")


def _valid_until() -> str:
    """Day orders: today's session if the market is open now, else the next weekday's."""
    now = datetime.now(IST)
    day = now.date()
    if not (now.weekday() < 5 and (now.hour, now.minute) < (15, 30)):
        day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.isoformat()


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

def _open_rows(c, user_id, symbol=None, expiry=None):
    sql = "SELECT * FROM positions WHERE user_id=:u AND status='open'"
    if symbol:
        sql += " AND symbol=:s AND expiry=:e"
    return c.all(sql + " ORDER BY id", u=user_id, s=symbol, e=expiry)


def _account_row(c, user_id) -> dict:
    row = c.one("SELECT * FROM accounts WHERE user_id=:u", u=user_id)
    if row is None:
        raise ValueError("No virtual account for this user")
    return row


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


def get_positions(user_id: int) -> dict:
    with db.tx(user_id) as c:
        rows = _open_rows(c, user_id)
    today = _today()
    groups, totals = [], {"pnl": 0.0, "pnl_exit": 0.0, "margin": 0.0, "delta": 0.0, "theta": 0.0, "vega": 0.0, "gamma": 0.0}
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
                px, src = mark(symbol, expiry, r["side"], r["strike"], q)
                # Closing touch: a short buys back at the ask, a long sells at the bid.
                close_px = q["ask"] if r["qty"] < 0 else q["bid"]
                leg.update(ltp=q["ltp"], bid=q["bid"], ask=q["ask"], iv=q["iv"], mark=px, mark_src=src,
                           ltp_gap_pct=pricing.ltp_gap_pct(q["bid"], q["ask"], q["ltp"]),
                           pnl=round((px - r["avg_price"]) * r["qty"], 2) if px is not None else 0.0,
                           pnl_exit=round((close_px - r["avg_price"]) * r["qty"], 2) if close_px > 0 else None,
                           **{k: round(v * r["qty"], 4) for k, v in g.items()})
            except Exception as e:
                err = str(e)
                leg.update(ltp=None, mark=None, mark_src="none", pnl=0.0, pnl_exit=None)
            out_legs.append(leg)
        try:
            m = group_margin(symbol, expiry, legs, spot) if spot else None
        except Exception as e:
            m, err = None, str(e)
        pnl = round(sum(l["pnl"] for l in out_legs), 2)
        exits = [l["pnl_exit"] for l in out_legs]
        pnl_exit = round(sum(exits), 2) if exits and None not in exits else None
        greeks = {k: round(sum(l.get(k, 0) for l in out_legs), 3) for k in ("delta", "theta", "vega", "gamma")}
        premium = round(sum(-l["qty"] * l["avg_price"] for l in out_legs), 2)
        groups.append({"symbol": symbol, "expiry": expiry, "dte": dte, "spot": spot, "legs": out_legs,
                       "time_exit_on": time_exit_date(expiry),
                       "strategy": _strategy_label(legs), "pnl": pnl, "pnl_exit": pnl_exit, "net_premium": premium,
                       "margin": m, "greeks": greeks, "error": err})
        totals["pnl"] += pnl
        if totals.get("pnl_exit", 0) is not None:
            totals["pnl_exit"] = None if pnl_exit is None else totals.get("pnl_exit", 0.0) + pnl_exit
        totals["margin"] += m["total"] if m else 0
        for k in greeks:
            totals[k] += greeks[k]
    return {"groups": groups, "totals": {k: (round(v, 2) if v is not None else None) for k, v in totals.items()},
            "market_open": market_open(), "account": get_account(user_id, _positions=groups)}


def get_account(user_id: int, _positions: list | None = None) -> dict:
    with db.tx(user_id) as c:
        acct = _account_row(c, user_id)
        realized = c.value("SELECT COALESCE(SUM(realized_pnl),0) FROM positions WHERE user_id=:u", u=user_id)
        n_open = c.value("SELECT COUNT(*) FROM positions WHERE user_id=:u AND status='open'", u=user_id)
        blocked = c.value("SELECT COALESCE(SUM(blocked_margin),0) FROM pending_orders "
                          "WHERE user_id=:u AND status='open'", u=user_id)
        n_pending = c.value("SELECT COUNT(*) FROM pending_orders WHERE user_id=:u AND status='open'", u=user_id)
    groups = _positions if _positions is not None else (get_positions(user_id)["groups"] if n_open else [])
    unrealized = sum(g["pnl"] for g in groups)
    used = sum(g["margin"]["total"] for g in groups if g["margin"]) + blocked
    value = acct["starting_capital"] + realized + unrealized
    return {
        "starting_capital": acct["starting_capital"], "created_at": acct["created_at"],
        "sl_mode_default": acct["sl_mode_default"],
        "realized_pnl": round(realized, 2), "unrealized_pnl": round(unrealized, 2),
        "account_value": round(value, 2), "used_margin": round(used, 2),
        "available_margin": round(value - used, 2),
        "return_pct": round((value / acct["starting_capital"] - 1) * 100, 2),
        "open_positions": n_open,
        "open_orders": n_pending, "blocked_margin": round(blocked, 2),
    }


def get_orders(user_id: int, limit: int = 200) -> list[dict]:
    """The account's fills (entries, exits, settlements), newest first."""
    with db.tx(user_id) as c:
        return c.all("SELECT * FROM orders WHERE user_id=:u ORDER BY id DESC LIMIT :n", u=user_id, n=limit)


def get_closed(user_id: int, limit: int = 200) -> list[dict]:
    """Closed positions, most recently closed first."""
    with db.tx(user_id) as c:
        return c.all("SELECT * FROM positions WHERE user_id=:u AND status='closed' "
                     "ORDER BY closed_at DESC LIMIT :n", u=user_id, n=limit)


# ---------- trading ----------

def _lock_account(c, user_id) -> None:
    """Row lock on the user's account: one user's trades run one at a time across processes."""
    c.value("SELECT 1 FROM accounts WHERE user_id=:u FOR UPDATE", u=user_id)


def _close_row(c, user_id, pid, price, realized, reason) -> None:
    c.run("UPDATE positions SET qty=0, status='closed', closed_at=now(), exit_price=:p,"
          " realized_pnl=realized_pnl+:r WHERE id=:i AND user_id=:u", p=price, r=realized, i=pid, u=user_id)
    progress.record_close(c, user_id, pid, reason)  # learning-path trade log and XP (#122), same transaction


def _apply_trade(c, user_id, symbol, expiry, side, strike, action, qty, price, lot, reason, note, sl_mode,
                 limit=None, entry_delta=None):
    """Nets the trade into the open position for this contract and records the order."""
    signed = qty if action == "BUY" else -qty
    row = c.one("SELECT * FROM positions WHERE user_id=:u AND status='open' AND symbol=:s AND expiry=:e"
                " AND side=:sd AND strike=:k", u=user_id, s=symbol, e=expiry, sd=side, k=strike)
    realized, pid = 0.0, None
    if row is None or (row["qty"] > 0) == (signed > 0):
        if row is None:
            sl = {"mode": sl_mode if signed < 0 else "off", "price": price if signed < 0 else None,
                  "on": str((_today() + timedelta(days=config.SL_GRACE_DAYS)).date()) if signed < 0 else None}
            pid = c.value(
                "INSERT INTO positions (user_id, symbol, expiry, side, strike, qty, avg_price, lot_size,"
                " sl_mode, sl_price, sl_activates_on, entry_delta) VALUES (:u,:s,:e,:sd,:k,:q,:p,:lot,:m,:sp,:on,:d)"
                " RETURNING id", u=user_id, s=symbol, e=expiry, sd=side, k=strike, q=signed, p=price, lot=lot,
                m=sl["mode"], sp=sl["price"], on=sl["on"], d=entry_delta if signed < 0 else None)
        else:
            new_qty = row["qty"] + signed
            avg = (row["avg_price"] * abs(row["qty"]) + price * qty) / abs(new_qty)
            # Adding to a short raises the collected premium, so the breakeven SL moves with it.
            sl_price = avg if new_qty < 0 else row["sl_price"]
            c.run("UPDATE positions SET qty=:q, avg_price=:a, sl_price=:sp WHERE id=:i AND user_id=:u",
                  q=new_qty, a=avg, sp=sl_price, i=row["id"], u=user_id)
            pid = row["id"]
    else:
        closing = min(abs(row["qty"]), qty)
        direction = 1 if row["qty"] > 0 else -1
        realized = round((price - row["avg_price"]) * closing * direction, 2)
        new_qty = row["qty"] + signed
        pid = row["id"]
        if new_qty == 0:
            _close_row(c, user_id, pid, price, realized, reason)
        elif (new_qty > 0) == (row["qty"] > 0):
            c.run("UPDATE positions SET qty=:q, realized_pnl=realized_pnl+:r WHERE id=:i AND user_id=:u",
                  q=new_qty, r=realized, i=pid, u=user_id)
        else:  # position flipped sides: close the old one, open the remainder fresh
            _close_row(c, user_id, pid, price, realized, reason)
            flip = abs(new_qty)
            _apply_trade(c, user_id, symbol, expiry, side, strike, action, flip, price, lot, reason, note, sl_mode, limit)
            qty -= flip
    c.run("INSERT INTO orders (user_id, symbol, expiry, side, strike, action, qty, price, reason, position_id,"
          " realized_pnl, note, limit_price) VALUES (:u,:s,:e,:sd,:k,:a,:q,:p,:r,:pid,:rp,:n,:lim)",
          u=user_id, s=symbol, e=expiry, sd=side, k=strike, a=action, q=qty, p=price, r=reason, pid=pid,
          rp=round(realized, 2), n=note, lim=limit if limit is not None else price)


def _check_liquidity(l: dict, q: dict) -> None:
    """A market order (no limit typed) fills at the ask, so on an illiquid strike that ask is the
    price the trade books at. Refuse it there instead of letting a wide, thin quote book as the
    entry premium and show up as a false unbooked loss the moment it fills (#80)."""
    ask = q["ask"]
    if ask <= 0:
        raise ValueError(f"{l['strike']:g} {l['side']} has no live ask price; place a limit order instead")
    spread_pct = (ask - q["bid"]) / ask * 100 if q["bid"] > 0 else 100.0
    if q["oi"] < config.LIQUIDITY_MIN_OI or spread_pct > config.LIQUIDITY_MAX_SPREAD_PCT:
        raise ValueError(f"{l['strike']:g} {l['side']} is too illiquid for a market order "
                         f"(OI {q['oi']:,}, spread {spread_pct:.0f}% of ask ₹{ask:.2f}); "
                         f"place a limit order instead")


def preview_order(user_id: int, symbol: str, expiry: str, legs: list[dict]) -> dict:
    """Prices an order without placing it. legs: [{side, strike, action: 'BUY'|'SELL', lots, price?}].
    `price` is the limit; without it it's a market order and the limit defaults to the touch price (the bid for a sell, the ask for
    a buy) — gated by _check_liquidity so a thin quote can't book a bad fill. Returns each leg's
    limit, whether it fills now, and the margin impact."""
    lot = data_fetch.fetch_lot_size(symbol, pd.Timestamp(expiry))
    if not lot:
        raise ValueError(f"Lot size for {symbol} {expiry} not found")
    fills, notes, illiquid = [], set(), []
    for l in legs:
        if l["action"] not in ("BUY", "SELL") or int(l["lots"]) < 1:
            raise ValueError("Each leg needs action BUY/SELL and at least 1 lot")
        q = quote(symbol, expiry, l["side"], float(l["strike"]))
        if not l.get("price"):
            _check_liquidity(l, q)
        liq = pricing.liquidity(q["bid"], q["ask"], q["ltp"], q["oi"], market_open())
        if liq["ok"] is False:
            illiquid.append({"side": l["side"], "strike": float(l["strike"]), "reason": liq["reason"],
                             "spread_pct": liq["spread_pct"], "bid": q["bid"], "ask": q["ask"], "ltp": q["ltp"]})
        limit = tick(l["price"]) if l.get("price") else _default_limit(q, l["action"])
        if limit <= 0:
            raise ValueError("Limit price must be above zero")
        now = _marketable(q, l["action"], limit)
        # Fills now at the touch (never worse than the limit); otherwise the premium is at the limit.
        px = _touch(q, l["action"]) if now else limit
        fills.append({**l, "strike": float(l["strike"]), "qty": int(l["lots"]) * lot, "limit": limit,
                      "price": px, "fills_now": now, "bid": q["bid"], "ask": q["ask"], "ltp": q["ltp"],
                      "spot": q["spot"], "iv": q["iv"]})
    if not market_open():
        notes.add("Market closed: the order waits and fills in the next session if the price is reached")
    elif not all(f["fills_now"] for f in fills):
        notes.add("A limit away from the market waits as an open order and expires at 15:30")
    with db.tx(user_id) as c:
        existing = _open_rows(c, user_id, symbol, expiry)
        default_sl = _account_row(c, user_id)["sl_mode_default"]
        waiting = _waiting(c, user_id, symbol, expiry)
    premium = sum(f["price"] * f["qty"] * (1 if f["action"] == "SELL" else -1) for f in fills)
    return {
        "symbol": symbol, "expiry": expiry, "lot_size": lot, "fills": fills,
        "premium": round(premium, 2), **_margin_impact(user_id, symbol, expiry, existing, fills),
        "sl_mode_default": default_sl, "notes": sorted(notes), "market_open": market_open(),
        "waiting": waiting, "illiquid": illiquid,
    }


def _waiting(c, user_id: int, symbol: str, expiry: str) -> list[dict]:
    """Open orders on this stock and expiry that haven't filled yet."""
    rows = c.all("SELECT id, side, strike, action, qty, limit_price, reason, created_at FROM pending_orders"
                 " WHERE user_id=:u AND symbol=:s AND expiry=:e AND status='open' ORDER BY id",
                 u=user_id, s=symbol, e=expiry)
    return [{**r, "strike": float(r["strike"]), "limit_price": float(r["limit_price"])} for r in rows]


def _margin_impact(user_id: int, symbol: str, expiry: str, existing: list[dict], fills: list[dict]) -> dict:
    """Margin the group needs after `fills`, against what the account has free right now."""
    spot = fills[0]["spot"]
    before = [{"side": r["side"], "strike": r["strike"], "qty": r["qty"]} for r in existing]
    after = {(b["side"], b["strike"]): b["qty"] for b in before}
    for f in fills:
        k = (f["side"], f["strike"])
        after[k] = after.get(k, 0) + (f["qty"] if f["action"] == "BUY" else -f["qty"])
    after_legs = [{"side": s, "strike": k, "qty": q} for (s, k), q in after.items()]
    m_before = group_margin(symbol, expiry, before, spot)["total"]
    m_after = group_margin(symbol, expiry, after_legs, spot)
    change = round(m_after["total"] - m_before, 2)
    available = get_account(user_id)["available_margin"]
    return {"margin_after": m_after, "margin_change": change, "available_margin": available,
            "sufficient": change <= available}


def _insufficient(m: dict) -> ValueError:
    return ValueError(f"Insufficient margin: needs ₹{m['margin_change']:,.0f}, "
                      f"available ₹{m['available_margin']:,.0f}")


def place_order(user_id: int, symbol: str, expiry: str, legs: list[dict], sl_mode: str | None = None,
                confirm_waiting: bool = False, confirm_illiquid: bool = False) -> dict:
    """Places an order on the virtual account. Always prices fills itself from live quotes. While an
    earlier order on the same stock and expiry is still waiting, it refuses unless `confirm_waiting` is set, so a
    second click never doubles the trade by accident. A leg on an illiquid strike (wide spread, thin
    OI, stale last trade) needs `confirm_illiquid`: the ticket shows why before asking."""
    p = preview_order(user_id, symbol, expiry, legs)
    if p["illiquid"] and not confirm_illiquid:
        bad = "; ".join(f"{i['strike']:g} {i['side']}: {i['reason']}" for i in p["illiquid"])
        raise ValueError(f"Illiquid strike ({bad}). Confirm to place anyway")
    return execute_order(user_id, p, sl_mode, reason="manual", allow_waiting=confirm_waiting)


def _entry_delta(expiry: str, f: dict) -> float | None:
    """|delta| of a sell at fill time, from the quote's IV, for the learning-path XP rules (#122)."""
    if f["action"] != "SELL" or not f.get("iv") or not f.get("spot"):
        return None
    dte = max((pd.Timestamp(expiry) - _today()).days, 1)
    try:
        return round(abs(greeks_sr.bs_delta(f["spot"], f["strike"], dte, f["iv"], f["side"])), 4)
    except (ValueError, ZeroDivisionError):
        return None


def execute_order(user_id: int, p: dict, sl_mode: str | None = None, reason: str = "manual",
                  extra_note: str | None = None, allow_waiting: bool = True) -> dict:
    """Books a preview produced by preview_order. In-process only (auto-trade, place_order):
    it trusts the fills inside `p`, so it must never be reachable from the RPC table."""
    symbol, expiry = p["symbol"], p["expiry"]
    if not p["sufficient"]:
        raise _insufficient(p)
    mode = sl_mode if sl_mode in SL_MODES else p["sl_mode_default"]
    note = "; ".join([n for n in [extra_note, *p["notes"]] if n]) or None
    resting = [f for f in p["fills"] if not f["fills_now"]]
    opened = []
    with _lock, db.tx(user_id) as c:
        _lock_account(c, user_id)
        # Under the lock, so two quick clicks or two tabs can't both pass.
        if not allow_waiting and _waiting(c, user_id, symbol, expiry):
            raise ValueError(f"Your earlier order on {symbol} {expiry} hasn't filled yet. "
                             "Confirm to place another one")
        # Check again under the lock: an order booked since the preview (another tab, another API
        # process, an auto-trade run) may have used the same free margin. Reads on other
        # connections see it, because it committed before this lock was granted.
        m = _margin_impact(user_id, symbol, expiry, _open_rows(c, user_id, symbol, expiry), p["fills"])
        if not m["sufficient"]:
            raise _insufficient(m)
        # Open entry orders hold their share of the margin until they fill or end.
        hold = max(m["margin_change"], 0) * len(resting) / len(p["fills"]) if resting else 0
        for f in p["fills"]:
            if f["fills_now"]:
                _apply_trade(c, user_id, symbol, expiry, f["side"], f["strike"], f["action"], f["qty"], f["price"],
                             p["lot_size"], reason, note, mode, f["limit"], entry_delta=_entry_delta(expiry, f))
            else:
                opened.append(c.value(
                    "INSERT INTO pending_orders (user_id, symbol, expiry, side, strike, action, qty, lot_size,"
                    " limit_price, reason, note, sl_mode, blocked_margin, valid_until) VALUES"
                    " (:u,:s,:e,:sd,:k,:a,:q,:lot,:lim,:r,:n,:m,:b,:v) RETURNING id",
                    u=user_id, s=symbol, e=expiry, sd=f["side"], k=f["strike"], a=f["action"], q=f["qty"],
                    lot=p["lot_size"], lim=f["limit"], r=reason, n=note, m=mode, b=round(hold / len(resting), 2),
                    v=_valid_until()))
    return {"filled": [f for f in p["fills"] if f["fills_now"]], "open": resting, "open_ids": opened,
            "premium": p["premium"], "notes": p["notes"]}


def _exit_rows(user_id: int, rows: list[dict], reason: str, price_override: dict | None = None) -> list[dict]:
    """Closes each leg with a limit at the touch. A leg with no bid/ask, or any leg while the market
    is closed, becomes an open limit order at the last price instead. Settlement (price_override)
    books at the given price."""
    done = []
    with _lock, db.tx(user_id) as c:
        _lock_account(c, user_id)
        for r in rows:
            # Re-read under the lock: the caller's copy may be stale (a fill or exit since).
            r = c.one("SELECT * FROM positions WHERE id=:i AND user_id=:u AND status='open'", i=r["id"], u=user_id)
            if r is None:
                continue
            action = "BUY" if r["qty"] < 0 else "SELL"
            if price_override and r["id"] in price_override:
                px = price_override[r["id"]]
                _apply_trade(c, user_id, r["symbol"], r["expiry"], r["side"], r["strike"], action, abs(r["qty"]),
                             px, r["lot_size"], reason, None, r["sl_mode"])
                done.append({"id": r["id"], "price": px, "status": "filled"})
                continue
            contract = dict(u=user_id, s=r["symbol"], e=r["expiry"], sd=r["side"], k=r["strike"], a=action)
            q = quote(r["symbol"], r["expiry"], r["side"], r["strike"])
            limit = _default_limit(q, action)
            if _marketable(q, action, limit):
                px = _touch(q, action)
                _apply_trade(c, user_id, r["symbol"], r["expiry"], r["side"], r["strike"], action, abs(r["qty"]),
                             px, r["lot_size"], reason, None, r["sl_mode"], limit)
                # The position is flat now; an older exit still waiting would reopen it the other way.
                c.run("UPDATE pending_orders SET status='cancelled', updated_at=now() WHERE user_id=:u"
                      " AND status='open' AND symbol=:s AND expiry=:e AND side=:sd AND strike=:k AND action=:a",
                      **contract)
                done.append({"id": r["id"], "price": px, "status": "filled"})
                continue
            # Orders already waiting in the closing direction reduce the position when they fill.
            # Queue only what they don't cover, so pressing Exit twice can't overshoot into an
            # opposite position.
            covered = c.value("SELECT COALESCE(SUM(qty),0) FROM pending_orders WHERE user_id=:u AND status='open'"
                              " AND symbol=:s AND expiry=:e AND side=:sd AND strike=:k AND action=:a", **contract)
            left = abs(r["qty"]) - int(covered)
            if left <= 0:
                done.append({"id": r["id"], "price": None, "status": "already_open"})
                continue
            oid = c.value(
                "INSERT INTO pending_orders (user_id, symbol, expiry, side, strike, action, qty, lot_size,"
                " limit_price, reason, sl_mode, valid_until) VALUES (:u,:s,:e,:sd,:k,:a,:q,:lot,:lim,:r,:m,:v)"
                " RETURNING id", **contract, q=left, lot=r["lot_size"], lim=limit, r=reason, m=r["sl_mode"],
                v=_valid_until())
            done.append({"id": r["id"], "price": limit, "status": "open", "order_id": oid})
    return done


def exit_position(user_id: int, position_id: int) -> list[dict]:
    """Closes one open position with a limit at the touch. With the market shut, or no bid/ask, it
    becomes an open limit order at the last price instead."""
    with db.tx(user_id) as c:
        rows = c.all("SELECT * FROM positions WHERE id=:i AND user_id=:u AND status='open'", i=position_id, u=user_id)
    if not rows:
        raise ValueError("Position not found or already closed")
    return _exit_rows(user_id, rows, "manual")


def exit_group(user_id: int, symbol: str, expiry: str) -> list[dict]:
    """Closes every open leg in one stock and expiry, the same way as exit_position. Works for a
    stock that has since left the Nifty 50."""
    with db.tx(user_id) as c:
        rows = _open_rows(c, user_id, symbol, expiry)
    if not rows:
        raise ValueError(f"No open positions in {symbol} {expiry}")
    return _exit_rows(user_id, rows, "manual")


def set_sl_mode(user_id: int, mode: str, position_id: int | None = None) -> dict:
    """Sets the stop-loss mode (auto, alert or off) of one short position, or the account default
    for new positions when position_id is omitted."""
    if mode not in SL_MODES:
        raise ValueError(f"SL mode must be one of {SL_MODES}")
    with db.tx(user_id) as c:
        if position_id is None:
            c.run("UPDATE accounts SET sl_mode_default=:m WHERE user_id=:u", m=mode, u=user_id)
        else:
            c.run("UPDATE positions SET sl_mode=:m, sl_alert_at=NULL WHERE id=:i AND user_id=:u AND qty<0",
                  m=mode, i=position_id, u=user_id)
    return {"ok": True}


def dismiss_alert(user_id: int, position_id: int) -> dict:
    """Clears a position's stop-loss alert."""
    with db.tx(user_id) as c:
        c.run("UPDATE positions SET sl_alert_at=NULL WHERE id=:i AND user_id=:u", i=position_id, u=user_id)
    return {"ok": True}


def reset(user_id: int, starting_capital: float = config.STARTING_CAPITAL) -> dict:
    """Deletes every order and position and restarts the virtual account with `starting_capital`
    (₹10,000 to ₹1,000 crore)."""
    if not 10_000 <= starting_capital <= 10_000_000_000:  # the NaN-safe form: NaN fails both bounds
        raise ValueError("Starting capital must be from ₹10,000 to ₹1,000 crore")
    with _lock, db.tx(user_id) as c:
        _lock_account(c, user_id)
        c.run("DELETE FROM orders WHERE user_id=:u", u=user_id)
        c.run("DELETE FROM pending_orders WHERE user_id=:u", u=user_id)
        c.run("DELETE FROM positions WHERE user_id=:u", u=user_id)
        c.run("UPDATE accounts SET starting_capital=:cap, created_at=now() WHERE user_id=:u",
              cap=starting_capital, u=user_id)
    return get_account(user_id)


# ---------- open limit orders ----------

def price_levels(user_id: int, symbol: str) -> dict:
    """Price history and floor pivots for a stock the user holds (Portfolio chart). Limited to held
    stocks so a client can't use it to make the server fetch arbitrary tickers."""
    with db.tx(user_id) as c:
        held = c.value("SELECT 1 FROM positions WHERE user_id=:u AND symbol=:s AND status='open' LIMIT 1",
                       u=user_id, s=symbol)
    if not held:
        raise ValueError(f"No open position in {symbol}")
    return pivots.for_symbol(symbol, datetime.fromisoformat(_valid_until()).date())


def get_open_orders(user_id: int) -> list[dict]:
    """Open limit orders with the current bid/ask beside each, for Improve 1 tick / Cancel."""
    with db.tx(user_id) as c:
        rows = c.all("SELECT id, symbol, expiry, side, strike, action, qty, lot_size, limit_price, reason,"
                     " blocked_margin, valid_until, created_at FROM pending_orders"
                     " WHERE user_id=:u AND status='open' ORDER BY id", u=user_id)
    for r in rows:
        try:
            q = quote(r["symbol"], r["expiry"], r["side"], r["strike"])
            r.update(bid=q["bid"], ask=q["ask"], ltp=q["ltp"])
        except Exception:
            r.update(bid=None, ask=None, ltp=None)
        r["lots"] = r["qty"] // r["lot_size"]
    return rows


def cancel_order(user_id: int, order_id: int) -> dict:
    """Cancels an open limit order, which releases its blocked margin. Refused once it has filled
    or ended."""
    with db.tx(user_id) as c:
        n = c.run("UPDATE pending_orders SET status='cancelled', updated_at=now() "
                  "WHERE id=:i AND user_id=:u AND status='open'", i=order_id, u=user_id)
    if not n:
        raise ValueError("Order not found, or it already filled or ended")
    return {"ok": True}


def modify_order(user_id: int, order_id: int, price: float) -> dict:
    """Changes an open limit order's price. If the market already meets it, the order fills now at the bid/ask."""
    price = tick(price)
    if price <= 0:
        raise ValueError("Limit price must be above zero")
    with db.tx(user_id) as c:
        n = c.run("UPDATE pending_orders SET limit_price=:p, updated_at=now() "
                  "WHERE id=:i AND user_id=:u AND status='open'", p=price, i=order_id, u=user_id)
    if not n:
        raise ValueError("Order not found, or it already filled or ended")
    filled = match_pending(user_id, only=order_id)
    return {"ok": True, "filled": bool(filled)}


def match_pending(user_id: int, only: int | None = None) -> list[int]:
    """Fills open orders the market has reached, and expires those past their session.
    A resting order fills at its own limit, as on the exchange."""
    filled = []
    with db.tx(user_id) as c:
        c.run("UPDATE pending_orders SET status='expired', updated_at=now() WHERE user_id=:u AND status='open'"
              " AND (valid_until < CURRENT_DATE OR (valid_until = CURRENT_DATE AND :closed))",
              u=user_id, closed=_session_over())
        sql = "SELECT * FROM pending_orders WHERE user_id=:u AND status='open'" + (" AND id=:i" if only else "")
        rows = c.all(sql + " ORDER BY id", u=user_id, i=only)
    if not market_open():
        return filled
    for r in rows:
        try:
            q = quote(r["symbol"], r["expiry"], r["side"], r["strike"])
        except Exception:
            continue
        touch = _touch(q, r["action"])
        if touch <= 0 or (touch < r["limit_price"] if r["action"] == "SELL" else touch > r["limit_price"]):
            continue
        # A modify to a marketable price fills at the touch; a resting order the market came to, at its limit.
        px = touch if only else r["limit_price"]
        with _lock, db.tx(user_id) as c:
            _lock_account(c, user_id)
            n = c.run("UPDATE pending_orders SET status='filled', fill_price=:p, updated_at=now() "
                      "WHERE id=:i AND user_id=:u AND status='open'", p=px, i=r["id"], u=user_id)
            if n:  # still open: nobody cancelled it between the read and now
                _apply_trade(c, user_id, r["symbol"], r["expiry"], r["side"], r["strike"], r["action"], r["qty"],
                             px, r["lot_size"], r["reason"], r["note"], r["sl_mode"], r["limit_price"])
                filled.append(r["id"])
    return filled


def _session_over() -> bool:
    now = datetime.now(IST)
    return now.weekday() >= 5 or (now.hour, now.minute) >= (15, 30)


def has_pending(user_id: int) -> bool:
    with db.tx(user_id) as c:
        return bool(c.value("SELECT 1 FROM pending_orders WHERE user_id=:u AND status='open' LIMIT 1", u=user_id))


# ---------- monitor: stop loss + expiry ----------

def _exit_group_rows(user_id: int, symbol: str, expiry: str, reason: str, note: str,
                     price_override: dict | None = None) -> list[int]:
    """Closes every open leg of one symbol/expiry group; the note says why on each order."""
    with db.tx(user_id) as c:
        rows = _open_rows(c, user_id, symbol, expiry)
    # Price every leg first so a missing quote aborts before any leg is closed: the group
    # exits together or not at all.
    fills = []
    for r in rows:
        action = "BUY" if r["qty"] < 0 else "SELL"
        px, fill_note = (price_override or {}).get(r["id"]), None
        if px is None:
            px, fill_note = _fill_price(quote(symbol, expiry, r["side"], r["strike"]), action)
        fills.append((r, action, px, "; ".join(n for n in (note, fill_note) if n)))
    with _lock, db.tx(user_id) as c:
        _lock_account(c, user_id)
        for r, action, px, leg_note in fills:
            _apply_trade(c, user_id, symbol, expiry, r["side"], r["strike"], action, abs(r["qty"]), px,
                         r["lot_size"], reason, leg_note, r["sl_mode"], px)
        # The group is closed, so any open order still waiting on these contracts is moot.
        c.run("UPDATE pending_orders SET status='cancelled', updated_at=now() WHERE user_id=:u AND status='open'"
              " AND symbol=:s AND expiry=:e", u=user_id, s=symbol, e=expiry)
    return [r["id"] for r, *_ in fills]


def time_exit_date(expiry: str) -> str:
    """First day the position is closed for time: when fewer than TIME_EXIT_DTE days remain."""
    return str((pd.Timestamp(expiry) - timedelta(days=config.TIME_EXIT_DTE - 1)).date())


def run_checks(user_id: int) -> dict:
    """Settles expired contracts, then during market hours applies three group rules, in order:
    time exit (fewer than TIME_EXIT_DTE days left), profit target (PROFIT_TARGET_DECAY_PCT of the
    premium decayed) and group stop loss (any short leg hits its stop). Each closes the whole
    symbol/expiry group. Safe to call any time."""
    today = _today()
    exited, alerted, settled, timed, targeted = [], [], [], [], []
    with db.tx(user_id) as c:
        rows = _open_rows(c, user_id)

    expired = [r for r in rows if pd.Timestamp(r["expiry"]) < today]
    for r in expired:
        try:
            hist = data_fetch.fetch_price_history(f"{r['symbol']}.NS", 10)
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.get_level_values(0)
            closes = hist["Close"].dropna()
            spot = float(closes[closes.index <= pd.Timestamp(r["expiry"])].iloc[-1])
            intrinsic = max(0.0, spot - r["strike"]) if r["side"] == "CE" else max(0.0, r["strike"] - spot)
            _exit_rows(user_id, [r], "expiry", {r["id"]: round(intrinsic, 2)})
            settled.append(r["id"])
        except Exception:
            continue  # retry on the next pass

    if not market_open():
        return {"exited": exited, "alerted": alerted, "settled": settled, "timed": timed, "targeted": targeted}

    live = [r for r in rows if r not in expired]
    for (symbol, expiry), legs in _groups(live).items():
        # Rule 1: time exit. NSE stock options settle by physical delivery, and delivery margins
        # rise in the final days, so the whole group closes a week out instead of running to expiry.
        dte = (pd.Timestamp(expiry) - today).days
        if dte < config.TIME_EXIT_DTE:
            try:
                timed += _exit_group_rows(user_id, symbol, expiry, "time_exit",
                                          f"Time exit: {dte} day{'s' if dte != 1 else ''} to expiry, "
                                          f"closed to avoid physical delivery")
            except Exception:
                pass  # no quote yet; retry on the next pass
            continue

        # Rule 2: profit target. Once 90% of the premium collected has decayed, the last 10% is not
        # worth the gap risk of holding naked shorts, so the whole group is bought back.
        shorts = [r for r in legs if r["qty"] < 0]
        collected = sum(r["avg_price"] * -r["qty"] for r in shorts)
        if collected > 0:
            try:
                quotes = {r["id"]: quote(symbol, expiry, r["side"], r["strike"]) for r in shorts}
                # Cost to close: a limit at the ask. With no ask on any leg, no exit this pass.
                if any(q["ask"] <= 0 for q in quotes.values()):
                    raise ValueError("no ask")
                cost = {i: q["ask"] for i, q in quotes.items()}
                to_close = sum(cost[r["id"]] * -r["qty"] for r in shorts)
                decayed = (1 - to_close / collected) * 100
                if decayed >= config.PROFIT_TARGET_DECAY_PCT:
                    targeted += _exit_group_rows(
                        user_id, symbol, expiry, "target_exit",
                        f"Profit target: {decayed:.0f}% of ₹{collected:,.0f} premium decayed "
                        f"(target {config.PROFIT_TARGET_DECAY_PCT}%); all legs closed", cost)
                    continue
            except Exception:
                pass  # missing quote: the SL check below still runs; target retries next pass

        # Rule 3: group stop loss. The first short leg past its stop decides for the group.
        for r in legs:
            if r["qty"] >= 0 or r["sl_mode"] == "off" or r["sl_alert_at"]:
                continue
            if today < pd.Timestamp(r["sl_activates_on"]):
                continue
            try:
                q = quote(symbol, expiry, r["side"], r["strike"])
            except Exception:
                continue
            if not pricing.has_book(q["bid"], q["ask"]):
                continue  # no two-sided book: no fair price to judge the stop by; retry next pass
            # The stop judges the mid, not the ask: on a wide book the ask alone sits above the
            # entry (a sell fills at the bid) and would fire the stop with no move at all.
            fair = pricing.mid(q["bid"], q["ask"])
            if fair < r["sl_price"]:
                continue
            buyback = q["ask"]  # the exit itself is a limit at the ask, which fills at once
            trigger = (f"{r['strike']:g} {r['side']} mid {fair:.2f} (bid {q['bid']:.2f} / ask {buyback:.2f}, "
                       f"stop {r['sl_price']:.2f})")
            if r["sl_mode"] == "auto":
                try:
                    exited += _exit_group_rows(user_id, symbol, expiry, "sl_auto",
                                               f"Group stop loss: {trigger}; all legs closed",
                                               {r["id"]: buyback})
                except Exception:
                    pass  # a leg had no quote; retry on the next pass
            else:
                with db.tx(user_id) as c:
                    c.run("UPDATE positions SET sl_alert_at=now() WHERE id=:i AND user_id=:u", i=r["id"], u=user_id)
                alerted.append(r["id"])
            break
    return {"exited": exited, "alerted": alerted, "settled": settled, "timed": timed, "targeted": targeted}


# ---------- cached snapshot: the dashboard reads this, never live NSE ----------
# One snapshot per user in Redis (snap:positions:{user_id}). The worker re-prices every minute
# in market hours; the API re-prices right after a trade. With Redis down, reads price live.

def _snap_key(user_id: int) -> str:
    return f"snap:positions:{int(user_id)}"


def refresh_positions(user_id: int) -> dict:
    """Re-prices open positions from NSE and stores the result with its timestamp."""
    data = get_positions(user_id)
    data["updated_at"] = _now()
    cache.set_json(_snap_key(user_id), data)
    return data


def cached_positions(user_id: int) -> dict:
    return cache.get_json(_snap_key(user_id)) or refresh_positions(user_id)


def cached_account(user_id: int) -> dict:
    """Account figures from the cached snapshot; realised P&L and cash always read fresh from the DB."""
    snap = cached_positions(user_id)
    return {**get_account(user_id, _positions=snap["groups"]), "updated_at": snap["updated_at"]}


def has_open(user_id: int) -> bool:
    with db.tx(user_id) as c:
        return bool(c.value("SELECT 1 FROM positions WHERE user_id=:u AND status='open' LIMIT 1", u=user_id))


def _safe_user_ids() -> list[int]:
    try:
        return users.active_user_ids()
    except Exception:
        return []


def start_monitor() -> None:
    """One loop, every active user: stop-loss and time-exit checks, then a fresh positions
    snapshot. Every minute while NSE is open, every 15 minutes otherwise."""
    def loop():
        while True:
            for uid in _safe_user_ids():
                try:
                    if has_pending(uid):
                        match_pending(uid)
                    if has_open(uid):
                        run_checks(uid)
                    refresh_positions(uid)
                except Exception:
                    pass  # one user's failure never stops the others; next pass retries
            time.sleep(config.POSITIONS_REFRESH_MARKET_SECONDS if market_window()
                       else config.POSITIONS_REFRESH_OFF_SECONDS)

    threading.Thread(target=loop, daemon=True, name="virtual-sl-monitor").start()
