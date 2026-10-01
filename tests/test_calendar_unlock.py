"""Market Calendar is the Level 3 unlock (issue #165); migration 0021 keeps it for existing accounts."""
import sys

from engine import db, permissions, users

fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


check("roles no longer grant it", "market_calendar" not in permissions.features_for("user")
      and "market_calendar" not in permissions.features_for("beta"))
uid = users.create_user("cal@test.example", "Cal", status="active")
check("new account at Level 1: locked", "market_calendar" not in permissions.user_features(uid, "user"))
with db.tx(uid) as c:
    c.run("INSERT INTO user_levels (user_id, level, level_since) VALUES (:u, 3, now()) "
          "ON CONFLICT (user_id) DO UPDATE SET level = 3", u=uid)
check("Level 3: unlocked", "market_calendar" in permissions.user_features(uid, "user"))

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
