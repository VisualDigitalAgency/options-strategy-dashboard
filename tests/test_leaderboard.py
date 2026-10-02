"""Monthly leaderboard (issue #125): rankings match hand-computed fixtures including the tie-break,
opted-out and under-5-trade users are excluded, Levels 1-3 rank in the Rising band, quarters, a reset splits capital, RLS (anyone
reads, only the worker writes), and the public RPC carries nothing beyond nicknames."""
import os
import sys

import server
from engine import cache, db, leaderboard, progress
from support import EXP, new_user

ORIGIN = "https://t.example"
os.environ["PUBLIC_URL"] = "https://theta.example"
server.ALLOWED_ORIGINS = {ORIGIN}
fails = []
MONTH = "2026-08"
CAP = 1_000_000


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def person(nick, level, pnls, opt_in=True, day="2026-08-%02d 10:00+05:30", reset=None):
    uid = new_user(f"{nick.lower()}@test.example", CAP)
    with db.tx() as c:
        c.run("UPDATE users SET nickname=:n, leaderboard_opt_in=:o WHERE id=:u", n=nick, o=opt_in, u=uid)
    with db.tx(uid) as c:
        c.run("UPDATE accounts SET created_at=:t WHERE user_id=:u", t=reset or "2026-01-01 00:00+05:30", u=uid)
        c.run("INSERT INTO user_levels (user_id, level) VALUES (:u, :l)", u=uid, l=level)
        for i, p in enumerate(pnls, 1):
            c.run("INSERT INTO trade_results (user_id, symbol, expiry, side, strike, short, lots, avg_price,"
                  " realized_pnl, capital, opened_at, closed_at, exit_reason, had_sl) VALUES (:u, 'SBIN', :e,"
                  " 'CE', 1200, true, 1, 5, :p, :c, :t, :t, 'manual', true)", u=uid, e=EXP, p=p, c=CAP, t=day % i)
    return uid


# 1. Scoring by hand: equity 10k, 5k, 15k, 20k, 20k -> 2% return, 0.5% drawdown floored to 1%.
s = leaderboard.score([10000, -5000, 10000, 5000, 0], CAP)
check("score by hand", s == {"return_pct": 2.0, "max_dd_pct": 0.5, "ratio": 2.0, "trades": 5, "win_rate": 60.0}, s)
s = leaderboard.score([-10000, 30000, 0, 0, 0], CAP)
check("drawdown from a running peak that starts at 0", s["max_dd_pct"] == 1.0 and s["ratio"] == 2.0, s)

# 2. Fixtures. In 4-6: Cara 2.5 (no drawdown, floored), Bo 2.0 at 4%, Ann 2.0 at 2% -> Bo wins the tie.
person("Ann", 5, [10000, -5000, 10000, 5000, 0])
person("Bo", 4, [20000, -20000, 20000, 20000, 0])
person("Cara", 6, [5000] * 5)
person("Dev", 8, [-10000, 30000, 0, 0, 0])
person("OptedOut", 5, [50000] * 5, opt_in=False)
person("FourOnly", 5, [50000] * 4)
lvl3 = person("Lvl3", 3, [50000] * 5)
person("OtherMonth", 5, [50000] * 5, day="2026-07-%02d 10:00+05:30")
person("PreReset", 5, [50000] * 5, reset="2026-08-20 00:00+05:30")  # all trades before the reset

b = leaderboard.compute(MONTH)
mid = [(r["rank"], r["nickname"], r["ratio"], r["return_pct"]) for r in b["4-6"]]
check("4-6 ranked by ratio, tie broken by return", mid == [(1, "Cara", 2.5, 2.5), (2, "Bo", 2.0, 4.0), (3, "Ann", 2.0, 2.0)], mid)
top = [(r["rank"], r["nickname"], r["level"]) for r in b["7-10"]]
check("7-10 band", top == [(1, "Dev", 8)], top)
names = {r["nickname"] for rows in b.values() for r in rows}
check("Levels 1-3 rank in the Rising band", [r["nickname"] for r in b["1-3"]] == ["Lvl3"], b["1-3"])
for n in ("OptedOut", "FourOnly", "OtherMonth", "PreReset"):
    check(f"excluded: {n}", n not in names)
