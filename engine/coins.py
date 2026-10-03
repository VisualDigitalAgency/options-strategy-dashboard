"""Coins (issue #47): a reward currency on top of the virtual-capital grants (engine/capital.py).

Earned, each checked here from data the server holds and paid once per (kind, ref) into
`coin_ledger`:
- the capital tasks and level-ups, in coins (config.COIN_TASKS, COIN_LEVEL);
- each disciplined profitable short leg: stop-loss on, sold below DELTA_MAX_ABS, held
  COIN_TRADE_MIN_DAYS, at least COIN_TRADE_MIN_PNL profit, at most COIN_TRADE_PER_MONTH a month;
- every COIN_XP_STEP XP.

Spent only by exchange: one way, coins → virtual capital at COIN_RUPEES each. An exchange is booked
as a capital grant, so it survives a reset and never counts as profit.
"""

from datetime import datetime

from . import capital, config, db, habits
from .progress import IST

LABELS = {**capital.LABELS, "level": "Reach a level", "trade": "A disciplined profitable trade",
          "challenge": "Weekly challenge",
          "xp": f"Every {config.COIN_XP_STEP} XP", "exchange": "Exchanged for virtual capital"}


class CoinError(ValueError):
    pass


def _trades(c, user_id: int) -> list[str]:
    """Refs of short legs that qualify, capped per IST month (oldest first)."""
    rows = c.all("SELECT id, to_char(closed_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM') AS m FROM trade_results "
                 "WHERE user_id=:u AND short AND had_sl AND realized_pnl >= :p AND entry_delta < :d "
                 "AND closed_at - opened_at >= make_interval(days => :n) ORDER BY closed_at, id",
                 u=user_id, p=config.COIN_TRADE_MIN_PNL, d=config.DELTA_MAX_ABS, n=config.COIN_TRADE_MIN_DAYS)
    out, per = [], {}
    for r in rows:
        per[r["m"]] = per.get(r["m"], 0) + 1
        if per[r["m"]] <= config.COIN_TRADE_PER_MONTH:
            out.append(str(r["id"]))
    return out


