"""Sign in with Google: off by default, the switch needs the client set, state is one-use and bound
to the browser, the ID token's issuer/audience/expiry/nonce and verified email are checked, a new
mailbox gets an active account, an existing one is linked, and the owner is always refused."""
import base64
import json
import os
import sys
import time
from urllib.parse import parse_qs, urlparse

import server
import support  # noqa: F401  (test DB and Redis)
from engine import app_settings, auth, cache, db, google_auth, users

fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def raises(fn):
    try:
        fn()
    except (auth.AuthError, ValueError) as e:
        return str(e)
    return None


owner = users.create_user("owner@test.example", "Owner", role="owner", status="active")
CID = "cid.apps.googleusercontent.com"

# 1. Off by default, and the switch refuses to turn on without a client.
check("off by default", google_auth.enabled() is False and app_settings.get("google_login") is False)
check("switch needs the client set", "GOOGLE_CLIENT_ID" in (raises(lambda: app_settings.set_value(owner, "google_login", True)) or ""))
check("start refused while off", raises(lambda: google_auth.start(None, "1.2.3.4")) is not None)
os.environ.update(GOOGLE_CLIENT_ID=CID, GOOGLE_CLIENT_SECRET="sec")
app_settings.set_value(owner, "google_login", True)
check("on once the client is set", google_auth.enabled())


class Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body


def token(**claims):
    part = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{part({'alg': 'RS256'})}.{part(claims)}.sig"


answer = {}
google_auth.requests.post = lambda url, data, timeout: Resp({"id_token": token(**answer)})


def sign_in(email, sub, ip="5.6.7.8", device=None, **over):
    url, browser = google_auth.start("", ip)
    q = parse_qs(urlparse(url).query)
    answer.clear()
    answer.update(iss="https://accounts.google.com", aud=CID, exp=time.time() + 300, nonce=q["nonce"][0], sub=sub,
                  email=email, email_verified=True, name="Gita Rao")
    answer.update(over)
    return q, browser, lambda b=browser: google_auth.finish(q["state"][0], "code", b, ip=ip, device=device)


# 2. The redirect carries PKCE and the right redirect URI.
q, browser, go = sign_in("new@test.example", "g-1")
check("PKCE S256 and our callback", q["code_challenge_method"] == ["S256"] and q["redirect_uri"][0].endswith("/auth/google/callback"))

# 3. A forged callback (another browser) fails, and the state is then spent.
check("wrong browser refused", raises(lambda: go("someone-else")) is not None)
check("state is one use", raises(go) is not None)

# 4. A new mailbox: an active, verified account, signed in.
_, _, go = sign_in("new@test.example", "g-1", device="dev-new")
tok, out = go()
with db.tx() as c:
    u = c.one("SELECT id, status, google_sub, email_verified_at, password_hash FROM users WHERE email='new@test.example'")
check("new account active and linked", tok and out["signed_in"] and u["status"] == "active" and u["google_sub"] == "g-1"
      and u["email_verified_at"] and u["password_hash"] is None, u)
check("session works", auth.session_user(tok) == u["id"])

# 5. Bad tokens are refused.
for label, over in (("wrong audience", {"aud": "other"}), ("wrong issuer", {"iss": "evil.example"}),
                    ("expired", {"exp": time.time() - 10}), ("wrong nonce", {"nonce": "x"}),
                    ("unverified email", {"email_verified": False})):
    _, _, go = sign_in("new@test.example", "g-1", **over)
    check(f"{label} refused", raises(go) is not None)

# 6. An existing password account is linked by its verified email.
pid = users.create_user("pw@test.example", "Pw", status="active")
_, _, go = sign_in("pw@test.example", "g-2")
tok, _ = go()
with db.tx() as c:
    linked = c.value("SELECT google_sub FROM users WHERE id=:u", u=pid)
check("existing account linked", tok and linked == "g-2")
_, _, go = sign_in("pw@test.example", "g-other")
check("a second Google account can't take it over", "different Google account" in (raises(go) or ""))

# 7. The owner is always refused, and the same browser can't open a second account.
_, _, go = sign_in("owner@test.example", "g-owner")
check("owner refused", "password" in (raises(go) or ""))
_, _, go = sign_in("another@test.example", "g-3", device=auth._hash("same-browser"))
auth.see_device(pid, auth._hash("same-browser"), None)
check("same browser can't sign up twice", "already has an account" in (raises(go) or ""))

# 8. Approval on: a new Google account waits, no session.
app_settings.set_value(owner, "auto_approve", False)
_, _, go = sign_in("wait@test.example", "g-4")
tok, out = go()
check("waits for approval", tok is None and "approval" in out["message"], out)

# 9. The routes: start sets the browser cookie and goes to Google; the full round trip signs in.
app_settings.set_value(owner, "auto_approve", True)
http = server.app.test_client()
r = http.get("/auth/google/start")
loc = r.headers.get("Location", "")
check("start redirects to Google with the cookie", r.status_code == 303 and loc.startswith(google_auth.AUTH_URL)
      and server.GOOGLE_COOKIE in r.headers.get("Set-Cookie", ""), loc[:60])
q = parse_qs(urlparse(loc).query)
answer.clear()
answer.update(iss="accounts.google.com", aud=CID, exp=time.time() + 300, nonce=q["nonce"][0], sub="g-5",
              email="route@test.example", email_verified=True, name="Route")
r = http.get(f"/auth/google/callback?state={q['state'][0]}&code=c")
check("callback signs in and lands on /", r.status_code == 303 and r.headers["Location"] == "/"
      and any(h.startswith(server.COOKIE + "=") and "Max-Age=0" not in h for h in r.headers.getlist("Set-Cookie")), r.headers["Location"])
r = http.get("/auth/google/callback?error=access_denied")
check("cancel goes back to sign in with a note", r.headers["Location"].startswith("/login?google="), r.headers["Location"])
check("app_info tells the page", server.app_info(None)["google_login"] is True)

# 10. Off again: everything refuses.
app_settings.set_value(owner, "google_login", False)
check("off again", raises(lambda: google_auth.start(None, "1.2.3.4")) is not None)
cache.delete("rl:google:5.6.7.8")

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
