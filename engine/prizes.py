"""Monthly prize draw: the "least risky cash shape" of the retention plan. OFF by default.

Nothing here runs until the owner turns on the `prize_draw` setting, which must wait for a written
legal opinion (doc/2026-10-03-prize-draw.md). The shape follows that note:
- free to enter, no purchase, explicit opt-in (user_prefs.prize_draw_opt_in);
- the prize never goes to the best return: entrants qualify by discipline, then winners are drawn
  at random, so nobody is paid for P&L;
- a qualified entrant, for a month: at least leaderboard.MIN_TRADES legs closed that month with a
  discipline score of at least config.CHAMPION_DISCIPLINE;
- the draw is reproducible: winners come from a SHA-256 of a stored random seed, the month and the
  sorted entrant ids, so anyone holding the seed can re-check it;
- TDS is recorded at config.PRIZE_TDS_PCT; KYC (PAN) and payment happen outside the app, and the
  owner marks each win paid or void. The app never stores a PAN or bank details.
"""

import hashlib
import secrets

from . import app_settings, config, db, leaderboard, users

STATUSES = ("pending_kyc", "paid", "void")


def enabled() -> bool:
    return bool(app_settings.get("prize_draw"))


def entrants(month: str) -> list[int]:
    """Opted-in active users who qualified in `month`, sorted by id."""
    out = []
    for uid in users.active_user_ids():
        with db.tx(uid) as c:
            if not c.value("SELECT prize_draw_opt_in FROM user_prefs WHERE user_id=:u", u=uid):
                continue
            legs = c.all("SELECT had_sl, short, entry_delta, price_source FROM trade_results WHERE user_id=:u "
                         "AND to_char(closed_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM') = :m", u=uid, m=month)
        if any(l["price_source"] == "live" for l in legs):  # traded on live broker prices this month (#216): not drawn, as on the leaderboard
            continue
        if len(legs) >= leaderboard.MIN_TRADES and leaderboard.discipline(legs) >= config.CHAMPION_DISCIPLINE:
            out.append(uid)
    return sorted(out)


def pick(seed: str, month: str, ids: list[int], n: int) -> list[int]:
    """n distinct winners from `ids`, determined only by the seed, the month and the ids."""
    pool, won = list(ids), []
    for i in range(min(n, len(pool))):
        h = int(hashlib.sha256(f"{seed}:{month}:{i}:{','.join(map(str, pool))}".encode()).hexdigest(), 16)
        won.append(pool.pop(h % len(pool)))
    return won


def draw(month: str) -> list[int]:
    """Runs `month`'s draw once (worker, after the month is frozen). Does nothing while the setting
    is off or if the month was drawn already. Returns the winners' ids."""
    from . import auth
    if not enabled():
        return []
    with db.tx() as c:
        if c.value("SELECT 1 FROM prize_draws WHERE month=:m", m=month):
            return []
    ids = entrants(month)
    if not ids:
        return []
    seed = secrets.token_hex(16)
    won = pick(seed, month, ids, config.PRIZE_WINNERS)
    tds = round(config.PRIZE_RUPEES * config.PRIZE_TDS_PCT / 100, 2)
    with db.tx() as c:
        for uid in won:
            c.run("INSERT INTO prize_draws (month, user_id, prize, tds, entrants, seed) VALUES (:m, :u, :p, :t, :n, :s)",
                  m=month, u=uid, p=config.PRIZE_RUPEES, t=tds, n=len(ids), s=seed)
    auth.audit("prize_drawn", month=month, entrants=len(ids), winners=won, seed=seed)
    return won


def status(user_id: int) -> dict:
    """For My progress: whether the draw runs, the caller's entry, the rules, and their wins."""
    with db.tx(user_id) as c:
        opted = bool(c.value("SELECT prize_draw_opt_in FROM user_prefs WHERE user_id=:u", u=user_id))
        wins = c.all("SELECT month, prize, tds, status FROM prize_draws WHERE user_id=:u ORDER BY month DESC", u=user_id)
    return {"enabled": enabled(), "opted_in": opted, "prize": config.PRIZE_RUPEES, "winners": config.PRIZE_WINNERS,
            "min_trades": leaderboard.MIN_TRADES, "min_discipline": config.CHAMPION_DISCIPLINE,
            "tds_pct": config.PRIZE_TDS_PCT, "wins": [{**w, "prize": float(w["prize"]), "tds": float(w["tds"])} for w in wins]}


def set_opt_in(user_id: int, opt_in: bool) -> dict:
    """Enters or leaves the monthly draw. Entering is refused while the draw is off."""
    if opt_in and not enabled():
        raise ValueError("The prize draw isn't running")
    with db.tx(user_id) as c:
        c.run("INSERT INTO user_prefs (user_id, prize_draw_opt_in) VALUES (:u, :o) "
              "ON CONFLICT (user_id) DO UPDATE SET prize_draw_opt_in=:o", u=user_id, o=opt_in)
    return status(user_id)


def admin_list() -> list[dict]:
    """Owner: every win, newest first, with the winner's name and email for KYC and payment."""
    with db.tx() as c:
        rows = c.all("SELECT d.id, d.month, d.prize, d.tds, d.entrants, d.seed, d.status, d.note, d.drawn_at, "
                     "u.name, u.email FROM prize_draws d JOIN users u ON u.id = d.user_id ORDER BY d.month DESC, d.id")
    return [{**r, "prize": float(r["prize"]), "tds": float(r["tds"])} for r in rows]


def admin_mark(owner_id: int, draw_id: int, status: str, note: str | None = None, ip: str | None = None) -> list[dict]:
    """Owner: marks a win paid (after KYC and payment outside the app) or void. Audited."""
    from . import auth
    if status not in STATUSES:
        raise ValueError("Status must be pending_kyc, paid or void")
    with db.tx() as c:
        if not c.value("UPDATE prize_draws SET status=:s, note=:n, updated_at=now() WHERE id=:i RETURNING id",
                       s=status, n=(note or "")[:500] or None, i=draw_id):
            raise ValueError("Draw not found")
    auth.audit("prize_marked", actor_id=owner_id, ip=ip, draw_id=draw_id, status=status)
    return admin_list()
