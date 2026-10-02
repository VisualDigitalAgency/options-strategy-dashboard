"""Strategy gate (issue #170): spreads and condors first, a single unprotected sale from Level 3,
a strangle from Level 5. Closing is never blocked; the owner and Pro accounts are not gated."""
import sys

from engine import auth, config, db, users, virtual

fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def f(side, strike, action, lots=1):
    return {"side": side, "strike": float(strike), "action": action, "qty": lots * 100, "price": 5.0}


def held(side, strike, qty):
    return {"side": side, "strike": float(strike), "qty": qty, "avg_price": 5.0}


def at_level(email, level, role="user"):
    uid = users.create_user(email, "G", role=role, status="active")
    with db.tx(uid) as c:
        c.run("INSERT INTO user_levels (user_id, level, level_since) VALUES (:u, :l, now()) "
              "ON CONFLICT (user_id) DO UPDATE SET level = :l", u=uid, l=level)
    return uid


rule = virtual._strategy_rule
l1, l3, l5 = at_level("g1@test.example", 1), at_level("g3@test.example", 3), at_level("g5@test.example", 5)
spread = [f("PE", 900, "SELL"), f("PE", 880, "BUY")]
condor = spread + [f("CE", 1100, "SELL"), f("CE", 1120, "BUY")]
strangle = [f("PE", 900, "SELL"), f("CE", 1100, "SELL")]

check("Level 1: credit spread allowed", rule(l1, [], spread) is None)
check("Level 1: iron condor allowed", rule(l1, [], condor) is None)
r = rule(l1, [], [f("PE", 900, "SELL")])
check("Level 1: a naked sale refused, with the unlock level", r and f"Level {config.NAKED_LEVEL}" in r, r)
check("Level 1: a bought leg on the wrong side doesn't protect", rule(l1, [], [f("PE", 900, "SELL"), f("PE", 920, "BUY")]))
check("Level 1: fewer bought lots than sold doesn't protect", rule(l1, [], [f("PE", 900, "SELL", 2), f("PE", 880, "BUY", 1)]))
check("Level 1: a sale protected by a leg already held is allowed", rule(l1, [held("PE", 880, 100)], [f("PE", 900, "SELL")]) is None)
check("Level 1: closing a naked leg is never blocked", rule(l1, [held("PE", 900, -100)], [f("PE", 900, "BUY")]) is None)
check("Level 3: a single naked sale allowed", rule(l3, [], [f("CE", 1100, "SELL")]) is None)
r = rule(l3, [], strangle)
check("Level 3: a strangle refused", r and f"Level {config.STRANGLE_LEVEL}" in r, r)
check("Level 3: adding the second naked side to a held one refused", rule(l3, [held("PE", 900, -100)], [f("CE", 1100, "SELL")]))
check("Level 5: a strangle allowed", rule(l5, [], strangle) is None)
owner = at_level("go@test.example", 1, role="owner")
check("owner not gated", rule(owner, [], strangle) is None)
beta = at_level("gb@test.example", 1, role="beta")  # beta has the screener (Pro)
check("Pro account not gated (the screener suggests strangles)", rule(beta, [], strangle) is None)

# auth_me tells the builder which templates to lock: only while the gate applies.
check("auth_me: Level 1 gets the unlock levels", auth.me(l1)["sell_levels"] == {"naked": config.NAKED_LEVEL, "strangle": config.STRANGLE_LEVEL},
      auth.me(l1)["sell_levels"])
check("auth_me: Level 5, owner and Pro get none", all(auth.me(u)["sell_levels"] is None for u in (l5, owner, beta)))

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
