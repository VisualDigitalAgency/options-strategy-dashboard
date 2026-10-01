"""Referral links (issue #126, part C): one stable invite code per user, made on first use;
sign-ups through it are attributed (a wrong code is ignored, never blocks); only confirmed
accounts count; the admin list shows who invited whom; share cards link to sign-up with the
sharer's code; clients can't read or set anyone else's."""
import os
import sys

import server
from engine import auth, cards, db, mail
from support import new_user

ORIGIN = "https://t.example"
os.environ["PUBLIC_URL"] = "https://theta.example"
server.ALLOWED_ORIGINS = {ORIGIN}
fails = []
codes = {}


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


mail.send = lambda to, subject, text: codes.__setitem__(to, subject.split()[0])
_ip = iter(f"10.3.0.{i}" for i in range(1, 250))


def client(uid=None):
    c = server.app.test_client()
    ip = next(_ip)
    if uid:
        c.set_cookie(server.COOKIE, auth.new_session(uid, ip, "t"), domain="localhost")

    def call(method, params=None):
        return c.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                      headers={"Origin": ORIGIN}, environ_base={"REMOTE_ADDR": ip}).get_json()
    return call


def referred_by(email):
    with db.tx() as c:
        return c.value("SELECT referred_by FROM users WHERE email=:e", e=email)


inviter = new_user("inviter@test.example", 1_000_000)
r = client(inviter)("referral_get")["result"]
check("invite link uses the public URL and the code", r["url"] == f"https://theta.example/register?ref={r['code']}" and len(r["code"]) == 8, r)
check("code is stable", client(inviter)("referral_get")["result"]["code"] == r["code"])
check("nobody joined yet", r["joined"] == 0)

# Sign-ups.
call = client()
call("auth_register", {"name": "Friend One", "email": "f1@test.example", "password": "correct-horse-battery-9", "ref": r["code"]})
check("sign-up through the link is attributed", referred_by("f1@test.example") == inviter)
check("unconfirmed sign-ups don't count yet", client(inviter)("referral_get")["result"]["joined"] == 0)
call("auth_verify_email", {"email": "f1@test.example", "code": codes["f1@test.example"]})
check("confirmed sign-up counts", client(inviter)("referral_get")["result"]["joined"] == 1)
res = client()("auth_register", {"name": "Friend Two", "email": "f2@test.example", "password": "correct-horse-battery-9", "ref": "nope"})
check("a wrong code never blocks sign-up", "result" in res and referred_by("f2@test.example") is None, res)
client()("auth_register", {"name": "Friend Three", "email": "f3@test.example", "password": "correct-horse-battery-9"})
check("no code, no referrer", referred_by("f3@test.example") is None)

# Admin view.
rows = {u["email"]: u for u in auth.list_users()}
check("admin sees who invited whom", rows["f1@test.example"]["referred_by_name"] and rows["inviter@test.example"]["referrals"] == 1,
      {k: (v["referred_by_name"], v["referrals"]) for k, v in rows.items()})

# Cards carry the sharer's code.
with db.tx(inviter) as c:
    c.run("INSERT INTO user_levels (user_id) VALUES (:u)", u=inviter)
slug = cards.create(inviter, "level", 1)["slug"]
html = server.app.test_client().get(f"/c/{slug}").get_data(as_text=True)
check("card page sign-up link carries the sharer's code", f"/register?ref={r['code']}" in html)

# Guard.
res = client(inviter)("referral_get", {"user_id": 1})
check("client can't ask for someone else's link", "error" in res, res)

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
