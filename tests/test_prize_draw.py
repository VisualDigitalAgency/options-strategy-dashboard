"""Monthly prize draw: does nothing while the owner's setting is off; entry is explicit; only
disciplined opted-in players qualify; the draw is reproducible from its seed; a user reads only their
own wins; the owner marks wins paid (audited)."""
import sys

from engine import app_settings, config, db, prizes, users
from support import EXP, new_user

fails = []
MONTH = "2026-08"


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def player(email, sl=True, n=5):
    uid = new_user(email, 1_000_000)
    with db.tx(uid) as c:
        for i in range(1, n + 1):
            c.run("INSERT INTO trade_results (user_id, symbol, expiry, side, strike, short, lots, avg_price, realized_pnl,"
                  " capital, opened_at, closed_at, exit_reason, had_sl, entry_delta) VALUES (:u, 'SBIN', :e, 'CE', 1200,"
                  " true, 1, 5, -100, 1000000, :t, :t, 'manual', :sl, 0.1)", u=uid, e=EXP, sl=sl, t=f"2026-08-{i:02d} 10:00+05:30")
    return uid


owner = users.create_user("o@test.example", "O", role="owner", status="active")
good = player("good@test.example")
also = player("also@test.example")
reckless = player("reckless@test.example", sl=False)
few = player("few@test.example", n=3)
shy = player("shy@test.example")

# 1. Off by default: no entry, no draw.
check("setting off by default", app_settings.get("prize_draw") is False)
try:
    prizes.set_opt_in(good, True)
    check("entry refused while off", False)
except ValueError:
    check("entry refused while off", True)
check("no draw while off", prizes.draw(MONTH) == [])

# 2. On: explicit entry; only disciplined opted-in players with enough trades qualify (losses don't matter).
app_settings.set_value(owner, "prize_draw", True)
for u in (good, also, reckless, few):
    prizes.set_opt_in(u, True)
check("entrants: disciplined, enough trades, opted in", prizes.entrants(MONTH) == sorted([good, also]), prizes.entrants(MONTH))

# 3. Draw: one winner among the entrants, reproducible from the seed, once per month.
won = prizes.draw(MONTH)
check("one winner, an entrant", len(won) == config.PRIZE_WINNERS and won[0] in (good, also), won)
rows = prizes.admin_list()
check("TDS recorded", rows[0]["tds"] == config.PRIZE_RUPEES * config.PRIZE_TDS_PCT / 100 and rows[0]["entrants"] == 2, rows[0])
check("reproducible from the stored seed", prizes.pick(rows[0]["seed"], MONTH, sorted([good, also]), 1) == won)
check("not drawn twice", prizes.draw(MONTH) == [])

# 4. A user sees only their own wins (RLS).
loser = also if won[0] == good else good
check("winner sees the win", prizes.status(won[0])["wins"][0]["status"] == "pending_kyc")
check("others see none", prizes.status(loser)["wins"] == [])
with db.tx(loser) as c:
    check("RLS hides other users' rows", c.value("SELECT count(*) FROM prize_draws") == 0)

# 5. Owner marks it paid, audited.
prizes.admin_mark(owner, rows[0]["id"], "paid", "UTR 123")
check("marked paid", prizes.admin_list()[0]["status"] == "paid")
with db.tx() as c:
    check("audited", c.value("SELECT count(*) FROM audit_log WHERE action IN ('prize_drawn', 'prize_marked')") == 2)
try:
    prizes.admin_mark(owner, rows[0]["id"], "sent")
    check("unknown status refused", False)
except ValueError:
    check("unknown status refused", True)

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
