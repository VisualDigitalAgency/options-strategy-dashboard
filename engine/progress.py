"""Learning-path progress (issue #122, part of #120): trade log, XP and levels.

Every closed virtual position is copied into `trade_results` when it closes (record_close, called
from virtual._close_row inside the same transaction), and scored into the append-only `xp_ledger`:
discipline earns XP, breaking rules costs it, and profit only adds a capped bonus. Lesson passes
(#124) add XP too.

A user leaves level n for n+1 when all three hold (evaluate):
  - total XP >= 100 * n^2
  - at least LEVEL_MIN_DAYS[n] days at level n
  - level n's gate, measured on legs closed since the later of reaching the level and the last
    virtual-account reset (so a reset restarts the gate but never takes XP away).
Levels only go up, one step per evaluation. Gates for levels 6+ need data the app doesn't record
yet (Nifty-wide volatility, the Adjustments course, mentoring, the final assessment), so they read
as "not available yet" and nobody passes them until those land.

A "trade" here is one closed leg: a short strangle is two.
"""

from datetime import datetime, timedelta, timezone

from . import config, db

IST = timezone(timedelta(hours=5, minutes=30))
MAX_LEVEL = 10
UNAVAILABLE = "Not available yet"


def xp_needed(level: int) -> int:
    """Total XP needed to leave `level`."""
    return 100 * level * level


# ---------- recording ----------

def _award(c, user_id: int, points: int, reason: str, ref: str) -> None:
    if points:
        c.run("INSERT INTO xp_ledger (user_id, points, reason, ref) VALUES (:u, :p, :r, :f) "
              "ON CONFLICT (user_id, reason, ref) DO NOTHING", u=user_id, p=points, r=reason, f=ref)


def record_close(c, user_id: int, pid: int, exit_reason: str) -> None:
    """Called inside the transaction that just closed position `pid`: logs it and scores it."""
    r = c.one("SELECT p.*, a.starting_capital FROM positions p JOIN accounts a ON a.user_id = p.user_id "
              "WHERE p.id=:i AND p.user_id=:u", i=pid, u=user_id)
    # At close the row's qty is 0, so read the opening side and size from its orders (the closing
    # order is written after this runs).
    opening = c.one("SELECT action FROM orders WHERE position_id=:i AND user_id=:u ORDER BY id LIMIT 1", i=pid, u=user_id)
    short = bool(opening and opening["action"] == "SELL")
    qty = c.value("SELECT COALESCE(SUM(qty), 0) FROM orders WHERE position_id=:i AND user_id=:u AND action=:a",
                  i=pid, u=user_id, a=opening["action"] if opening else "SELL")
    trade_id = c.value(
        "INSERT INTO trade_results (user_id, position_id, symbol, expiry, side, strike, short, lots, avg_price, exit_price,"
        " realized_pnl, capital, opened_at, exit_reason, had_sl, entry_delta) VALUES"
        " (:u,:i,:s,:e,:sd,:k,:sh,:l,:ap,:xp,:pnl,:cap,:o,:why,:sl,:d) RETURNING id",
        u=user_id, i=pid, s=r["symbol"], e=r["expiry"], sd=r["side"], k=r["strike"], sh=short,
        l=max(1, round(qty / r["lot_size"])), ap=r["avg_price"], xp=r["exit_price"],
        pnl=r["realized_pnl"], cap=r["starting_capital"], o=r["opened_at"], why=exit_reason,
        sl=r["sl_mode"] != "off", d=r["entry_delta"])
    held = c.value("SELECT EXTRACT(EPOCH FROM (now() - :o)) / 60", o=r["opened_at"])
    if not short or held < config.QUICK_FLIP_MINUTES:
        return
    ref = f"trade:{trade_id}"
    if r["sl_mode"] == "off":
        _award(c, user_id, config.XP_NO_SL, "no_sl", ref)
    delta = r["entry_delta"]
    if delta is not None and float(delta) >= config.DELTA_MAX_ABS:
        _award(c, user_id, config.XP_HIGH_DELTA, "high_delta", ref)
    if r["sl_mode"] != "off" and delta is not None and float(delta) < config.DELTA_MAX_ABS:
        _award(c, user_id, config.XP_TRADE_OK, "trade_ok", ref)
    if float(r["realized_pnl"]) > 0:
        month = datetime.now(IST).strftime("%Y-%m")
        so_far = c.value("SELECT COALESCE(SUM(points), 0) FROM xp_ledger WHERE user_id=:u AND reason='profit_bonus' "
                         "AND to_char(ts AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM') = :m", u=user_id, m=month)
        _award(c, user_id, min(config.XP_PROFIT_BONUS, config.XP_PROFIT_CAP - so_far), "profit_bonus", ref)


