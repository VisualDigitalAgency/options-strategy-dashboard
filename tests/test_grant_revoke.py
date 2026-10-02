"""Revoking a capital grant (issue #194): audited, permanent, and a reset skips it."""
import sys

import server
from engine import capital, coins, config, db, lessons, users, virtual

fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def cap(uid):
    with db.tx(uid) as c:
        return float(c.value("SELECT starting_capital FROM accounts WHERE user_id=:u", u=uid))


owner = users.create_user("grant-owner@test.example", "Owner", role="owner", status="active")
uid = users.create_user("grant-user@test.example", "U", status="active")
reward = config.CAPITAL_TASKS["l1_lessons"][0]
with db.tx(uid) as c:
    for l in lessons.list_lessons():
        if l["level"] == 1:
            c.run("INSERT INTO lesson_progress (user_id, slug, attempts, best_score, passed_at, last_attempt_at) "
                  "VALUES (:u, :s, 1, 100, now(), now())", u=uid, s=l["slug"])
capital.evaluate(uid)
start = cap(uid)
check("the task paid", start == config.STARTING_CAPITAL + reward, start)

g = capital.admin_grants(uid)
check("the owner's view lists it, revocable", len(g) == 1 and g[0]["revocable"] and not g[0]["revoked"]
      and g[0]["amount"] == reward, g)

for bad in ("", "  ", "ab", "x" * 201):
    try:
        capital.revoke(owner, uid, g[0]["id"], bad)
        ok = False
    except capital.GrantError:
        ok = True
    check(f"a reason of {len(bad.strip())} characters is refused", ok)
check("nothing changed after refusals", cap(uid) == start)

r = capital.revoke(owner, uid, g[0]["id"], "invite abuse", ip="203.0.113.5")
check("revoke takes the amount back", cap(uid) == start - reward and r["amount"] == reward, (cap(uid), r))
after = capital.admin_grants(uid)
check("the row stays, marked revoked and not revocable", len(after) == 1 and after[0]["revoked"] and not after[0]["revocable"], after)

try:
    capital.revoke(owner, uid, g[0]["id"], "again please")
    again = False
except capital.GrantError as e:
    again = "Already revoked" in str(e)
check("a second revoke is refused", again and cap(uid) == start - reward)

capital.evaluate(uid)
capital.evaluate(uid)
check("the task is never paid again", cap(uid) == start - reward and len(capital.admin_grants(uid)) == 1, cap(uid))

check("the user's own page shows it as revoked", capital.status(uid)["grants"][0]["revoked"] is True)

virtual.reset(uid)
check("a reset skips the revoked grant", cap(uid) == config.STARTING_CAPITAL, cap(uid))

with db.tx() as c:
    log = c.all("SELECT actor_id, target_user_id, detail FROM audit_log WHERE action='grant_revoked'")
check("audited with who, why and how much", len(log) == 1 and log[0]["actor_id"] == owner and log[0]["target_user_id"] == uid
      and log[0]["detail"]["reason"] == "invite abuse" and log[0]["detail"]["amount"] == reward, log)

# A coin exchange is listed but can't be revoked.
with db.tx(uid) as c:
    c.run("INSERT INTO coin_ledger (user_id, kind, ref, coins) VALUES (:u, 'level', 'seed', 50)", u=uid)
coins.exchange(uid, 10)
ex = [x for x in capital.admin_grants(uid) if x["label"] == "Exchanged coins"]
check("a coin exchange is listed but not revocable", len(ex) == 1 and not ex[0]["revocable"], ex)
try:
    capital.revoke(owner, uid, ex[0]["id"], "trying anyway")
    ok = False
except capital.GrantError as e:
    ok = "coin exchange" in str(e)
check("revoking a coin exchange is refused", ok)

try:
    capital.revoke(owner, uid, 999999, "no such grant")
    ok = False
except capital.GrantError as e:
    ok = "No such grant" in str(e)
check("an unknown grant is refused", ok)

other = users.create_user("grant-other@test.example", "O", status="active")
try:
    capital.revoke(owner, other, ex[0]["id"], "wrong user")
    ok = False
except capital.GrantError:
    ok = True
check("a grant can't be revoked through another user's id", ok)

check("both methods are admin-only and owner-gated", all(m in server.ADMIN_METHODS and server.REQUIRES[m] == "owner"
      for m in ("admin_user_grants", "admin_revoke_grant")))

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
