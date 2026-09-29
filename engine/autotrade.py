"""Auto-trade for the virtual account, per user.

Once a day at each user's set IST time (market hours only), ranks the screener's actionable
setups by POP-weighted ROI and sells them into that user's virtual account. Two limits bound
every order:
  - per-trade cap: margin for one setup <= account value x max % per trade
  - reserve floor: free margin after the order >= account value x reserve %
Margin is checked with the live SPAN + exposure preview before each order, so the limits hold
on real numbers, not the screener's estimate. Never touches a broker.
"""

import json
import logging
import threading
import time
from datetime import datetime, timedelta

from . import cache, config, db, users, virtual

log = logging.getLogger("theta.autotrade")

CHECK_INTERVAL = 30
FIELDS = ("enabled", "run_at", "min_pop", "reserve_pct", "max_trade_pct")
RUN_LOCK_TTL = 900  # a run takes a minute or two; the lock expires on its own if a process dies mid-run


def get_settings(user_id: int) -> dict:
    with db.tx(user_id) as c:
        s = c.one("SELECT enabled, run_at, min_pop, reserve_pct, max_trade_pct, last_run_date "
                  "FROM autotrade_settings WHERE user_id=:u", u=user_id)
    if s is None:
        raise ValueError("No auto-trade settings for this user")
    s["next_run"] = _next_run(s)
    s["running"] = cache.exists(f"lock:autotrade:{user_id}")
    return s


def set_settings(user_id: int, enabled: bool | None = None, run_at: str | None = None, min_pop: float | None = None,
                 reserve_pct: float | None = None, max_trade_pct: float | None = None) -> dict:
    kw = {"enabled": enabled, "run_at": run_at, "min_pop": min_pop, "reserve_pct": reserve_pct,
          "max_trade_pct": max_trade_pct}
    changes = {k: v for k, v in kw.items() if v is not None}
    if "run_at" in changes:
        h, m = (int(x) for x in str(changes["run_at"]).split(":"))
        if not ((9, 15) <= (h, m) < (15, 30)):
            raise ValueError("Run time must be within market hours, 09:15 to 15:29 IST")
        changes["run_at"] = f"{h:02d}:{m:02d}"
    for k, lo, hi in (("min_pop", 50, 99), ("reserve_pct", 0, 90), ("max_trade_pct", 1, 100)):
        if k in changes:
            changes[k] = float(changes[k])
            if not lo <= changes[k] <= hi:
                raise ValueError(f"{k} must be between {lo} and {hi}")
    if "enabled" in changes:
        changes["enabled"] = bool(changes["enabled"])
    if changes:
        # Column names come from the fixed parameter list above; values are bound parameters.
        assert set(changes) <= set(FIELDS)
        with db.tx(user_id) as c:
            c.run(f"UPDATE autotrade_settings SET {', '.join(f'{k}=:{k}' for k in changes)} WHERE user_id=:u",
                  u=user_id, **changes)
    return get_settings(user_id)


def get_runs(user_id: int, limit: int = 20) -> list[dict]:
    with db.tx(user_id) as c:
        return c.all("SELECT id, ts, trigger, placed, summary FROM autotrade_runs WHERE user_id=:u "
                     "ORDER BY id DESC LIMIT :n", u=user_id, n=limit)


def _next_run(s: dict) -> str | None:
    if not s["enabled"]:
        return None
    now = datetime.now(virtual.IST)
    today = now.strftime("%Y-%m-%d")
    day = now
    if s["last_run_date"] == today or now.strftime("%H:%M") >= "15:30":
        day = now + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return f"{day.strftime('%Y-%m-%d')} {s['run_at']}"


def score(c: dict) -> float:
    """POP-weighted return on margin: a 95% POP at 1.6% ROI (1.52) beats 85% at 1.2% (1.02)."""
    return round(c["strategy"]["pop"] / 100 * c["strategy"]["roi_pct"], 4)


def run(user_id: int, candidates: list[dict], trigger: str = "manual") -> dict:
    """Places auto orders from screened candidates. Returns and logs what was placed and skipped."""
    # Shared lock: the worker's scheduled run and a "Run now" from the API can never overlap.
    lock = cache.Lock(f"autotrade:{user_id}", RUN_LOCK_TTL)
    if not lock.acquire():
        raise ValueError("An auto-trade run is already in progress" if cache.up()
                         else "Auto-trade needs the cache service, which is unreachable; try again shortly")
    try:
        return _run(user_id, candidates, trigger)
    finally:
        lock.release()


