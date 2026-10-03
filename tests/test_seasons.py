"""Retention phase 2: discipline score, season champions (best rank with discipline >= 80), the
season certificate, the monthly recap email and signup cohorts."""
import sys

from engine import cards, cohort, config, db, leaderboard, mail, recap, users
from support import EXP, new_user

fails = []
MONTH = "2026-08"
CAP = 1_000_000


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def person(nick, level, pnls, sl=True, delta=0.1):
    uid = new_user(f"{nick.lower()}@test.example", CAP)
    with db.tx() as c:
        c.run("UPDATE users SET nickname=:n, leaderboard_opt_in=true WHERE id=:u", n=nick, u=uid)
    with db.tx(uid) as c:
        c.run("UPDATE accounts SET created_at='2026-01-01 00:00+05:30' WHERE user_id=:u", u=uid)
        c.run("INSERT INTO user_levels (user_id, level) VALUES (:u, :l)", u=uid, l=level)
        for i, p in enumerate(pnls, 1):
            c.run("INSERT INTO trade_results (user_id, symbol, expiry, side, strike, short, lots, avg_price, realized_pnl,"
                  " capital, opened_at, closed_at, exit_reason, had_sl, entry_delta) VALUES (:u, 'SBIN', :e, 'CE', 1200,"
                  " true, 1, 5, :p, :c, :t, :t, 'manual', :sl, :d)",
                  u=uid, e=EXP, p=p, c=CAP, t=f"2026-08-{i:02d} 10:00+05:30", sl=sl, d=delta)
    return uid


# 1. Discipline score by hand: 3 of 4 legs by the rules.
rows = [{"had_sl": True, "short": True, "entry_delta": 0.1}, {"had_sl": True, "short": True, "entry_delta": 0.1},
        {"had_sl": True, "short": False, "entry_delta": None}, {"had_sl": False, "short": True, "entry_delta": 0.1}]
check("discipline: share of legs by the rules", leaderboard.discipline(rows) == 75)
check("a high-delta sale isn't disciplined", leaderboard.discipline([{"had_sl": True, "short": True, "entry_delta": 0.2}]) == 0)

# 2. Champion: Lucky ranks first in 4-6 but traded without stops; Steady wins the season.
lucky = person("Lucky", 5, [50000] * 5, sl=False)
steady = person("Steady", 5, [5000] * 5)
leaderboard.finalize(MONTH)
champs = leaderboard.champions(MONTH)
check("best rank with discipline >= 80 wins, not the reckless #1", champs.get("4-6") == steady and lucky not in champs.values(), champs)
board = leaderboard.get(MONTH)
rows46 = next(b for b in board["bands"] if b["band"] == "4-6")["rows"]
check("finalized rows carry discipline and the champion flag",
      [(r["nickname"], r["discipline"], r["champion"]) for r in rows46] == [("Lucky", 0, False), ("Steady", 100, True)], rows46)
check("titles for the champion", leaderboard.titles(steady) == [{"month": MONTH, "band": "Levels 4-6"}], leaderboard.titles(steady))

# 3. Certificate: only the champion can make it.
slug = cards.create(steady, "season", 202608)["slug"]
big, small = cards.headline(cards.get(slug), "X")
check("season certificate", big == "Season champion · August 2026" and "Levels 4-6" in small, (big, small))
try:
    cards.create(lucky, "season", 202608)
    check("non-champion refused", False)
except cards.CardError:
    check("non-champion refused", True)

# 4. Recap email.
s = recap.summary(steady, MONTH)
check("recap numbers", s["trades"] == 5 and s["discipline"] == 100 and s["champion"] == "Levels 4-6", s)
quiet = new_user("quiet@test.example", CAP)
check("nothing to report: no email", recap.summary(quiet, MONTH) is None)
sent = []
mail.send = lambda to, subject, text: sent.append((to, subject, text))
recap.send_all(MONTH)
check("recap sent to people with a month", {t for t, *_ in sent} == {"lucky@test.example", "steady@test.example"}, [t for t, *_ in sent])
check("recap names the title", any("Season champion" in body for *_, body in sent))

# 5. Cohort: everyone here joined this week; Steady and Lucky are Level 5, others 1.
co = cohort.get(quiet)
check("cohort: size and how many are ahead", co["size"] == len(users.active_user_ids()) and co["ahead"] == 2 and co["level"] == 1, co)
check("cohort: counts only, no names", set(co) == {"week", "size", "level", "levels", "ahead"})
check("champion threshold from config", config.CHAMPION_DISCIPLINE == 80)

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
