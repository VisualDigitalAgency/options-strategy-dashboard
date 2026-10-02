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

from . import cache, config, data_fetch, db, greeks_sr, permissions, pivots, pricing, progress, risk_rules, span, users

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
    """legs: [{side, strike, qty, price?}] signed. Returns SPAN + exposure on short legs, plus the
    premium paid for long legs (`price`, else `avg_price`), which a buyer pays up front (#137). With
    no short leg the premium is all a long position blocks."""
    legs = [l for l in legs if l["qty"] != 0]
    paid = round(sum(l["qty"] * float(l.get("price") or l.get("avg_price") or 0) for l in legs if l["qty"] > 0), 2)
    if not any(l["qty"] < 0 for l in legs):
        return {"span": 0.0, "exposure": 0.0, "premium_paid": paid, "total": paid}
    span.load(risk_rules.get_universe())
    sp = span.scan_risk_positions(symbol, pd.Timestamp(expiry).strftime("%Y%m%d"), legs)
    if sp is None:
        raise ValueError(f"{symbol} {expiry} contract not found in NSE SPAN file")
    pct = _exposure_pct(symbol)
    exposure = sum(spot * -l["qty"] * pct / 100 for l in legs if l["qty"] < 0)
    return {"span": sp, "exposure": round(exposure, 2), "premium_paid": paid, "total": round(sp + exposure + paid, 2)}


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
    if r["qty"] > 0 and r["sl_price"] is None:
        return "n/a"  # a long held before #137 has no stop of its own
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
        # Square-off charges and shortfall penalties (#178) are trading costs: they reduce value and return %.
        charges = c.value("SELECT COALESCE(SUM(amount),0) FROM account_charges WHERE user_id=:u", u=user_id)
    groups = _positions if _positions is not None else (get_positions(user_id)["groups"] if n_open else [])
    unrealized = sum(g["pnl"] for g in groups)
    used = sum(g["margin"]["total"] for g in groups if g["margin"]) + blocked
    value = acct["starting_capital"] + realized + unrealized - charges
    util = round(used / value * 100, 1) if value > 0 else None
    status = ("squareoff" if value <= 0 or util >= config.RMS_SQUAREOFF_PCT
              else "warning" if util >= config.RMS_WARN_PCT else "ok")
    return {
        "starting_capital": acct["starting_capital"], "created_at": acct["created_at"],
        "sl_mode_default": acct["sl_mode_default"],
        "realized_pnl": round(realized, 2), "unrealized_pnl": round(unrealized, 2),
        "account_value": round(value, 2), "used_margin": round(used, 2),
        "available_margin": round(value - used, 2),
        "return_pct": round((value / acct["starting_capital"] - 1) * 100, 2),
        "open_positions": n_open,
        "open_orders": n_pending, "blocked_margin": round(blocked, 2),
        "charges": round(charges, 2),
        # Margin used ÷ account value (None once value is at or below zero) and what RMS makes of it.
        "margin_used_pct": util, "margin_status": status,
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
            # A short's stop is its sale price from day SL_GRACE_DAYS; a long's is LONG_SL_PCT of what
            # was paid, live at once, and only acts while the group has no short (run_checks).
            sl = ({"mode": sl_mode, "price": price, "on": str((_today() + timedelta(days=config.SL_GRACE_DAYS)).date())}
                  if signed < 0 else
                  {"mode": sl_mode, "price": _long_stop(price), "on": str(_today().date())})
            pid = c.value(
                "INSERT INTO positions (user_id, symbol, expiry, side, strike, qty, avg_price, lot_size,"
                " sl_mode, sl_price, sl_activates_on, entry_delta) VALUES (:u,:s,:e,:sd,:k,:q,:p,:lot,:m,:sp,:on,:d)"
                " RETURNING id", u=user_id, s=symbol, e=expiry, sd=side, k=strike, q=signed, p=price, lot=lot,
                m=sl["mode"], sp=sl["price"], on=sl["on"], d=entry_delta if signed < 0 else None)
        else:
            new_qty = row["qty"] + signed
            avg = (row["avg_price"] * abs(row["qty"]) + price * qty) / abs(new_qty)
            # Adding to a short raises the collected premium, so the breakeven SL moves with it.
            sl_price = avg if new_qty < 0 else _long_stop(avg)
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
    impact = _margin_impact(user_id, symbol, expiry, existing, fills)
    return {
        "symbol": symbol, "expiry": expiry, "lot_size": lot, "fills": fills,
        "premium": round(premium, 2), **impact,
        "sl_mode_default": default_sl, "notes": sorted(notes), "market_open": market_open(),
        "waiting": waiting, "illiquid": illiquid,
        # Any rule blocks the order; the builder shows the reason (#137, #170, #178).
        "buy_rule": _buy_rule(user_id, existing, fills) or _strategy_rule(user_id, existing, fills)
        or _rms_rule(existing, fills, impact),
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
    before = [{"side": r["side"], "strike": r["strike"], "qty": r["qty"], "price": r["avg_price"]} for r in existing]
    after_legs = _after(before, fills)
    m_before = group_margin(symbol, expiry, before, spot)["total"]
    m_after = group_margin(symbol, expiry, after_legs, spot)
    change = round(m_after["total"] - m_before, 2)
    acct = get_account(user_id)
    available = acct["available_margin"]
    value = acct["account_value"]
    # Margin used ÷ account value once this order is in, for the RMS rule (#178).
    used_after = round((acct["used_margin"] + change) / value * 100, 1) if value > 0 else None
    return {"margin_after": m_after, "margin_change": change, "available_margin": available,
            "sufficient": change <= available, "margin_used_pct_after": used_after}


def _long_stop(price: float) -> float:
    return round(price * (100 - config.LONG_SL_PCT) / 100, 2)


def _after(before: list[dict], fills: list[dict]) -> list[dict]:
    """The group's legs once `fills` book: signed qty per contract, and for a long its average cost."""
    after = {(b["side"], b["strike"]): dict(b) for b in before}
    for f in fills:
        k = (f["side"], f["strike"])
        signed = f["qty"] if f["action"] == "BUY" else -f["qty"]
        a = after.setdefault(k, {"side": f["side"], "strike": f["strike"], "qty": 0, "price": 0.0})
        new = a["qty"] + signed
        if signed > 0 and new > 0:  # buying into a long (or flipping to one) adds cost at the fill
            held = max(a["qty"], 0)
            a["price"] = (a["price"] * held + f["price"] * (new - held)) / new
        a["qty"] = new
    return [a for a in after.values() if a["qty"] != 0]


def _buy_rule(user_id: int, existing: list[dict], fills: list[dict]) -> str | None:
    """Why this order's buy legs aren't allowed, or None (#137). With `hedges` (Level 6) any buy is
    fine. Without it, a long may only protect a sell in the same group: same option type, further
    out of the money than a short, and no more long than short on that side. An order that adds no
    long (buying back a short) is always fine, even if it leaves a hedge on its own."""
    before = {(r["side"], r["strike"]): r["qty"] for r in existing}
    after = {(l["side"], l["strike"]): l["qty"] for l in _after(
        [{"side": r["side"], "strike": r["strike"], "qty": r["qty"], "price": r["avg_price"]} for r in existing], fills)}
    if not any(q > max(before.get(k, 0), 0) for k, q in after.items()):
        return None
    with db.tx() as c:
        role = c.value("SELECT role FROM users WHERE id=:u", u=user_id)
    if "hedges" in permissions.user_features(user_id, role):
        return None
    legs = _after([{"side": r["side"], "strike": r["strike"], "qty": r["qty"], "price": r["avg_price"]}
                   for r in existing], fills)
    for side in ("CE", "PE"):
        longs = [l for l in legs if l["side"] == side and l["qty"] > 0]
        shorts = [l for l in legs if l["side"] == side and l["qty"] < 0]
        if not longs:
            continue
        if not shorts:
            return (f"Buying a {side} on its own unlocks at Level 6. Until then a bought leg must protect "
                    f"a sold {side} in the same order or position")
        nearest = min(s["strike"] for s in shorts) if side == "CE" else max(s["strike"] for s in shorts)
        bad = [l for l in longs if (l["strike"] <= nearest if side == "CE" else l["strike"] >= nearest)]
        if bad:
            return (f"The bought {bad[0]['strike']:g} {side} must be further out of the money than the sold "
                    f"{nearest:g} {side} to protect it (any strike unlocks at Level 6)")
        if sum(l["qty"] for l in longs) > -sum(s["qty"] for s in shorts):
            return f"Buy no more {side} than you sell; more unlocks at Level 6"
    return None


def _strategy_rule(user_id: int, existing: list[dict], fills: list[dict]) -> str | None:
    """Why this order's sells aren't allowed at the user's level, or None (#170). The course runs in
    ascending margin: spreads and condors first, a single unprotected sale from NAKED_LEVEL, both
    sides unprotected (a strangle) from STRANGLE_LEVEL. A sold leg counts as protected when the
    group holds as many bought lots of the same type further out of the money. Only orders that add
    a sale are checked, so closing or reducing is always allowed. The owner and Pro accounts (the
    screener suggests strangles) are not gated; auto-trade books through execute_order, not here."""
    before = {(r["side"], r["strike"]): r["qty"] for r in existing}
    legs = _after([{"side": r["side"], "strike": r["strike"], "qty": r["qty"], "price": r["avg_price"]}
                   for r in existing], fills)
    if not any(l["qty"] < min(before.get((l["side"], l["strike"]), 0), 0) for l in legs):
        return None
    with db.tx() as c:
        role = c.value("SELECT role FROM users WHERE id=:u", u=user_id)
    with db.tx(user_id) as c:  # user_levels is per-user under RLS
        level = c.value("SELECT level FROM user_levels WHERE user_id=:u", u=user_id) or 1
    if role == "owner" or level >= config.STRANGLE_LEVEL or "screener" in permissions.user_features(user_id, role):
        return None
    naked = []
    for side in ("CE", "PE"):
        shorts = [l for l in legs if l["side"] == side and l["qty"] < 0]
        if not shorts:
            continue
        nearest = min(s["strike"] for s in shorts) if side == "CE" else max(s["strike"] for s in shorts)
        cover = sum(l["qty"] for l in legs if l["side"] == side and l["qty"] > 0
                    and (l["strike"] > nearest if side == "CE" else l["strike"] < nearest))
        if cover < -sum(s["qty"] for s in shorts):
            naked.append(side)
    if naked and level < config.NAKED_LEVEL:
        return (f"Selling a {naked[0]} without a bought {naked[0]} further out behind it unlocks at Level "
                f"{config.NAKED_LEVEL}. Until then, trade credit spreads and iron condors")
    if len(naked) == 2:
        return (f"Selling both a call and a put without protection (a strangle) unlocks at Level "
                f"{config.STRANGLE_LEVEL}. Protect one side with a bought option")
    return None


def _rms_rule(existing: list[dict], fills: list[dict], impact: dict) -> str | None:
    """An order that adds a sale is refused when it would leave margin used at RMS_WARN_PCT of
    account value or more (or value is at or below zero), so a trade can't walk the account into
    an RMS square-off. Closing or reducing is always allowed (#178)."""
    before = {(r["side"], r["strike"]): r["qty"] for r in existing}
    legs = _after([{"side": r["side"], "strike": r["strike"], "qty": r["qty"], "price": r["avg_price"]}
                   for r in existing], fills)
    if not any(l["qty"] < min(before.get((l["side"], l["strike"]), 0), 0) for l in legs):
        return None
    pct = impact["margin_used_pct_after"]
    if pct is not None and pct < config.RMS_WARN_PCT:
        return None
    used = f"{pct:g}% of your account" if pct is not None else "more than your account"
    return (f"This would bring margin used to {used} (limit {config.RMS_WARN_PCT}%). Trade smaller or "
            f"close a position first; at {config.RMS_SQUAREOFF_PCT}% positions are squared off")


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
    if p["buy_rule"]:
        raise ValueError(p["buy_rule"])
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
            # An untriggered stop isn't an exit yet; it is replaced by this one (cancelled below).
            c.run("UPDATE pending_orders SET status='cancelled', updated_at=now() WHERE user_id=:u AND status='open'"
                  " AND order_type <> 'limit' AND triggered_at IS NULL AND symbol=:s AND expiry=:e AND side=:sd"
                  " AND strike=:k AND action=:a", **contract)
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


def reset(user_id: int) -> dict:
    """Deletes every order and position and restarts the virtual account with its base capital
    (₹2 lakh for accounts made since #47) plus every capital grant earned. The amount is never the
    caller's choice: capital only grows by completing tasks (engine/capital.py)."""
    with _lock, db.tx(user_id) as c:
        _lock_account(c, user_id)
        c.run("DELETE FROM orders WHERE user_id=:u", u=user_id)
        c.run("DELETE FROM pending_orders WHERE user_id=:u", u=user_id)
        c.run("DELETE FROM positions WHERE user_id=:u", u=user_id)
        c.run("UPDATE accounts SET starting_capital = base_capital + (SELECT COALESCE(SUM(amount), 0) "
              "FROM capital_grants WHERE user_id=:u), created_at=now() WHERE user_id=:u", u=user_id)
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
                     " blocked_margin, valid_until, created_at, order_type, trigger_price, triggered_at FROM pending_orders"
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
        if r["order_type"] != "limit" and r["triggered_at"] is None:
            if not _triggered(r, q):
                continue  # a stop waits for its trigger (#183)
            if r["order_type"] == "slm":
                if _fill_slm(user_id, r, q):
                    filled.append(r["id"])
                continue
            with db.tx(user_id) as c:  # SL: from now on an ordinary limit order
                c.run("UPDATE pending_orders SET triggered_at=now(), updated_at=now() WHERE id=:i AND user_id=:u",
                      i=r["id"], u=user_id)
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


def _triggered(r: dict, q: dict) -> bool:
    """A stop triggers when the traded price reaches it: a BUY stop (protecting a sold leg) at or
    above the trigger, a SELL stop (protecting a bought leg) at or below. The price is the mid of a
    two-sided book, as for the group stop, else the last trade."""
    px = pricing.mid(q["bid"], q["ask"]) if pricing.has_book(q["bid"], q["ask"]) else q["ltp"]
    if not px or px <= 0:
        return False
    return px >= r["trigger_price"] if r["action"] == "BUY" else px <= r["trigger_price"]


def _fill_slm(user_id: int, r: dict, q: dict) -> bool:
    """SL-M: once triggered, fills at once at the touch (ask for a BUY, bid for a SELL). With no
    touch on that side it waits for the next pass."""
    px = _touch(q, r["action"])
    if px <= 0:
        return False
    with _lock, db.tx(user_id) as c:
        _lock_account(c, user_id)
        n = c.run("UPDATE pending_orders SET status='filled', fill_price=:p, triggered_at=now(), updated_at=now() "
                  "WHERE id=:i AND user_id=:u AND status='open'", p=px, i=r["id"], u=user_id)
        if not n:
            return False
        held = c.value("SELECT qty FROM positions WHERE user_id=:u AND symbol=:s AND expiry=:e AND side=:sd "
                       "AND strike=:k AND status='open'", u=user_id, s=r["symbol"], e=r["expiry"], sd=r["side"], k=r["strike"])
        qty = min(r["qty"], abs(held or 0))  # never past flat: the leg may have shrunk since
        if qty <= 0:
            c.run("UPDATE pending_orders SET status='cancelled' WHERE id=:i AND user_id=:u", i=r["id"], u=user_id)
            return False
        _apply_trade(c, user_id, r["symbol"], r["expiry"], r["side"], r["strike"], r["action"], qty, px,
                     r["lot_size"], "sl_order", f"SL-M triggered at {r['trigger_price']:g}; filled at {px:g}",
                     r["sl_mode"], px)
    return True


def stop_contracts(user_id: int) -> set[tuple]:
    """(symbol, expiry, side, strike) of legs protected by the user's own stop order: the day-15
    group stop leaves these to it (#183)."""
    with db.tx(user_id) as c:
        rows = c.all("SELECT symbol, expiry, side, strike FROM pending_orders WHERE user_id=:u AND status='open' "
                     "AND order_type <> 'limit'", u=user_id)
    return {(r["symbol"], str(r["expiry"]), r["side"], float(r["strike"])) for r in rows}


def place_stop(user_id: int, position_id: int, trigger: float, order_type: str = "slm",
               limit: float | None = None) -> dict:
    """A stop-loss order to exit one open leg (#183): SL-M (trigger, then market) or SL (trigger, then
    a limit). A sold leg gets a BUY stop above the price; a bought leg a SELL stop below it. One stop
    per leg, for its whole quantity; it lasts until the leg's expiry and is cancelled when the leg
    closes any other way. While it is open, the day-15 group stop leaves this leg to it."""
    if order_type not in ("sl", "slm"):
        raise ValueError("Stop type must be SL or SL-M")
    trigger = tick(trigger)
    if trigger <= 0:
        raise ValueError("Trigger price must be above zero")
    with db.tx(user_id) as c:
        r = c.one("SELECT * FROM positions WHERE id=:i AND user_id=:u AND status='open'", i=position_id, u=user_id)
        if r is None:
            raise ValueError("Position not found or already closed")
        if c.value("SELECT 1 FROM pending_orders WHERE user_id=:u AND status='open' AND order_type <> 'limit' "
                   "AND symbol=:s AND expiry=:e AND side=:sd AND strike=:k", u=user_id, s=r["symbol"], e=r["expiry"],
                   sd=r["side"], k=r["strike"]):
            raise ValueError("This leg already has a stop-loss order; cancel it to set a new one")
    action = "BUY" if r["qty"] < 0 else "SELL"
    q = quote(r["symbol"], r["expiry"], r["side"], r["strike"])
    now_px = pricing.mid(q["bid"], q["ask"]) if pricing.has_book(q["bid"], q["ask"]) else q["ltp"]
    if now_px and (trigger <= now_px if action == "BUY" else trigger >= now_px):
        side = "above" if action == "BUY" else "below"
        raise ValueError(f"The trigger must be {side} the current price ({now_px:g}) for a {'sold' if action == 'BUY' else 'bought'} leg")
    if order_type == "sl":
        if limit is None:
            raise ValueError("An SL order needs a limit price")
        limit = tick(limit)
        if limit <= 0 or (limit < trigger if action == "BUY" else limit > trigger):
            raise ValueError(f"The limit must be {'at or above' if action == 'BUY' else 'at or below'} the trigger")
    else:
        limit = trigger  # SL-M fills at market; the limit column holds the trigger for display only
    with db.tx(user_id) as c:
        oid = c.value(
            "INSERT INTO pending_orders (user_id, symbol, expiry, side, strike, action, qty, lot_size, limit_price,"
            " reason, note, sl_mode, valid_until, order_type, trigger_price) VALUES (:u,:s,:e,:sd,:k,:a,:q,:lot,:lim,"
            " 'sl_order', :n, :m, :v, :t, :tr) RETURNING id",
            u=user_id, s=r["symbol"], e=r["expiry"], sd=r["side"], k=r["strike"], a=action, q=abs(r["qty"]),
            lot=r["lot_size"], lim=limit, n=f"{order_type.upper().replace('SLM', 'SL-M')} trigger {trigger:g}",
            m=r["sl_mode"], v=str(r["expiry"]), t=order_type, tr=trigger)
    return {"order_id": oid, "action": action, "trigger": trigger, "limit": limit if order_type == "sl" else None}


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
    stops = stop_contracts(user_id)  # legs with the user's own stop order: the group stop leaves them to it
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
            if (symbol, str(expiry), r["side"], float(r["strike"])) in stops:
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

        # Rule 4 (#137): with no short left to protect, a bought leg is a bet on its own; it closes
        # once its value falls LONG_SL_PCT below what was paid, judged on the mid, sold at the bid.
        if shorts:
            continue
        for r in legs:
            if r["qty"] <= 0 or r["sl_price"] is None or r["sl_mode"] == "off" or r["sl_alert_at"]:
                continue
            if (symbol, str(expiry), r["side"], float(r["strike"])) in stops:
                continue
            try:
                q = quote(symbol, expiry, r["side"], r["strike"])
            except Exception:
                continue
            if not pricing.has_book(q["bid"], q["ask"]):
                continue
            fair = pricing.mid(q["bid"], q["ask"])
            if fair > r["sl_price"]:
                continue
            trigger = (f"{r['strike']:g} {r['side']} mid {fair:.2f} (bid {q['bid']:.2f}), "
                       f"stop {r['sl_price']:.2f} = {config.LONG_SL_PCT}% below the {r['avg_price']:.2f} paid")
            if r["sl_mode"] == "auto":
                try:
                    exited += _exit_group_rows(user_id, symbol, expiry, "sl_auto",
                                               f"Long stop loss: {trigger}; all legs closed", {r["id"]: q["bid"]})
                except Exception:
                    pass
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
                    from . import rms  # rms builds on this module
                    if has_open(uid) or has_pending(uid):
                        rms.check(uid)  # margin shortfall: record it, square off at the RMS limit (#178)
                    if _session_over():
                        rms.apply_penalties(uid)  # once per day; a repeat call is a no-op
                    refresh_positions(uid)
                except Exception:
                    pass  # one user's failure never stops the others; next pass retries
            time.sleep(config.POSITIONS_REFRESH_MARKET_SECONDS if market_window()
                       else config.POSITIONS_REFRESH_OFF_SECONDS)

    threading.Thread(target=loop, daemon=True, name="virtual-sl-monitor").start()
