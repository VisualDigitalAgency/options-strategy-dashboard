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
Levels only go up, one step per evaluation. From Level 6 the gates also look at the track record
since the last reset (months profitable, 12-month drawdown), Nifty's monthly swings (engine/nifty),
the finished leaderboards, the people a user invited, and, to reach Level 10, the owner's sign-off
on a final assessment (#146).

A "trade" here is one closed leg: a short strangle is two.
"""

from datetime import datetime, timedelta, timezone

from . import config, db, nifty

IST = timezone(timedelta(hours=5, minutes=30))
MAX_LEVEL = 10
UNAVAILABLE = "Not available yet"
FINAL_LABEL = "Final assessment approved by the owner"


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

def _lessons_check(c, user_id: int, level: int, label: str) -> dict:
    from . import lessons
    need = {l["slug"] for l in lessons.list_lessons() if l["level"] == level}
    done = {r["slug"] for r in c.all("SELECT slug FROM lesson_progress WHERE user_id=:u AND passed_at IS NOT NULL",
                                     u=user_id)}
    return {"label": label, "ok": bool(need) and need <= done, "value": f"{len(need & done)}/{len(need)}"}


def _last_months(now: datetime, n: int) -> list[str]:
    """The n complete calendar months (IST) ending last month, newest first."""
    out, d = [], now.astimezone(IST).replace(day=1) - timedelta(days=1)
    for _ in range(n):
        out.append(d.strftime("%Y-%m"))
        d = d.replace(day=1) - timedelta(days=1)
    return out


def _profit_months(history: list[dict], now: datetime, need: int, of: int) -> dict:
    window = set(_last_months(now, of))
    by = _monthly([t for t in history if t["month"] in window])
    won = sum(1 for v in by.values() if v > 0)
    return {"label": f"{need} profitable months out of the last {of}", "ok": won >= need, "value": f"{won}/{of}"}


def _window_dd(history: list[dict], now: datetime, months: int, limit: float) -> dict:
    window = set(_last_months(now, months)) | {now.astimezone(IST).strftime("%Y-%m")}
    m = metrics([t for t in history if t["month"] in window])
    return {"label": f"Max drawdown {limit:g}% or less over {months} months", "ok": m["trades"] > 0 and m["max_dd_pct"] <= limit,
            "value": f"{m['max_dd_pct']}%"}


def _breached(t: dict) -> bool:
    """A short leg broke the stop-loss discipline: closed with its stop off, or left open more than a
    day after its stop alert fired. A stop that fired and closed the trade is discipline, not a breach."""
    if not t["had_sl"]:
        return True
    return t.get("alert_days") is not None and float(t["alert_days"]) > 1


def _volatile_month(trades: list[dict]) -> dict:
    label = f"A volatile month (Nifty swing {config.VOLATILE_SWING_PCT:g}% or more) with no stop-loss broken"
    ranges = nifty.monthly()
    if not ranges:
        return {"label": label, "ok": False, "value": "Nifty data not loaded yet"}
    best = None
    for month in sorted({t["month"] for t in trades}, reverse=True):
        swing = ranges.get(month, {}).get("swing_pct", 0)
        shorts = [t for t in trades if t["month"] == month and t["short"]]
        if swing >= config.VOLATILE_SWING_PCT and shorts and not any(_breached(t) for t in shorts):
            best = f"{month} (Nifty {swing:g}%)"
            break
    return {"label": label, "ok": best is not None, "value": best or "None yet"}


def _top_boards(c, user_id: int) -> dict:
    """Finished monthly boards where the user ranked in the top L8_TOP_PCT% of their band. The Rising
    band (Levels 1-3) doesn't count: the gate is about competing with Level 4+ players."""
    rows = c.all("SELECT e.month, e.rank, (SELECT count(*) FROM leaderboard_entries b WHERE b.month = e.month "
                 "AND b.band = e.band) AS size FROM leaderboard_entries e WHERE e.user_id=:u AND e.band <> '1-3'", u=user_id)
    top = sum(1 for r in rows if r["rank"] <= max(1, -(-r["size"] * config.L8_TOP_PCT // 100)))
    return {"label": f"Top {config.L8_TOP_PCT}% of your leaderboard band in {config.L8_TOP_MONTHS} months",
            "ok": top >= config.L8_TOP_MONTHS, "value": top}


def _mentees(c, user_id: int) -> dict:
    """People this user invited (#134) who reached MENTEE_LEVEL. Each level is read in that user's own
    transaction (user_levels is per-user under RLS)."""
    invited = [r["id"] for r in c.all("SELECT id FROM users WHERE referred_by=:u AND status = 'active'", u=user_id)]
    got = 0
    for i in invited:
        with db.tx(i) as ci:
            got += (ci.value("SELECT level FROM user_levels WHERE user_id=:u", u=i) or 1) >= config.MENTEE_LEVEL
    return {"label": f"{config.L9_MENTEES} people you invited reached Level {config.MENTEE_LEVEL}",
            "ok": got >= config.L9_MENTEES, "value": got}


def _track_record(history: list[dict]) -> dict:
    months = int(float(history[0]["age_days"]) // 30.44) if history else 0
    return {"label": f"A track record of {config.L9_TRACK_MONTHS} months or more", "ok": months >= config.L9_TRACK_MONTHS,
            "value": f"{months} months"}


def _gate(level: int, trades: list[dict], c, user_id: int, now: datetime, history: list[dict] | None = None) -> list[dict]:
    """The checks for leaving `level`, each {label, ok, value}. `trades` are those since reaching the
    level; `history` is everything since the last reset, for the longer windows of Levels 7+."""
    history = trades if history is None else history
    shorts = [t for t in trades if t["short"]]
    m = metrics(trades)
    if level == 1:
        return [_lessons_check(c, user_id, 1, "Pass every Level 1 lesson quiz"),
                {"label": "Close 5 trades at this level", "ok": m["trades"] >= 5, "value": m["trades"]}]
    if level == 2:
        no_sl = sum(1 for t in shorts if not t["had_sl"])
        return [{"label": "Close 15 trades at this level", "ok": m["trades"] >= 15, "value": m["trades"]},
                {"label": "Every short leg had its stop-loss on", "ok": no_sl == 0, "value": f"{no_sl} without"}]
    if level == 3:
        return [{"label": "Close 30 trades at this level", "ok": m["trades"] >= 30, "value": m["trades"]},
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
                {"label": "Close 60 trades at this level", "ok": m["trades"] >= 60, "value": m["trades"]}]
    if level == 6:
        return [_volatile_month(trades), _lessons_check(c, user_id, 6, "Pass the Adjustments course (Level 6 lessons)")]
    if level == 7:
        need, of = config.L7_PROFIT_MONTHS
        return [_profit_months(history, now, need, of), _window_dd(history, now, of, config.L7_MAX_DD_PCT)]
    if level == 8:
        year = metrics([t for t in history if float(t["age_days"]) <= 365])
        return [{"label": f"Return ÷ drawdown {config.L8_RET_DD_12M:g} or more over 12 months",
                 "ok": year["trades"] > 0 and year["ret_dd"] >= config.L8_RET_DD_12M, "value": year["ret_dd"]},
                _top_boards(c, user_id)]
    if level == 9:
        need, of = config.L9_PROFIT_MONTHS
        approved = c.value("SELECT final_approved_at FROM user_levels WHERE user_id=:u", u=user_id)
        return [_profit_months(history, now, need, of), _window_dd(history, now, of, config.L9_MAX_DD_PCT),
                _mentees(c, user_id), _track_record(history),
                {"label": FINAL_LABEL, "ok": approved is not None, "value": "Approved" if approved else "Waiting"}]
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
    # Everything since the last reset; the gate's own trades are the part since reaching the level.
    # `alert_days`: how long a leg stayed open after its stop alert fired (null if it never did).
    history = c.all("SELECT t.*, to_char(t.closed_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM') AS month, "
                    "EXTRACT(EPOCH FROM (CAST(:n AS timestamptz) - t.closed_at)) / 86400 AS age_days, "
                    "EXTRACT(EPOCH FROM (t.closed_at - p.sl_alert_at)) / 86400 AS alert_days, "
                    "t.closed_at >= GREATEST(l.level_since, a.created_at) AS in_gate FROM trade_results t "
                    "JOIN accounts a ON a.user_id = t.user_id JOIN user_levels l ON l.user_id = t.user_id "
                    "LEFT JOIN positions p ON p.id = t.position_id AND p.user_id = t.user_id "
                    "WHERE t.user_id=:u AND t.closed_at >= a.created_at ORDER BY t.closed_at, t.id", u=user_id, n=now)
    trades = [t for t in history if t["in_gate"]]
    nxt = None
    if level < MAX_LEVEL:
        checks = [{"label": f"{xp_needed(level):,} XP", "ok": xp >= xp_needed(level), "value": xp},
                  {"label": f"{config.LEVEL_MIN_DAYS[level]} days at this level",
                   "ok": days >= config.LEVEL_MIN_DAYS[level], "value": days},
                  *_gate(level, trades, c, user_id, now, history)]
        nxt = {"level": level + 1, "title": config.LEVEL_TITLES[level + 1], "xp_needed": xp_needed(level),
               "xp_from": xp_needed(level - 1), "days": days, "min_days": config.LEVEL_MIN_DAYS[level],
               "checks": checks, "ready": all(ch["ok"] for ch in checks)}
    return {"level": level, "title": config.LEVEL_TITLES[level], "badges": badges(level), "level_since": since, "gate_since": start,
            "xp": xp, "next": nxt, "metrics": metrics(trades)}


def badges(level: int) -> list[str]:
    """The badges a level has earned (config.BADGES, #120), lowest first."""
    return [b for lv, b in sorted(config.BADGES.items()) if level >= lv]


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
    _maybe_beta(user_id, snap["level"])
    from . import capital  # capital reads IST from here
    grants = capital.evaluate(user_id)  # task milestones (#47): pays whatever is newly done
    return {**snap, "leveled_up": up, "capital_grants": grants}


def final_ready(user_id: int) -> bool:
    """At Level 9 with every check passed except the owner's final-assessment sign-off."""
    with db.tx(user_id) as c:
        # Cheap first: the Admin list asks this for every user, and only Level 9 can be waiting.
        if c.value("SELECT level FROM user_levels WHERE user_id=:u", u=user_id) != 9:
            return False
        snap = _snapshot(c, user_id, datetime.now(timezone.utc))
    if snap["level"] != 9 or not snap["next"]:
        return False
    return all(ch["ok"] for ch in snap["next"]["checks"] if ch["label"] != FINAL_LABEL)


def approve_final(owner_id: int, target_id: int, ip: str | None = None) -> dict:
    """The owner signs off the Level 10 final assessment, once everything else passes; the user then
    moves up at once. Audited."""
    from . import auth
    if not final_ready(target_id):
        raise ValueError("Only a Level 9 user who has passed every other check can be approved")
    with db.tx(target_id) as c:
        c.run("UPDATE user_levels SET final_approved_at=now(), final_approved_by=:o WHERE user_id=:u",
              o=owner_id, u=target_id)
    auth.audit("final_assessment_approved", actor_id=owner_id, target_user_id=target_id, ip=ip)
    return evaluate(target_id)


def _maybe_beta(user_id: int, level: int) -> None:
    """Level config.BETA_LEVEL promotes a `user` to `beta`, considered once: `auto_beta` is set
    either way, so an owner's later demotion back to User is never undone (#123)."""
    from . import auth
    if level < config.BETA_LEVEL:
        return
    with db.tx(user_id) as c:
        done = c.value("UPDATE user_levels SET auto_beta=true WHERE user_id=:u AND NOT auto_beta RETURNING 1", u=user_id)
    if done:
        auth.auto_promote(user_id, "beta", level)


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
