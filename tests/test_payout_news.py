"""Payout toast feed (issue #192): what paid out since the last clock this browser saw."""
import sys

from engine import capital, config, db, lessons, users

fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


uid = users.create_user("news@test.example", "News", status="active")
first = capital.news(uid)
check("no clock yet: nothing replayed, only the clock", first["items"] == [] and first["now"].endswith("Z"), first)

check("nothing new since the clock", capital.news(uid, first["now"])["items"] == [])

with db.tx(uid) as c:
    for l in lessons.list_lessons():
        if l["level"] == 1:
            c.run("INSERT INTO lesson_progress (user_id, slug, attempts, best_score, passed_at, last_attempt_at) "
                  "VALUES (:u, :s, 1, 100, now(), now())", u=uid, s=l["slug"])
got = capital.news(uid, first["now"])
cap_items = [i for i in got["items"] if i["kind"] == "capital"]
coin_items = [i for i in got["items"] if i["kind"] == "coins"]
check("a newly passed task shows as capital and as coins (it pays both)",
      [i["amount"] for i in cap_items] == [config.CAPITAL_TASKS["l1_lessons"][0]]
      and [i["amount"] for i in coin_items] == [config.COIN_TASKS["l1_lessons"][0]], got["items"])
check("labelled with the task", cap_items[0]["label"] == capital.LABELS["l1_lessons"] and coin_items[0]["label"] == capital.LABELS["l1_lessons"])
check("clock moves forward", got["now"] > first["now"])

again = capital.news(uid, got["now"])
check("each payout is shown once", again["items"] == [], again["items"])

# An exchange is the user's own doing: neither the coin debit nor its capital grant is news.
from engine import coins  # noqa: E402
coins.exchange(uid, 5)
check("a coin exchange is not news", capital.news(uid, got["now"])["items"] == [])

with db.tx(uid) as c:
    c.run("INSERT INTO coin_ledger (user_id, kind, ref, coins) VALUES (:u, 'level', '2', :n)", u=uid, n=config.COIN_LEVEL[2])
lv = capital.news(uid, got["now"])["items"]
check("a level reward reads 'Reach Level N'", any(i["kind"] == "coins" and i["label"] == "Reach Level 2" for i in lv), lv)

try:
    capital.news(uid, "yesterday")
    bad = False
except ValueError as e:
    bad = "Bad time" in str(e)
check("a bad clock is refused", bad)

other = users.create_user("news2@test.example", "Other", status="active")
check("another user sees none of it", capital.news(other, first["now"])["items"] == [])

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
