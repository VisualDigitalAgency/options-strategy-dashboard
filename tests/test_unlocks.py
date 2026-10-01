"""Levels unlock features, owner overrides per user, and the Level 6 Beta promotion (issue #123).
Role + level + overrides decide access on the server; levels never grant real trading or admin
powers; only `beta` is ever assigned automatically, once, and a manual demotion sticks."""
import sys
from datetime import datetime, timedelta, timezone

import server
from engine import auth, config, db, permissions, progress, users

ORIGIN = "https://t.example"
server.ALLOWED_ORIGINS = {ORIGIN}
server.universe = lambda: ["SBIN"]
fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def as_user(uid):
    c = server.app.test_client()
    c.set_cookie(server.COOKIE, auth.new_session(uid, "10.0.0.5", "ua"), domain="localhost")
    return lambda m, p=None: c.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": m, "params": p or {}},
                                    headers={"Origin": ORIGIN}).get_json()


def set_level(uid, level):
    with db.tx(uid) as c:
        c.run("INSERT INTO user_levels (user_id, level) VALUES (:u, :l) ON CONFLICT (user_id) DO UPDATE SET level=:l",
              u=uid, l=level)


def feats(uid):
    with db.tx() as c:
        role = c.value("SELECT role FROM users WHERE id=:u", u=uid)
    return set(permissions.user_features(uid, role))


owner = users.create_user("owner@test.example", "Owner", role="owner", status="active")
learner = users.create_user("learner@test.example", "Learner", status="active")
O, L = as_user(owner), as_user(learner)

# A shipped feature to unlock by level (the planned ones don't exist yet): the Market Calendar,
# switched off for the User role. live_trading is listed too, to prove levels can never grant it.
config.LEVEL_FEATURES = {2: ("market_calendar", "live_trading", "not_shipped_yet")}
O("admin_set_feature", {"role": "user", "feature": "market_calendar", "enabled": False})

# 1. Level unlocks, applied by the server's own check.
set_level(learner, 1)
check("Level 1: calendar locked", "market_calendar" not in feats(learner))
check("server refuses it at Level 1", L("get_market_calendar").get("error", {}).get("code") == server.FORBIDDEN)
set_level(learner, 2)
check("Level 2 unlocks it with no owner action", "market_calendar" in feats(learner))
check("server allows it at Level 2", L("get_market_calendar").get("error", {}).get("code") != server.FORBIDDEN)
check("auth_me lists level features", "market_calendar" in L("auth_me")["result"]["features"])
check("a level never grants live trading", "live_trading" not in feats(learner))
check("unknown future features are ignored", "not_shipped_yet" not in feats(learner))

# 2. Owner overrides.
r = O("admin_set_override", {"target_id": learner, "feature": "market_calendar", "mode": "deny"})
check("deny beats the level unlock", "result" in r and "market_calendar" not in feats(learner), r)
O("admin_set_override", {"target_id": learner, "feature": "market_calendar", "mode": "clear"})
check("clear goes back to role + level", "market_calendar" in feats(learner))
set_level(learner, 1)
O("admin_set_override", {"target_id": learner, "feature": "market_calendar", "mode": "grant"})
check("grant works below the required level", "market_calendar" in feats(learner))
r = O("admin_get_overrides", {"target_id": learner})["result"]
check("overrides listed", [(x["feature"], x["mode"]) for x in r] == [("market_calendar", "grant")], r)
r = L("admin_set_override", {"target_id": learner, "feature": "autotrade", "mode": "deny"})
check("only the owner sets overrides", r.get("error", {}).get("code") == server.FORBIDDEN, r)
r = O("admin_set_override", {"target_id": owner, "feature": "autotrade", "mode": "deny"})
check("the owner can't be overridden", "every feature" in r.get("error", {}).get("message", ""), r)
r = O("admin_set_override", {"target_id": learner, "feature": "nope", "mode": "grant"})
check("unknown feature refused", "Unknown feature" in r.get("error", {}).get("message", ""), r)
with db.tx() as c:
    acts = [x["action"] for x in c.all("SELECT action FROM audit_log WHERE action LIKE 'override_%' ORDER BY id")]
check("overrides audited", acts == ["override_deny", "override_clear", "override_grant"], acts)

# 3. Level 6 promotes user -> beta, once, audited.
config.BETA_LEVEL = 6
climber = users.create_user("climber@test.example", "Climber", status="active")
set_level(climber, 6)
progress.evaluate(climber, _now=datetime.now(timezone.utc) + timedelta(days=1))
with db.tx() as c:
    role = c.value("SELECT role FROM users WHERE id=:u", u=climber)
    log = c.one("SELECT detail FROM audit_log WHERE action='role_changed' AND target_user_id=:u", u=climber)
check("Level 6 user becomes beta", role == "beta", role)
check("promotion audited as automatic", log and log["detail"] == {"was": "user", "role": "beta", "auto": True, "level": 6}, log)
O("admin_set_role", {"target_id": climber, "role": "user"})
progress.evaluate(climber, _now=datetime.now(timezone.utc) + timedelta(days=2))
with db.tx() as c:
    role = c.value("SELECT role FROM users WHERE id=:u", u=climber)
check("owner's demotion sticks", role == "user", role)

# 4. Never above Beta, and never touching other roles.
sub = users.create_user("sub@test.example", "Sub", role="sub_admin", status="active")
set_level(sub, 9)
progress.evaluate(sub, _now=datetime.now(timezone.utc) + timedelta(days=1))
with db.tx() as c:
    role = c.value("SELECT role FROM users WHERE id=:u", u=sub)
check("a sub-admin is left alone", role == "sub_admin", role)
for bad in ("sub_admin", "owner", "user"):
    try:
        auth.auto_promote(learner, bad, 9)
        check(f"auto_promote refuses {bad}", False)
    except ValueError:
        check(f"auto_promote refuses {bad}", True)
check("a direct auto_promote to beta still only touches `user` accounts", auth.auto_promote(sub, "beta", 9) is False)

# Coin store (#175): off for every role by default, and no level ever unlocks it.
check("coin store off for every toggled role", not any("coin_store" in permissions.features_for(r)
                                                        for r in permissions.TOGGLED_ROLES))
check("no level unlocks the coin store", "coin_store" not in permissions.level_features(10))
with db.tx() as c:
    c.run("UPDATE role_features SET enabled=true WHERE role='user' AND feature='coin_store'")
shop = users.create_user("shop@test.example", "Shop", status="active")
check("role on, Level 1: still no coin store", "coin_store" not in permissions.user_features(shop, "user"))
check("role on, Level 1: shown locked with its level", auth.me(shop)["level_locked"] == {"coin_store": 4})
with db.tx(shop) as c:
    c.run("INSERT INTO user_levels (user_id, level, level_since) VALUES (:u, 4, now()) "
          "ON CONFLICT (user_id) DO UPDATE SET level = 4", u=shop)
check("role on, Level 4: coin store", "coin_store" in permissions.user_features(shop, "user"))
check("unlocked: no longer listed as locked", auth.me(shop)["level_locked"] == {})
with db.tx() as c:
    c.run("UPDATE role_features SET enabled=false WHERE role='user' AND feature='coin_store'")
check("role off, Level 4: no coin store", "coin_store" not in permissions.user_features(shop, "user"))

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
