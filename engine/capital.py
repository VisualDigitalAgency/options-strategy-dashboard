"""Virtual capital milestones (issue #47).

Every account starts with config.STARTING_CAPITAL (₹2 lakh). Capital grows only by completing tasks
(config.CAPITAL_TASKS) and reaching levels (config.LEVEL_CAPITAL). Each task is checked here from data
the server already holds, never from what the browser says, and pays once per (task, ref) into
`capital_grants`; the same transaction adds it to `accounts.starting_capital`.

Grants raise the capital base, not the P&L: return % is value ÷ capital, and every closed trade
records the capital it was taken with (trade_results.capital), so a grant never shows as profit.
"""

from datetime import datetime

from . import config, db, lessons
from .progress import IST

LABELS = {
    "l1_lessons": "Pass every Level 1 lesson quiz",
    "first_sl_trade": "Close a trade with its stop-loss on",
    "five_sl_trades": "Close 5 trades, every short leg with its stop-loss on",
    "profit_month": "Finish a calendar month in profit",
    "low_delta_20": f"Close 20 short legs sold below delta {config.DELTA_MAX_ABS}",
    "adjustments": "Pass the Adjustments course (Level 6 lessons)",
    "invite_trades": "Someone you invited confirms their email and closes a trade",
    "invite_level3": "Someone you invited reaches Level 3",
    "share_card": "Share a level-up or course card",
}
LINKS = {"l1_lessons": "/learn", "adjustments": "/learn", "first_sl_trade": "/builder", "five_sl_trades": "/builder",
         "profit_month": "/portfolio", "low_delta_20": "/builder", "invite_trades": "/progress",
         "invite_level3": "/progress", "share_card": "/progress"}


def _passed(c, user_id: int, level: int) -> tuple[int, int]:
    need = {l["slug"] for l in lessons.list_lessons() if l["level"] == level}
    done = {r["slug"] for r in c.all("SELECT slug FROM lesson_progress WHERE user_id=:u AND passed_at IS NOT NULL", u=user_id)}
    return len(need & done), len(need)


def _earned(c, user_id: int) -> dict[str, list[str]]:
    """task -> the refs it is due for right now (each ref pays once)."""
    out: dict[str, list[str]] = {}
    got, need = _passed(c, user_id, 1)
    out["l1_lessons"] = [""] if need and got == need else []
    shorts = c.all("SELECT had_sl, entry_delta FROM trade_results WHERE user_id=:u AND short", u=user_id)
    n_all = c.value("SELECT count(*) FROM trade_results WHERE user_id=:u", u=user_id)
    out["first_sl_trade"] = [""] if any(t["had_sl"] for t in shorts) else []
    out["five_sl_trades"] = [""] if n_all >= 5 and all(t["had_sl"] for t in shorts) else []
    low = sum(1 for t in shorts if t["entry_delta"] is not None and float(t["entry_delta"]) < config.DELTA_MAX_ABS)
    out["low_delta_20"] = [""] if low >= 20 else []
    this_month = datetime.now(IST).strftime("%Y-%m")
    months = c.all("SELECT to_char(closed_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM') AS m, sum(realized_pnl) AS pnl "
                   "FROM trade_results WHERE user_id=:u GROUP BY 1 ORDER BY 1", u=user_id)
    out["profit_month"] = [r["m"] for r in months if r["m"] < this_month and float(r["pnl"]) > 0]
    got, need = _passed(c, user_id, 6)
    out["adjustments"] = [""] if need and got == need else []
    out["share_card"] = [r["kind"] for r in c.all("SELECT DISTINCT kind FROM share_cards WHERE user_id=:u", u=user_id)]
    level = c.value("SELECT level FROM user_levels WHERE user_id=:u", u=user_id) or 1
    out["level"] = [str(lv) for lv in config.LEVEL_CAPITAL if lv <= level]
    return out


