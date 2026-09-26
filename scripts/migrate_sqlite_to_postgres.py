"""One-off copy of the single-user SQLite virtual account into Postgres, under the admin user.

    python scripts/migrate_sqlite_to_postgres.py            # dry run: prints what it would copy
    python scripts/migrate_sqlite_to_postgres.py --apply    # copies, then checks before/after

- Creates the admin user (ADMIN_EMAIL, default admin@theta.local) if missing.
- Copies the account, positions, orders, auto-trade settings and run log. SQLite times are IST
  text; they become TIMESTAMPTZ. Position ids are remapped, and orders follow their position.
- Checks row counts and money totals match, inside the same transaction: any mismatch rolls
  the whole copy back.
- Never writes to SQLite. Running it again does nothing: the copy is recorded in audit_log.
Stop the old server first, or orders placed during the copy stay behind in SQLite.
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import db, users  # noqa: E402

SQLITE = ROOT / "engine" / "data" / "virtual.db"
IST = timezone(timedelta(hours=5, minutes=30))
ACTION = "sqlite_import"


def ts(v):
    """'2026-09-24 15:57:39' (IST) -> aware datetime. Dates and NULLs pass through."""
    if v is None or len(v) == 10:
        return v
    return datetime.strptime(v, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)


def read_sqlite() -> dict:
    # Read-only URI: the source file can't be changed by this script.
    c = sqlite3.connect(f"file:{SQLITE.as_posix()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    q = lambda sql: [dict(r) for r in c.execute(sql)]
    data = {
        "account": q("SELECT * FROM account WHERE id=1")[0],
        "positions": q("SELECT * FROM positions ORDER BY id"),
        "orders": q("SELECT * FROM orders ORDER BY id"),
        "autotrade": q("SELECT * FROM autotrade WHERE id=1"),
        "runs": q("SELECT * FROM autotrade_runs ORDER BY id"),
    }
    c.close()
    return data


def totals(positions, orders, runs) -> dict:
    """Numbers that must match on both sides."""
    r2 = lambda v: round(float(v), 2)
    return {
        "positions": len(positions),
        "open_legs": sum(1 for p in positions if p["status"] == "open"),
        "open_qty": sum(int(p["qty"]) for p in positions if p["status"] == "open"),
        "premium_open": r2(sum(-float(p["qty"]) * float(p["avg_price"]) for p in positions if p["status"] == "open")),
        "booked_pnl": r2(sum(float(p["realized_pnl"]) for p in positions)),
        "orders": len(orders),
        "order_value": r2(sum(float(o["qty"]) * float(o["price"]) for o in orders)),
        "runs": len(runs),
        "runs_placed": sum(int(r["placed"]) for r in runs),
    }


def main(apply: bool) -> int:
    src = read_sqlite()
    before = totals(src["positions"], src["orders"], src["runs"])
    acct = src["account"]
    print(f"SQLite {SQLITE}")
    print(f"  account: capital {acct['starting_capital']:,.0f}, SL default {acct['sl_mode_default']}, since {acct['created_at']}")
    print(f"  before: {json.dumps(before)}")
    print(f"  account value (capital + booked): {acct['starting_capital'] + before['booked_pnl']:,.2f}")

    uid = users.bootstrap_local_user()
    with db.tx() as c:
        done = c.value("SELECT COUNT(*) FROM audit_log WHERE action=:a AND target_user_id=:u", a=ACTION, u=uid)
    if done:
        print(f"Already imported into user {uid} (audit_log). Nothing to do.")
        return 0
    with db.tx(uid) as c:
        existing = c.value("SELECT COUNT(*) FROM positions WHERE user_id=:u", u=uid) + \
                   c.value("SELECT COUNT(*) FROM orders WHERE user_id=:u", u=uid)
    if existing:
        print(f"User {uid} already has {existing} positions/orders in Postgres. Refusing to mix; nothing copied.")
        return 1
    if not apply:
        print(f"Dry run: would copy into user {uid}. Re-run with --apply.")
        return 0

    with db.tx(uid) as c:  # one transaction: all of it lands, or none
        c.run("UPDATE accounts SET starting_capital=:cap, sl_mode_default=:m, created_at=:t WHERE user_id=:u",
              cap=acct["starting_capital"], m=acct["sl_mode_default"], t=ts(acct["created_at"]), u=uid)
        ids = {}
        for p in src["positions"]:
            ids[p["id"]] = c.value(
                "INSERT INTO positions (user_id, symbol, expiry, side, strike, qty, avg_price, lot_size, status,"
                " opened_at, closed_at, realized_pnl, exit_price, sl_mode, sl_price, sl_activates_on, sl_alert_at)"
                " VALUES (:u,:symbol,:expiry,:side,:strike,:qty,:avg_price,:lot_size,:status,:opened_at,:closed_at,"
                ":realized_pnl,:exit_price,:sl_mode,:sl_price,:sl_activates_on,:sl_alert_at) RETURNING id",
                u=uid, **{**p, "opened_at": ts(p["opened_at"]), "closed_at": ts(p["closed_at"]),
                          "sl_alert_at": ts(p["sl_alert_at"])})
        for o in src["orders"]:
            c.run("INSERT INTO orders (user_id, position_id, ts, symbol, expiry, side, strike, action, qty, price,"
                  " reason, realized_pnl, note) VALUES (:u,:pid,:ts,:symbol,:expiry,:side,:strike,:action,:qty,"
                  ":price,:reason,:realized_pnl,:note)",
                  u=uid, pid=ids.get(o["position_id"]), **{**o, "ts": ts(o["ts"])})
        for a in src["autotrade"]:
            c.run("UPDATE autotrade_settings SET enabled=:e, run_at=:r, min_pop=:p, reserve_pct=:res,"
                  " max_trade_pct=:mx, last_run_date=:d WHERE user_id=:u",
                  e=bool(a["enabled"]), r=a["run_at"], p=a["min_pop"], res=a["reserve_pct"],
                  mx=a["max_trade_pct"], d=a["last_run_date"], u=uid)
        for r in src["runs"]:
            c.run("INSERT INTO autotrade_runs (user_id, ts, trigger, placed, summary)"
                  " VALUES (:u, :ts, :t, :n, CAST(:s AS jsonb))",
                  u=uid, ts=ts(r["ts"]), t=r["trigger"], n=r["placed"], s=r["summary"])

        after = totals(c.all("SELECT * FROM positions WHERE user_id=:u", u=uid),
                       c.all("SELECT * FROM orders WHERE user_id=:u", u=uid),
                       c.all("SELECT * FROM autotrade_runs WHERE user_id=:u", u=uid))
        cap_after = c.value("SELECT starting_capital FROM accounts WHERE user_id=:u", u=uid)
        orphans = c.value("SELECT COUNT(*) FROM orders WHERE user_id=:u AND position_id IS NULL", u=uid)
        print(f"  after:  {json.dumps(after)}")
        print(f"  account value (capital + booked): {cap_after + after['booked_pnl']:,.2f}")
        problems = [k for k in before if before[k] != after[k]]
        if cap_after != acct["starting_capital"]:
            problems.append("starting_capital")
        if orphans != sum(1 for o in src["orders"] if o["position_id"] is None):
            problems.append("order->position links")
        if problems:
            raise SystemExit(f"Mismatch in {problems}; rolled back, nothing copied.")
        c.run("INSERT INTO audit_log (actor_id, action, target_user_id, detail)"
              " VALUES (:u, :a, :u, CAST(:d AS jsonb))", u=uid, a=ACTION, d=json.dumps({"source": str(SQLITE), **after}))
    print(f"Imported into user {uid}. Every check matches. SQLite left untouched.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    sys.exit(main(ap.parse_args().apply))