def _run(user_id: int, candidates: list[dict], trigger: str) -> dict:
    s = get_settings(user_id)
    acct = virtual.get_account(user_id)
    value = acct["account_value"]
    reserve = value * s["reserve_pct"] / 100
    cap = value * s["max_trade_pct"] / 100
    held = {(g["symbol"], g["expiry"]) for g in virtual.get_positions(user_id)["groups"]}
    # An order still waiting to fill (placed outside market hours, or a limit away from the touch)
    # isn't a position yet, but it will be: without this, the next run places the same trade again.
    with db.tx(user_id) as c:
        waiting = {(r["symbol"], r["expiry"]) for r in c.all(
            "SELECT DISTINCT symbol, expiry FROM pending_orders WHERE user_id=:u AND status='open'", u=user_id)}
    free = acct["available_margin"]

    placed, skipped = [], []
    # The screen carries several expiry cycles per stock. Auto-trade stays at one position per stock
    # per run: only cycles at least MIN_DTE out (a nearer one would hit the time exit before its stop
    # ever arms), and of those the best-scoring one, nearer expiry on a tie.
    best: dict[str, dict] = {}
    for c in candidates:
        if not (c.get("legs") and (c.get("strategy") or {}).get("margin")) or (c.get("dte") or 0) < config.MIN_DTE:
            continue
        cur = best.get(c["symbol"])
        if cur is None or (score(c), -c["dte"]) > (score(cur), -cur["dte"]):
            best[c["symbol"]] = c
    ready = list(best.values())
    scores = {c["symbol"]: score(c) for c in ready}  # kept local: candidates are the shared screen cache
    ready.sort(key=lambda c: scores[c["symbol"]], reverse=True)

    for c in ready:
        sym, exp, st = c["symbol"], c["expiry"], c["strategy"]
        tag = {"symbol": sym, "pop": st["pop"], "roi_pct": st["roi_pct"], "score": scores[sym]}
        if st["pop"] < s["min_pop"]:
            skipped.append({**tag, "reason": f"POP {st['pop']:.1f}% below {s['min_pop']:g}% floor"})
            continue
        if (sym, exp) in held:
            skipped.append({**tag, "reason": "Already holding this stock and expiry"})
            continue
        if (sym, exp) in waiting:
            skipped.append({**tag, "reason": "An order for this stock and expiry is still waiting to fill"})
            continue
        room = min(cap, free - reserve)
        lots = int(room // st["margin"]) if room > 0 else 0
        if lots < 1:
            why = "Reserve floor reached" if free - reserve < st["margin"] else "One lot exceeds the per-trade cap"
            skipped.append({**tag, "reason": why})
            continue
        try:
            legs = lambda n: [{"side": l["side"], "strike": l["strike"], "action": "SELL", "lots": n} for l in c["legs"]]
            p = virtual.preview_order(user_id, sym, exp, legs(lots))
            # Live margin can differ from the screener's estimate; trim lots until both limits hold.
            while lots >= 1 and p["margin_change"] > room:
                lots = min(lots - 1, int(lots * room / p["margin_change"]))
                if lots >= 1:
                    p = virtual.preview_order(user_id, sym, exp, legs(lots))
            if lots < 1:
                skipped.append({**tag, "reason": "Live margin for one lot breaks a limit"})
                continue
            if p["illiquid"]:
                bad = "; ".join(f"{i['strike']:g} {i['side']}: {i['reason']}" for i in p["illiquid"])
                skipped.append({**tag, "reason": f"Illiquid strike ({bad})"})
                continue
            note = f"Auto: POP {st['pop']:.1f}%, ROI {st['roi_pct']:.2f}%, score {scores[sym]:.2f}"
            r = virtual.execute_order(user_id, p, reason="auto", extra_note=note)
            free -= p["margin_change"]
            held.add((sym, exp))
            placed.append({**tag, "lots": lots, "legs": [f"{l['strike']:g} {l['side']}" for l in c["legs"]],
                           "premium": r["premium"], "margin": p["margin_change"]})
        except Exception as e:
            skipped.append({**tag, "reason": f"Order failed: {e}"})

    summary = {"placed": placed, "skipped": skipped, "account_value": value, "reserve": round(reserve, 2),
               "per_trade_cap": round(cap, 2), "free_after": round(free, 2), "settings": {k: s[k] for k in FIELDS}}
    with db.tx(user_id) as c:
        c.run("INSERT INTO autotrade_runs (user_id, trigger, placed, summary) VALUES (:u, :t, :n, CAST(:s AS jsonb))",
              u=user_id, t=trigger, n=len(placed), s=json.dumps(summary))
        if trigger == "schedule":
            c.run("UPDATE autotrade_settings SET last_run_date=:d WHERE user_id=:u", d=virtual._now()[:10], u=user_id)
    return summary


def start_scheduler(get_candidates) -> None:
    """get_candidates() must return a fresh, complete screen (it may block while one runs)."""
    def loop():
        while True:
            try:
                uids = users.active_user_ids()
            except Exception:
                uids = []
            for uid in uids:  # one user at a time: they share the screen and quotes, so NSE load stays flat
                try:
                    s = get_settings(uid)
                    now = datetime.now(virtual.IST)
                    due = (s["enabled"] and virtual.market_open() and now.strftime("%H:%M") >= s["run_at"]
                           and s["last_run_date"] != now.strftime("%Y-%m-%d"))
                    if due:
                        run(uid, get_candidates(), trigger="schedule")
                        virtual.refresh_positions(uid)
                except Exception:  # one user's failure never stops the others; next pass retries
                    log.exception("auto-trade pass failed for user %s", uid)
            time.sleep(CHECK_INTERVAL)

    threading.Thread(target=loop, daemon=True, name="virtual-autotrade").start()