def _invites(user_id: int) -> dict[str, list[str]]:
    """Each invited person is read in their own transaction (their rows are private under RLS)."""
    with db.tx() as c:
        invited = [r["id"] for r in c.all("SELECT id FROM users WHERE referred_by=:u AND status='active' "
                                          "AND email_verified_at IS NOT NULL", u=user_id)]
    traded, level3 = [], []
    for i in invited:
        with db.tx(i) as ci:
            if ci.value("SELECT 1 FROM trade_results WHERE user_id=:u LIMIT 1", u=i):
                traded.append(str(i))
            if (ci.value("SELECT level FROM user_levels WHERE user_id=:u", u=i) or 1) >= 3:
                level3.append(str(i))
    return {"invite_trades": traded, "invite_level3": level3}


def _amount(task: str, ref: str) -> int:
    return config.LEVEL_CAPITAL[int(ref)] if task == "level" else config.CAPITAL_TASKS[task][0]


def evaluate(user_id: int) -> list[dict]:
    """Pays every task newly completed. Idempotent; returns the grants made by this call."""
    with db.tx(user_id) as c:
        due = _earned(c, user_id)
    due |= _invites(user_id)
    new = []
    with db.tx(user_id) as c:
        if not c.value("SELECT 1 FROM accounts WHERE user_id=:u FOR UPDATE", u=user_id):
            return []
        paid: dict[str, set] = {}
        for r in c.all("SELECT task, ref FROM capital_grants WHERE user_id=:u", u=user_id):
            paid.setdefault(r["task"], set()).add(r["ref"])
        for task, refs in due.items():
            limit = config.CAPITAL_TASKS[task][1] if task in config.CAPITAL_TASKS else len(refs)
            for ref in refs:
                if ref in paid.get(task, set()) or len(paid.get(task, set())) >= limit:
                    continue
                amt = _amount(task, ref)
                ok = c.value("INSERT INTO capital_grants (user_id, task, ref, amount) VALUES (:u, :t, :r, :a) "
                             "ON CONFLICT (user_id, task, ref) DO NOTHING RETURNING id", u=user_id, t=task, r=ref, a=amt)
                if ok:
                    c.run("UPDATE accounts SET starting_capital = starting_capital + :a WHERE user_id=:u", a=amt, u=user_id)
                    paid.setdefault(task, set()).add(ref)
                    new.append({"task": task, "ref": ref, "amount": amt, "label": _label(task, ref)})
    return new


def _label(task: str, ref: str) -> str:
    return f"Reach Level {ref}" if task == "level" else LABELS[task]


def status(user_id: int) -> dict:
    """The task list for the Earn capital page: each task's reward, how often it pays, how many times
    it has paid, and where to do it; the level rewards; and the grant history."""
    evaluate(user_id)
    with db.tx(user_id) as c:
        grants = c.all("SELECT task, ref, amount, created_at FROM capital_grants WHERE user_id=:u ORDER BY created_at DESC",
                       u=user_id)
        acct = c.one("SELECT starting_capital, base_capital FROM accounts WHERE user_id=:u", u=user_id)
        level = c.value("SELECT level FROM user_levels WHERE user_id=:u", u=user_id) or 1
        l1 = _passed(c, user_id, 1)
        n_trades = c.value("SELECT count(*) FROM trade_results WHERE user_id=:u", u=user_id)
        low = c.value("SELECT count(*) FROM trade_results WHERE user_id=:u AND short AND entry_delta < :d",
                      u=user_id, d=config.DELTA_MAX_ABS)
    times = {}
    for g in grants:
        times[g["task"]] = times.get(g["task"], 0) + 1
    progress = {"l1_lessons": f"{l1[0]}/{l1[1]}", "five_sl_trades": f"{min(n_trades, 5)}/5", "low_delta_20": f"{min(low, 20)}/20"}
    tasks = [{"key": k, "label": LABELS[k], "reward": amt, "max": n, "done": times.get(k, 0),
              "progress": progress.get(k), "link": LINKS[k]} for k, (amt, n) in config.CAPITAL_TASKS.items()]
    levels = [{"level": lv, "reward": amt, "done": lv <= level} for lv, amt in config.LEVEL_CAPITAL.items()]
    return {"capital": acct["starting_capital"] if acct else None, "base": acct["base_capital"] if acct else None,
            "start": config.STARTING_CAPITAL, "tasks": tasks, "levels": levels,
            "grants": [{**g, "label": _label(g["task"], g["ref"])} for g in grants]}