def _sync_lessons(c, user_id: int) -> None:
    for row in c.all("SELECT slug FROM lesson_progress WHERE user_id=:u AND passed_at IS NOT NULL", u=user_id):
        _award(c, user_id, config.XP_LESSON, "lesson", f"lesson:{row['slug']}")


# ---------- metrics ----------

def metrics(trades: list[dict]) -> dict:
    """Return %, max drawdown % (on the equity curve of booked P&L), return ÷ drawdown, win rate.
    Drawdown has a 1% floor in the ratio so a clean record doesn't divide by zero."""
    if not trades:
        return {"trades": 0, "pnl": 0.0, "return_pct": 0.0, "max_dd_pct": 0.0, "ret_dd": 0.0, "win_rate": 0.0}
    capital = float(trades[0]["capital"])
    eq = peak = capital
    dd = 0.0
    for t in trades:
        eq += float(t["realized_pnl"])
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak * 100 if peak > 0 else 0.0)
    pnl = sum(float(t["realized_pnl"]) for t in trades)
    ret = pnl / capital * 100
    wins = sum(1 for t in trades if float(t["realized_pnl"]) > 0)
    return {"trades": len(trades), "pnl": round(pnl, 2), "return_pct": round(ret, 2), "max_dd_pct": round(dd, 2),
            "ret_dd": round(ret / max(dd, 1.0), 2), "win_rate": round(wins / len(trades) * 100, 1)}


def _monthly(trades: list[dict]) -> dict:
    out = {}
    for t in trades:
        out.setdefault(t["month"], []).append(t)
    return {m: sum(float(t["realized_pnl"]) for t in ts) for m, ts in out.items()}


def _profitable_streak(trades: list[dict], now: datetime) -> int:
    """Complete calendar months in a row, ending last month, with booked profit > 0."""
    by = _monthly(trades)
    streak, d = 0, now.replace(day=1) - timedelta(days=1)
    while by.get(d.strftime("%Y-%m"), 0) > 0:
        streak += 1
        d = d.replace(day=1) - timedelta(days=1)
    return streak


# ---------- gates ----------

def _gate(level: int, trades: list[dict], c, user_id: int, now: datetime) -> list[dict]:
    """The checks for leaving `level`, each {label, ok, value}."""
    shorts = [t for t in trades if t["short"]]
    m = metrics(trades)
    if level == 1:
        from . import lessons
        need = {l["slug"] for l in lessons.list_lessons() if l["level"] == 1}
        done = {r["slug"] for r in c.all("SELECT slug FROM lesson_progress WHERE user_id=:u AND passed_at IS NOT NULL",
                                         u=user_id)}
        return [{"label": "Pass every Level 1 lesson quiz", "ok": need <= done, "value": f"{len(need & done)}/{len(need)}"},
                {"label": "Close 5 trades", "ok": m["trades"] >= 5, "value": m["trades"]}]
    if level == 2:
        no_sl = sum(1 for t in shorts if not t["had_sl"])
        return [{"label": "Close 15 trades", "ok": m["trades"] >= 15, "value": m["trades"]},
                {"label": "Every short leg had its stop-loss on", "ok": no_sl == 0, "value": f"{no_sl} without"}]
    if level == 3:
        return [{"label": "Close 30 trades", "ok": m["trades"] >= 30, "value": m["trades"]},
                {"label": "Win rate 60% or more", "ok": m["win_rate"] >= 60, "value": f"{m['win_rate']}%"},
                {"label": "Max drawdown 15% or less", "ok": m["trades"] > 0 and m["max_dd_pct"] <= 15,
                 "value": f"{m['max_dd_pct']}%"}]
    if level == 4:
        high = sum(1 for t in shorts if t["entry_delta"] is not None and float(t["entry_delta"]) >= config.DELTA_MAX_ABS)
        streak = _profitable_streak(trades, now)
        return [{"label": "3 profitable months in a row", "ok": streak >= 3, "value": streak},
                {"label": "No short leg sold at delta 0.15 or more", "ok": high == 0, "value": f"{high} over"}]
    if level == 5:
        recent = [t for t in trades if float(t["age_days"]) <= 90]
        r = metrics(recent)
        return [{"label": "Return ÷ drawdown 1.5 or more over 3 months", "ok": r["trades"] > 0 and r["ret_dd"] >= 1.5,
                 "value": r["ret_dd"]},
                {"label": "Close 60 trades", "ok": m["trades"] >= 60, "value": m["trades"]}]
    return [{"label": UNAVAILABLE, "ok": False, "value": None}]


