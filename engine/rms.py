"""Virtual-account risk management (issue #178), modelled on a broker's RMS and the exchange's
margin-shortfall penalty.

- `check(user_id)`, every monitor pass in market hours: records the day's peak shortfall, and once
  margin used reaches RMS_SQUAREOFF_PCT of account value (or value is at or below zero) cancels
  waiting orders, then squares off whole groups, largest margin first, until margin used is back
  under RMS_WARN_PCT. Each order RMS places is charged RMS_CHARGE ("Square-off charges"), the group
  costs XP_RMS_SQUAREOFF, and the order history says why.
- `apply_penalties(day)`, once the session is over: charges the day's peak shortfall at the
  exchange's rates (config.PENALTY_*), escalating for repeat shortfalls.
Charges reduce account value and return %: unlike capital grants, they are real trading costs.
"""

from datetime import date, datetime, timedelta

from . import config, db, pricing, progress, virtual
from .progress import IST


def _today_ist() -> date:
    return datetime.now(IST).date()


def _record_shortfall(user_id: int, acct: dict) -> None:
    short = acct["used_margin"] - acct["account_value"]
    if short <= 0 or not pricing.trading_day():  # the exchange only penalises trading days
        return
    with db.tx(user_id) as c:
        c.run("INSERT INTO margin_shortfalls (user_id, day, peak, required) VALUES (:u, :d, :p, :r) "
              "ON CONFLICT (user_id, day) DO UPDATE SET peak = GREATEST(margin_shortfalls.peak, EXCLUDED.peak), "
              "required = CASE WHEN EXCLUDED.peak > margin_shortfalls.peak THEN EXCLUDED.required "
              "ELSE margin_shortfalls.required END",
              u=user_id, d=_today_ist(), p=round(short, 2), r=round(acct["used_margin"], 2))


def _charge(c, user_id: int, kind: str, ref: str, amount: float, note: str) -> bool:
    return bool(c.value("INSERT INTO account_charges (user_id, kind, ref, amount, note) VALUES (:u, :k, :r, :a, :n) "
                        "ON CONFLICT (user_id, kind, ref) DO NOTHING RETURNING id",
                        u=user_id, k=kind, r=ref, a=round(amount, 2), n=note))


def check(user_id: int) -> dict:
    """One RMS pass. Square-off only runs while the market is open; outside it the account stays
    flagged (margin_status) and the next open squares it off."""
    acct = virtual.get_account(user_id)
    _record_shortfall(user_id, acct)
    if acct["margin_status"] != "squareoff" or not virtual.market_open():
        return {"status": acct["margin_status"], "cancelled": 0, "closed": []}
    stamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    why = (f"RMS square-off: margin used {acct['margin_used_pct']}% of account value"
           if acct["margin_used_pct"] is not None else "RMS square-off: account value at or below zero")
    # Waiting limit orders block margin and could reopen what RMS closes: cancel them first. Stop-loss
    # orders only reduce risk, so they stay (#183).
    with db.tx(user_id) as c:
        cancelled = c.run("UPDATE pending_orders SET status='cancelled', updated_at=now() "
                          "WHERE user_id=:u AND status='open' AND order_type='limit'", u=user_id)
    closed = []
    snap = virtual.get_positions(user_id)
    groups = sorted((g for g in snap["groups"] if g["margin"]), key=lambda g: -g["margin"]["total"])
    groups += [g for g in snap["groups"] if not g["margin"]]  # unpriced margin last
    for g in groups:
        acct = virtual.get_account(user_id)
        if acct["margin_status"] == "ok" or (acct["margin_used_pct"] is not None
                                             and acct["margin_used_pct"] < config.RMS_WARN_PCT):
            break
        try:
            ids = virtual._exit_group_rows(user_id, g["symbol"], g["expiry"], "rms_squareoff",
                                           f"{why}; whole group closed")
        except Exception:
            continue  # no quote for a leg: try the next group, retry this one next pass
        ref = f"{g['symbol']}:{g['expiry']}:{stamp}"
        with db.tx(user_id) as c:
            for i in ids:
                _charge(c, user_id, "rms_charge", f"{ref}:{i}", config.RMS_CHARGE,
                        f"Square-off charges: {g['symbol']} {g['expiry']}")
            progress._award(c, user_id, config.XP_RMS_SQUAREOFF, "rms_squareoff", ref)
        closed.append({"symbol": g["symbol"], "expiry": g["expiry"], "legs": len(ids)})
    return {"status": virtual.get_account(user_id)["margin_status"], "cancelled": cancelled, "closed": closed}


def penalty_rate(peak: float, required: float, streak: int, month_days: int) -> float:
    """The exchange's rate, % of the shortfall: 0.5% when small (under PENALTY_SMALL_RUPEES and under
    PENALTY_SMALL_SHARE_PCT of the margin required), else 1%; 5% for repeat shortfalls."""
    if streak > config.PENALTY_STREAK_DAYS or month_days > config.PENALTY_MONTH_DAYS:
        return config.PENALTY_REPEAT_PCT
    small = peak < config.PENALTY_SMALL_RUPEES and required > 0 and peak / required * 100 < config.PENALTY_SMALL_SHARE_PCT
    return config.PENALTY_LOW_PCT if small else config.PENALTY_PCT


def apply_penalties(user_id: int, day: date | None = None) -> dict | None:
    """Charges `day`'s peak shortfall once (idempotent). Returns the charge, or None."""
    day = day or _today_ist()
    with db.tx(user_id) as c:
        row = c.one("SELECT peak, required FROM margin_shortfalls WHERE user_id=:u AND day=:d", u=user_id, d=day)
        if not row:
            return None
        days = {date.fromisoformat(str(r["day"])[:10]) for r in c.all("SELECT day FROM margin_shortfalls WHERE user_id=:u AND day <= :d "
                                       "AND day > :d - 40", u=user_id, d=day)}
        streak, d = 0, day
        while d in days:
            streak, d = streak + 1, d - timedelta(days=1)
            while d.weekday() >= 5 and d not in days:  # weekends don't break a run of trading days
                d -= timedelta(days=1)
        month_days = sum(1 for x in days if (x.year, x.month) == (day.year, day.month))
        rate = penalty_rate(float(row["peak"]), float(row["required"]), streak, month_days)
        amount = float(row["peak"]) * rate / 100
        note = f"Margin shortfall penalty: {rate:g}% of ₹{float(row['peak']):,.0f} peak shortfall on {day}"
        if amount <= 0 or not _charge(c, user_id, "margin_penalty", str(day), amount, note):
            return None
    return {"day": str(day), "rate": rate, "amount": round(amount, 2)}


def charges(user_id: int, limit: int = 100) -> list[dict]:
    """The account's square-off charges and shortfall penalties, newest first."""
    with db.tx(user_id) as c:
        return c.all("SELECT kind, amount, note, created_at FROM account_charges WHERE user_id=:u "
                     "ORDER BY created_at DESC, id DESC LIMIT :n", u=user_id, n=limit)
