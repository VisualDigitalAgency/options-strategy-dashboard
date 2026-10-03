"""Retention phase 3: time-limited grants (free Pro months). A grant with months lapses on its own,
an award extends rather than restarts, the owner's deny or permanent grant is never touched, and the
season champions get Pro when their month is frozen."""
import sys

from engine import config, db, leaderboard, permissions, users
from support import EXP, new_user

fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def has_pro(uid):
    return "screener" in permissions.user_features(uid, "user")


def expires(uid):
    with db.tx() as c:
        return c.value("SELECT expires_at FROM user_feature_overrides WHERE user_id=:u AND feature='screener'", u=uid)


owner = users.create_user("o@test.example", "O", role="owner", status="active")
a = users.create_user("a@test.example", "A", status="active")

# 1. Owner grants Pro for 3 months; it lapses once expired.
permissions.set_override(owner, a, "screener", "grant", months=3)
check("time-limited grant gives Pro", has_pro(a))
check("expiry set", expires(a) is not None)
with db.tx() as c:
    c.run("UPDATE user_feature_overrides SET expires_at = now() - interval '1 minute' WHERE user_id=:u", u=a)
check("lapsed grant no longer counts", not has_pro(a))
check("lapsed grant hidden from the override list", permissions.overrides(a) == [])
for bad in ({"mode": "deny", "months": 1}, {"mode": "grant", "months": 13}):
    try:
        permissions.set_override(owner, a, "screener", bad["mode"], months=bad["months"])
        check(f"refused: {bad}", False)
    except ValueError:
        check(f"refused: {bad}", True)

# 2. Awards: extend, never override the owner's deny or permanent grant, never the owner.
b = users.create_user("b@test.example", "B", status="active")
check("award grants Pro", permissions.award_months(b, "screener", 1, "test") and has_pro(b))
permissions.award_months(b, "screener", 1, "test")
with db.tx() as c:
    left = c.value("SELECT extract(day FROM expires_at - now()) FROM user_feature_overrides WHERE user_id=:u", u=b)
check("a second award extends the first (about 2 months left)", float(left) >= 55, left)
d = users.create_user("d@test.example", "D", status="active")
permissions.set_override(owner, d, "screener", "deny")
check("an owner's deny stays", not permissions.award_months(d, "screener", 1, "test") and not has_pro(d))
p = users.create_user("p@test.example", "P", status="active")
permissions.set_override(owner, p, "screener", "grant")
check("a permanent grant stays permanent", not permissions.award_months(p, "screener", 1, "test") and expires(p) is None)
check("the owner is skipped", not permissions.award_months(owner, "screener", 1, "test"))
with db.tx() as c:
    check("awards audited", c.value("SELECT count(*) FROM audit_log WHERE action='feature_awarded'") == 2)

# 3. Season champions get Pro when their month is frozen.
champ = new_user("champ@test.example", 1_000_000)
with db.tx() as c:
    c.run("UPDATE users SET nickname='Champ', leaderboard_opt_in=true WHERE id=:u", u=champ)
with db.tx(champ) as c:
    c.run("UPDATE accounts SET created_at='2026-01-01 00:00+05:30' WHERE user_id=:u", u=champ)
    c.run("INSERT INTO user_levels (user_id, level) VALUES (:u, 5)", u=champ)
    for i in range(1, 6):
        c.run("INSERT INTO trade_results (user_id, symbol, expiry, side, strike, short, lots, avg_price, realized_pnl,"
              " capital, opened_at, closed_at, exit_reason, had_sl, entry_delta) VALUES (:u, 'SBIN', :e, 'CE', 1200, true,"
              " 1, 5, 5000, 1000000, :t, :t, 'manual', true, 0.1)", u=champ, e=EXP, t=f"2026-08-{i:02d} 10:00+05:30")
leaderboard.finalize("2026-08")
check("champion awarded Pro", leaderboard.award_champions("2026-08") == 1 and has_pro(champ))
check("months from config", config.CHAMPION_PRO_MONTHS == 1)

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