# ---------- status and evaluation ----------

def _level_row(c, user_id: int) -> dict:
    # Level 1 starts when the account was created, not when progress is first looked at, so trades
    # closed before then still count towards the first gate.
    c.run("INSERT INTO user_levels (user_id, level_since) SELECT id, created_at FROM users WHERE id=:u "
          "ON CONFLICT (user_id) DO NOTHING", u=user_id)
    return c.one("SELECT level, level_since FROM user_levels WHERE user_id=:u", u=user_id)


def _snapshot(c, user_id: int, now: datetime) -> dict:
    _level_row(c, user_id)
    # Dates are worked out in SQL: the gate starts at the later of reaching the level and the last reset.
    lv = c.one("SELECT l.level, l.level_since, GREATEST(l.level_since, a.created_at) AS gate_since, "
               "floor(EXTRACT(EPOCH FROM (CAST(:n AS timestamptz) - l.level_since)) / 86400)::int AS days "
               "FROM user_levels l JOIN accounts a ON a.user_id = l.user_id WHERE l.user_id=:u", u=user_id, n=now)
    level, since, start, days = lv["level"], lv["level_since"], lv["gate_since"], lv["days"]
    xp = c.value("SELECT COALESCE(SUM(points), 0) FROM xp_ledger WHERE user_id=:u", u=user_id)
    trades = c.all("SELECT *, to_char(closed_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM') AS month, "
                   "EXTRACT(EPOCH FROM (CAST(:n AS timestamptz) - closed_at)) / 86400 AS age_days FROM trade_results "
                   "WHERE user_id=:u AND closed_at >= (SELECT GREATEST(l.level_since, a.created_at) FROM user_levels l "
                   "JOIN accounts a ON a.user_id = l.user_id WHERE l.user_id=:u) ORDER BY closed_at, id", u=user_id, n=now)
    nxt = None
    if level < MAX_LEVEL:
        checks = [{"label": f"{xp_needed(level):,} XP", "ok": xp >= xp_needed(level), "value": xp},
                  {"label": f"{config.LEVEL_MIN_DAYS[level]} days at this level",
                   "ok": days >= config.LEVEL_MIN_DAYS[level], "value": days},
                  *_gate(level, trades, c, user_id, now)]
        nxt = {"level": level + 1, "title": config.LEVEL_TITLES[level + 1], "xp_needed": xp_needed(level),
               "checks": checks, "ready": all(ch["ok"] for ch in checks)}
    return {"level": level, "title": config.LEVEL_TITLES[level], "level_since": since, "gate_since": start,
            "xp": xp, "next": nxt, "metrics": metrics(trades)}


def evaluate(user_id: int, _now: datetime | None = None) -> dict:
    """Scores any newly passed lessons, moves up one level if every check passes, and returns the
    user's progress: level, XP, the next level's checks with live values, and gate metrics."""
    from . import auth
    # `_now` is for tests only; the RPC guard never lets a client set an underscored parameter.
    now = _now or datetime.now(timezone.utc)
    with db.tx(user_id) as c:
        _sync_lessons(c, user_id)
        snap = _snapshot(c, user_id, now)
        if snap["next"] and snap["next"]["ready"]:
            c.run("UPDATE user_levels SET level=level+1, level_since=:n WHERE user_id=:u", n=now, u=user_id)
            up = snap["next"]["level"]
            snap = _snapshot(c, user_id, now)
        else:
            up = None
    if up:
        auth.audit("level_up", actor_id=None, target_user_id=user_id, level=up)
    return {**snap, "leveled_up": up}


def history(user_id: int, limit: int = 50) -> list[dict]:
    """The newest XP ledger entries: points, reason and what they were for."""
    with db.tx(user_id) as c:
        return c.all("SELECT ts, points, reason, ref FROM xp_ledger WHERE user_id=:u ORDER BY id DESC LIMIT :n",
                     u=user_id, n=limit)


def evaluate_all() -> int:
    """Nightly pass for every active user. Returns how many levelled up."""
    from . import users
    ups = 0
    for uid in users.active_user_ids():
        try:
            ups += bool(evaluate(uid)["leveled_up"])
        except Exception:  # one user's failure never stops the rest
            import logging
            logging.getLogger("theta.progress").exception("progress evaluation failed for user %s", uid)
    return ups
