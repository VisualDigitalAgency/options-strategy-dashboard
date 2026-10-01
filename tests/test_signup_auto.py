"""Sign-ups without the manual-approval wall (issue #121): with auto_approve on, confirming the
email activates the account and signs it in; off, it waits as before. Only the owner flips the
switch, and it is audited. First-login onboarding sets a unique nickname and leaderboard opt-in."""
import sys

import server
from engine import app_settings, auth, db, mail, users

ORIGIN = "https://t.example"
server.ALLOWED_ORIGINS = {ORIGIN}
server.universe = lambda: ["SBIN"]
fails = []
codes = {}


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def fake_send(to, subject, text):
    codes[to] = subject.split()[0]


mail.send = fake_send
_ip = iter(f"10.2.0.{i}" for i in range(1, 250))


def client():
    c = server.app.test_client()
    ip = next(_ip)

    def call(method, params=None):
        r = c.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                   headers={"Origin": ORIGIN}, environ_base={"REMOTE_ADDR": ip})
        return r.get_json()
    return call


def sign_up(call, email, name):
    r = call("auth_register", {"name": name, "email": email, "password": "correct-horse-battery-9"})
    assert "result" in r, r
    return call("auth_verify_email", {"email": email, "code": codes[email]})


def status(email):
    with db.tx() as c:
        return c.value("SELECT status FROM users WHERE email=:e", e=email)


# 1. Default is on: confirming the email activates the account and signs it in.
check("auto_approve defaults to on", app_settings.get("auto_approve") is True)
a = client()
r = sign_up(a, "asha@test.example", "Asha")["result"]
check("confirmed -> active and signed in", r.get("signed_in") and r["user"]["status"] == "active"
      and status("asha@test.example") == "active", r)
me = a("auth_me")["result"]
check("same browser is signed in straight away", me and me["email"] == "asha@test.example", me)
check("new account starts as a plain user", me["role"] == "user" and me["nickname"] is None and not me["leaderboard_opt_in"])
with db.tx() as c:
    acts = [r["action"] for r in c.all("SELECT action FROM audit_log WHERE target_user_id=:u ORDER BY id", u=me["id"])]
check("audited as auto-approved, then signed in", acts[-3:] == ["email_verified", "user_active", "login"], acts)

# 2. Onboarding: nickname rules and leaderboard opt-in.
r = a("profile_set", {"nickname": "no", "leaderboard_opt_in": True})
check("nickname too short refused", "3 to 20" in r.get("error", {}).get("message", ""), r)
r = a("profile_set", {"nickname": "bad name!"})
check("nickname with spaces refused", "error" in r, r)
r = a("profile_set", {"nickname": "ThetaAsha", "leaderboard_opt_in": True})["result"]
check("nickname and opt-in saved", r["nickname"] == "ThetaAsha" and r["leaderboard_opt_in"], r)
b = client()
sign_up(b, "ravi@test.example", "Ravi")
r = b("profile_set", {"nickname": "thetaasha"})
check("nickname unique ignoring case", r.get("error", {}).get("message") == "That nickname is taken", r)
r = b("profile_set", {"leaderboard_opt_in": False})["result"]
check("opt-in alone leaves nickname unset", r["nickname"] is None and not r["leaderboard_opt_in"], r)

# 3. Only the owner can flip the switch; it is audited and applies at once.
owner = users.create_user("owner@test.example", "Owner", role="owner", status="active")
tok = auth.new_session(owner, "10.2.1.1", "ua")
oc = server.app.test_client()
oc.set_cookie(server.COOKIE, tok, domain="localhost")


def owner_call(method, params=None):
    return oc.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                   headers={"Origin": ORIGIN}, environ_base={"REMOTE_ADDR": "10.2.1.1"}).get_json()


r = a("admin_set_setting", {"key": "auto_approve", "value": False})
check("a plain user can't change settings", r.get("error", {}).get("code") == server.FORBIDDEN, r)
r = owner_call("admin_set_setting", {"key": "nope", "value": True})
check("unknown setting refused", "Unknown setting" in r.get("error", {}).get("message", ""), r)
r = owner_call("admin_set_setting", {"key": "auto_approve", "value": False})
check("owner turns auto-approve off", "result" in r and r["result"][0]["value"] is False, r)
with db.tx() as c:
    log = c.one("SELECT actor_id, detail FROM audit_log WHERE action='setting_changed' ORDER BY id DESC LIMIT 1")
check("setting change audited", log and log["actor_id"] == owner and log["detail"]["value"] is False, log)

# 4. Off: back to manual approval, not signed in.
c3 = client()
r = sign_up(c3, "meera@test.example", "Meera")["result"]
check("off -> pending, not signed in", not r.get("signed_in") and status("meera@test.example") == "pending"
      and c3("auth_me")["result"] is None, r)

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