def _due(user_id: int) -> dict[str, list[str]]:
    with db.tx(user_id) as c:
        due = capital._earned(c, user_id)
        due["trade"] = _trades(c, user_id)
        xp = c.value("SELECT COALESCE(SUM(points), 0) FROM xp_ledger WHERE user_id=:u", u=user_id)
        due["challenge"] = habits.completed_weeks(c, user_id, datetime.now(IST))
    due |= capital._invites(user_id)
    due["xp"] = [str(n) for n in range(1, max(int(xp), 0) // config.COIN_XP_STEP + 1)]
    return due


def _coins(kind: str, ref: str) -> int:
    if kind == "level":
        return config.COIN_LEVEL[int(ref)]
    if kind == "trade":
        return config.COIN_TRADE
    if kind == "xp":
        return config.COIN_XP
    if kind == "challenge":
        return config.COIN_CHALLENGE
    return config.COIN_TASKS[kind][0]


def _limit(kind: str, refs: list[str]) -> int:
    return config.COIN_TASKS[kind][1] if kind in config.COIN_TASKS else len(refs)


def evaluate(user_id: int) -> list[dict]:
    """Pays every coin newly earned. Idempotent; returns the credits made by this call."""
    due = _due(user_id)
    new = []
    with db.tx(user_id) as c:
        if not c.value("SELECT 1 FROM accounts WHERE user_id=:u FOR UPDATE", u=user_id):
            return []
        paid: dict[str, set] = {}
        for r in c.all("SELECT kind, ref FROM coin_ledger WHERE user_id=:u AND coins > 0", u=user_id):
            paid.setdefault(r["kind"], set()).add(r["ref"])
        for kind, refs in due.items():
            if kind != "level" and kind not in config.COIN_TASKS and kind not in ("trade", "xp", "challenge"):
                continue
            for ref in refs:
                got = paid.setdefault(kind, set())
                if ref in got or len(got) >= _limit(kind, refs):
                    continue
                n = _coins(kind, ref)
                if c.value("INSERT INTO coin_ledger (user_id, kind, ref, coins) VALUES (:u, :k, :r, :n) "
                           "ON CONFLICT (user_id, kind, ref) DO NOTHING RETURNING id", u=user_id, k=kind, r=ref, n=n):
                    got.add(ref)
                    new.append({"kind": kind, "ref": ref, "coins": n})
    return new


def balance(c, user_id: int) -> int:
    return int(c.value("SELECT COALESCE(SUM(coins), 0) FROM coin_ledger WHERE user_id=:u", u=user_id))


def exchange(user_id: int, coins: int) -> dict:
    """Turns `coins` into virtual capital at COIN_RUPEES each. One way: capital never turns back into
    coins. Booked as a capital grant, so a reset keeps it and return % doesn't count it as profit."""
    if coins <= 0:
        raise CoinError("Exchange at least 1 coin")
    with db.tx(user_id) as c:
        if not c.value("SELECT 1 FROM accounts WHERE user_id=:u FOR UPDATE", u=user_id):
            raise CoinError("No virtual account")
        have = balance(c, user_id)
        if coins > have:
            raise CoinError(f"You have {have} coins")
        rupees = coins * config.COIN_RUPEES
        lid = c.value("INSERT INTO coin_ledger (user_id, kind, ref, coins) VALUES (:u, 'exchange', "
                      "'x' || nextval('coin_ledger_id_seq'), :n) RETURNING id", u=user_id, n=-coins)
        c.run("INSERT INTO capital_grants (user_id, task, ref, amount) VALUES (:u, 'coins', :r, :a)",
              u=user_id, r=str(lid), a=rupees)
        c.run("UPDATE accounts SET starting_capital = starting_capital + :a WHERE user_id=:u", a=rupees, u=user_id)
        left = balance(c, user_id)
    return {"exchanged": coins, "rupees": rupees, "balance": left}


def status(user_id: int) -> dict:
    """The Coins page: balance, the rate, how each kind is earned, and the history."""
    capital.evaluate(user_id)  # pays capital grants, then coins
    with db.tx(user_id) as c:
        bal = balance(c, user_id)
        rows = c.all("SELECT kind, ref, coins, created_at FROM coin_ledger WHERE user_id=:u ORDER BY created_at DESC, id DESC "
                     "LIMIT 200", u=user_id)
        month = c.value("SELECT to_char(now() AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM')")
        trades_month = c.value("SELECT count(*) FROM trade_results WHERE user_id=:u "
                               "AND to_char(closed_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM') = :m "
                               "AND id::text IN (SELECT ref FROM coin_ledger WHERE user_id=:u AND kind='trade')",
                               u=user_id, m=month)
    rules = [{"key": k, "label": capital.LABELS[k], "coins": n, "max": m} for k, (n, m) in config.COIN_TASKS.items()]
    rules += [{"key": "trade", "label": f"Profitable short leg: stop-loss on, delta below {config.DELTA_MAX_ABS}, "
               f"held {config.COIN_TRADE_MIN_DAYS}+ days, ₹{config.COIN_TRADE_MIN_PNL}+ profit", "coins": config.COIN_TRADE,
               "max": config.COIN_TRADE_PER_MONTH, "per": "month", "done": trades_month},
              {"key": "xp", "label": LABELS["xp"], "coins": config.COIN_XP, "max": None},
              {"key": "challenge", "label": "Finish the weekly challenge (on My progress)", "coins": config.COIN_CHALLENGE,
               "max": 1, "per": "week"}]
    return {"balance": bal, "rupees_per_coin": config.COIN_RUPEES, "rules": rules,
            "levels": [{"level": lv, "coins": n} for lv, n in config.COIN_LEVEL.items()],
            "history": [{**r, "label": LABELS.get(r["kind"], r["kind"])} for r in rows]}
