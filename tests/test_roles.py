"""Roles and owner-managed feature toggles (issue #46): one owner, rank rules for sub-admins,
owner-only toggles, server-side gating that follows a toggle at once, and audit entries."""
import sys

from sqlalchemy.exc import IntegrityError

import server
from engine import auth, db, permissions, users

ORIGIN = "https://t.example"
server.ALLOWED_ORIGINS = {ORIGIN}
server.universe = lambda: ["SBIN"]
fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def as_user(uid):
    token = auth.new_session(uid, "10.0.0.9", "ua")

    def call(method, params=None):
        c = server.app.test_client()
        c.set_cookie(server.COOKIE, token, domain="localhost")
        r = c.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                   headers={"Origin": ORIGIN}, environ_base={"REMOTE_ADDR": "10.0.0.9"})
        return r.get_json()
    return call


def ok(r):
    return "result" in r


def audits(action):
    with db.tx() as c:
        return c.all("SELECT actor_id, target_user_id, detail FROM audit_log WHERE action=:a ORDER BY id", a=action)


owner = users.create_user("owner@test.example", "Owner", role="owner", status="active")
sub = users.create_user("sub@test.example", "Sub", role="sub_admin", status="active")
sub2 = users.create_user("sub2@test.example", "Sub Two", role="sub_admin", status="active")
beta = users.create_user("beta@test.example", "Beta", role="beta", status="active")
plain = users.create_user("user@test.example", "User", status="active")
O, S, B, U = as_user(owner), as_user(sub), as_user(beta), as_user(plain)

# 1. Exactly one owner; nobody can be made owner.
try:
    users.create_user("owner2@test.example", "Owner Two", role="owner", status="active")
    check("database refuses a second owner", False)
except IntegrityError:
    check("database refuses a second owner", True)
r = O("admin_set_role", {"target_id": sub, "role": "owner"})
check("owner role can't be granted", not ok(r), r)
check("bootstrap never adds a second owner", users.bootstrap_local_user() == owner)

# 2. Seeded defaults match the old behaviour; me() carries the features.
check("owner has every feature", set(O("auth_me")["result"]["features"]) == set(permissions.FEATURES))
check("sub-admin starts without live trading",
      set(S("auth_me")["result"]["features"]) == {"manage_users", "manage_roles", "screener", "autotrade", "market_calendar"})
check("beta has the screener", "screener" in B("auth_me")["result"]["features"])
# Pro (#136): a plain user has no screener, so no auto-trade either (it trades the screen's picks).
check("user starts with the calendar only", set(U("auth_me")["result"]["features"]) == {"market_calendar"})
r = U("get_screened_candidates")
check("user can't read the screen", r.get("error", {}).get("code") == server.FORBIDDEN, r)
r = U("get_trade_detail", {"symbol": "SBIN"})
check("user can't open a stock analysis", r.get("error", {}).get("code") == server.FORBIDDEN, r)
O("admin_set_override", {"target_id": plain, "feature": "screener", "mode": "grant"})
check("granting Pro brings the screener and auto-trade", {"screener", "autotrade"} <= set(U("auth_me")["result"]["features"]))
O("admin_set_override", {"target_id": plain, "feature": "screener", "mode": "clear"})
check("removing Pro takes both away", not {"screener", "autotrade"} & set(U("auth_me")["result"]["features"]))

# 3. Admin methods follow manage_users, not a hard-coded role.
check("sub-admin lists users", ok(S("admin_list_users")))
r = U("admin_list_users")
check("user can't list users", r.get("error", {}).get("code") == server.FORBIDDEN, r)
r = B("broker_connect_url")
check("beta can't connect a broker by default", r.get("error", {}).get("code") == server.FORBIDDEN, r)
check("nobody can call owner-only toggles but the owner",
      all(f("admin_get_features").get("error", {}).get("code") == server.FORBIDDEN for f in (S, B, U)))

# 4. Rank rules.
r = S("admin_set_status", {"target_id": owner, "status": "disabled"})
check("sub-admin can't disable the owner", not ok(r), r)
r = S("admin_set_status", {"target_id": sub2, "status": "disabled"})
check("sub-admin can't disable another sub-admin", not ok(r), r)
r = S("admin_reset_password", {"target_id": sub2})
check("sub-admin can't reset another sub-admin's password", not ok(r), r)
r = S("admin_set_role", {"target_id": plain, "role": "sub_admin"})
check("sub-admin can't grant sub-admin", not ok(r), r)
r = S("admin_set_role", {"target_id": sub2, "role": "user"})
check("sub-admin can't demote a sub-admin", not ok(r), r)
r = S("admin_set_role", {"target_id": plain, "role": "beta"})
check("sub-admin moves user to beta", ok(r) and r["result"]["role"] == "beta", r)
r = S("admin_set_role", {"target_id": plain, "role": "user"})
check("...and back", ok(r), r)
r = O("admin_set_role", {"target_id": owner, "role": "user"})
check("owner can't change own role", not ok(r), r)
r = O("admin_set_role", {"target_id": sub2, "role": "user"})
check("owner demotes a sub-admin", ok(r), r)
r = O("admin_set_role", {"target_id": sub2, "role": "sub_admin"})
check("owner grants sub-admin", ok(r), r)
changes = audits("role_changed")
check("role changes audited with actor and old role",
      len(changes) == 4 and changes[0]["actor_id"] == sub and changes[0]["detail"] == {"was": "user", "role": "beta"}, changes)

# 5. Toggles: owner-only, audited, applied on the next request.
r = S("admin_set_feature", {"role": "beta", "feature": "live_trading", "enabled": True})
check("sub-admin can't flip toggles", r.get("error", {}).get("code") == server.FORBIDDEN, r)
r = O("admin_set_feature", {"role": "owner", "feature": "live_trading", "enabled": False})
check("owner's own features can't be toggled", not ok(r), r)
r = O("admin_set_feature", {"role": "beta", "feature": "nope", "enabled": True})
check("unknown feature refused", not ok(r), r)
r = O("admin_set_feature", {"role": "beta", "feature": "live_trading", "enabled": True})
check("owner turns live trading on for beta", ok(r) and r["result"]["matrix"]["beta"]["live_trading"], r)
check("beta sees it at once", "live_trading" in B("auth_me")["result"]["features"])
r = B("broker_connect_url")
check("beta passes the live-trading gate now", r.get("error", {}).get("code") != server.FORBIDDEN, r)
check("toggle audited", audits("feature_on")[-1]["detail"] == {"role": "beta", "feature": "live_trading"}, audits("feature_on"))

O("admin_set_feature", {"role": "user", "feature": "market_calendar", "enabled": False})
r = U("get_market_calendar")
check("calendar off for users -> refused", r.get("error", {}).get("code") == server.FORBIDDEN, r)
check("...beta still has it", B("get_market_calendar").get("error", {}).get("code") != server.FORBIDDEN)

O("admin_set_feature", {"role": "sub_admin", "feature": "manage_users", "enabled": False})
r = S("admin_list_users")
check("manage_users off -> sub-admin loses the admin page", r.get("error", {}).get("code") == server.FORBIDDEN, r)

O("admin_set_feature", {"role": "user", "feature": "autotrade", "enabled": False})
r = U("va_set_autotrade", {"enabled": True})
check("autotrade off -> settings refused", r.get("error", {}).get("code") == server.FORBIDDEN, r)
check("scheduler gate agrees", not permissions.allowed("user", "autotrade") and permissions.allowed("owner", "autotrade"))

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