check("rows carry no user id, email or rupee amount", set(b["4-6"][0]) == set(leaderboard.FIELDS), b["4-6"][0])

# 3. Finalize, idempotent; RLS.
check("finalize writes 5 rows", leaderboard.finalize(MONTH) == 5)
check("re-running replaces, never duplicates", leaderboard.finalize(MONTH) == 5)
check("month listed", MONTH in leaderboard.finalized_months())
someone = new_user("someone@test.example", CAP)
with db.tx(someone) as c:
    check("any user reads the board", c.value("SELECT count(*) FROM leaderboard_entries") == 5)
for sql in ("INSERT INTO leaderboard_entries VALUES ('2026-08', '4-6', 9, 'x', 5, 9, 9, 0, 5, 100)",
            "DELETE FROM leaderboard_entries"):
    try:
        with db.tx(someone) as c:
            c.run(sql)
            n = c.value("SELECT count(*) FROM leaderboard_entries")
    except Exception as e:
        n = type(e).__name__
    check(f"a user transaction can't write ({sql.split()[0]})", n == 5 or n == "ProgrammingError", n)
with db.tx() as c:
    check("still 5 rows", c.value("SELECT count(*) FROM leaderboard_entries") == 5)
with db.tx(lvl3) as c:
    check("a Rising-band win doesn't count toward the Level 8 gate", progress._top_boards(c, lvl3)["value"] == 0)

# 4. Public RPC, no cookie.
cache.delete("leaderboard:current")
app = server.app.test_client()


def call(params):
    return app.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "leaderboard_get", "params": params},
                    headers={"Origin": ORIGIN}).get_json()


r = call({"month": MONTH})
res = r.get("result", {})
band = {x["band"]: x for x in res.get("bands", [])}
check("loads without sign-in", not res.get("provisional") and band["4-6"]["rows"][1]["nickname"] == "Bo", r)
check("Rising band named and listed first", res["bands"][0]["levels"] == "Rising" and band["1-3"]["rows"][0]["nickname"] == "Lvl3")
check("no personal data in the response", "@" not in str(r) and "1000000" not in str(r) and "user_id" not in str(r))
r = call({})
check("no month gives the provisional running month", r["result"]["provisional"] and r["result"]["month"] == leaderboard.this_month(), r)
check("finished months offered", MONTH in r["result"]["months"], r["result"]["months"])
check("bad month refused", "error" in call({"month": "2026-13"}))
check("bad quarter refused", "error" in call({"month": "2026-Q5"}))

# 5. Quarters: 5 legs in each of its months (15 in all), scored over the whole quarter.
person("Quinn", 5, [2000] * 5, day="2026-07-%02d 10:00+05:30")
with db.tx() as c:
    quinn = c.value("SELECT id FROM users WHERE nickname='Quinn'")
with db.tx(quinn) as c:
    for mo in ("08", "09"):
        for i in range(1, 6):
            c.run("INSERT INTO trade_results (user_id, symbol, expiry, side, strike, short, lots, avg_price, realized_pnl,"
                  " capital, opened_at, closed_at, exit_reason, had_sl) VALUES (:u, 'SBIN', :e, 'CE', 1200, true, 1, 5,"
                  " 2000, :c, :t, :t, 'manual', true)", u=quinn, e=EXP, c=CAP, t=f"2026-{mo}-{i:02d} 10:00+05:30")
check("quarter months", leaderboard.quarter_months("2026-Q3") == ["2026-07", "2026-08", "2026-09"]
      and leaderboard.quarter_of("2026-08") == "2026-Q3")
r = call({"month": "2026-Q3"})["result"]
q = {x["band"]: [y["nickname"] for y in x["rows"]] for x in r["bands"]}
check("a quarter needs 5 legs a month: only Quinn qualifies", q["4-6"] == ["Quinn"] and r["kind"] == "quarter"
      and not r["provisional"], q)
quinn_row = next(x for x in r["bands"] if x["band"] == "4-6")["rows"][0]
check("scored over all 15 legs", quinn_row["trades"] == 15 and quinn_row["return_pct"] == 3.0, quinn_row)
check("quarters offered", "2026-Q3" in call({})["result"]["quarters"])

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
