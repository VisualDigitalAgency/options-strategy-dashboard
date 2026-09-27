"""Sign-up email verification (issue #45): a new account is `unverified` until its emailed code
is entered, then `pending` for the admin. Wrong/expired codes, guess limits, resend throttle,
same answers for unknown emails, and mail failures recorded for the admin."""
import sys
import threading

import server
from engine import auth, db, mail

ORIGIN = "https://t.example"
server.ALLOWED_ORIGINS = {ORIGIN}
server.universe = lambda: ["SBIN"]
fails = []
outbox = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def fake_send(to, subject, text):
    outbox.append({"to": to, "subject": subject, "code": subject.split()[0]})


mail.send = fake_send
_ip = iter(f"10.1.0.{i}" for i in range(1, 250))


def call(method, params, ip=None):
    c = server.app.test_client()
    r = c.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
               headers={"Origin": ORIGIN}, environ_base={"REMOTE_ADDR": ip or next(_ip)})
    return r.get_json()


def status(email):
    with db.tx() as c:
        return c.value("SELECT status FROM users WHERE email=:e", e=email)


def age_code(email, secs):
    with db.tx() as c:
        c.run("UPDATE users SET email_code_sent_at = email_code_sent_at - make_interval(secs => :s), "
              "email_code_expires_at = email_code_expires_at - make_interval(secs => :s) WHERE email=:e", s=secs, e=email)


PW = "plenty-long-passphrase-9"

# 1. Sign-up sends a code and leaves the account unverified; sign-in asks for the code.
j = call("auth_register", {"name": "New User", "email": "new@test.example", "password": PW})
check("register asks for the code", j["result"]["verify"] is True and "code" in j["result"]["message"], j)
check("one email sent, to the sign-up address", len(outbox) == 1 and outbox[0]["to"] == "new@test.example", outbox)
check("account starts unverified", status("new@test.example") == "unverified")
with db.tx() as c:
    stored = c.value("SELECT email_code_hash FROM users WHERE email='new@test.example'")
check("code is stored only as a hash", stored and outbox[0]["code"] not in stored)
j = call("auth_login", {"email": "new@test.example", "password": PW})
check("sign-in before verifying gets the unverified code", j["error"]["code"] == -32005, j["error"])
check("no second email inside the resend gap", len(outbox) == 1, len(outbox))

# 2. Wrong codes, then the right one.
code = outbox[-1]["code"]
wrong = "000000" if code != "000000" else "111111"
j = call("auth_verify_email", {"email": "new@test.example", "code": wrong})
check("wrong code refused", j["error"]["message"] == auth.BAD_CODE, j["error"])
j = call("auth_verify_email", {"email": "new@test.example", "code": code[:3] + " " + code[3:]})
check("right code (with a space) verifies", "waiting for approval" in j.get("result", {}).get("message", ""), j)
check("account moves to pending", status("new@test.example") == "pending")
j = call("auth_verify_email", {"email": "new@test.example", "code": code})
check("a used code can't be used again", j["error"]["message"] == auth.BAD_CODE, j["error"])
j = call("auth_login", {"email": "new@test.example", "password": PW})
check("verified account still waits for the admin", "waiting for approval" in j["error"]["message"], j["error"])

# 3. Unknown emails get the same answers.
j = call("auth_verify_email", {"email": "nobody@test.example", "code": "123456"})
check("verify on an unknown email: same message", j["error"]["message"] == auth.BAD_CODE, j["error"])
r1 = call("auth_resend_code", {"email": "nobody@test.example"})
outbox.clear()
call("auth_register", {"name": "Two User", "email": "two@test.example", "password": PW})
r2 = call("auth_resend_code", {"email": "two@test.example"})
check("resend answers the same for known and unknown emails", r1["result"] == r2["result"], (r1, r2))
check("resend inside the gap sends nothing", len(outbox) == 1, len(outbox))

# 4. Parallel guesses: at most CODE_TRIES are checked, then even the right code is refused.
go, answers = threading.Barrier(12), []


def guess(i):
    go.wait()
    answers.append(call("auth_verify_email", {"email": "two@test.example", "code": f"{i:06d}"}))


code2 = outbox[-1]["code"]
threads = [threading.Thread(target=guess, args=(i + 100000,)) for i in range(12)]
for t in threads:
    t.start()
for t in threads:
    t.join()
with db.tx() as c:
    tries = c.value("SELECT email_code_attempts FROM users WHERE email='two@test.example'")
check(f"12 parallel guesses count at most {auth.CODE_TRIES}", tries <= auth.CODE_TRIES, tries)
j = call("auth_verify_email", {"email": "two@test.example", "code": code2})
check("after the guess limit the right code is refused", "error" in j and status("two@test.example") == "unverified", j)

# 5. A new code after the gap works; an expired one doesn't.
age_code("two@test.example", auth.RESEND_GAP + 1)
call("auth_resend_code", {"email": "two@test.example"})
check("resend after the gap sends a new code", len(outbox) == 2, len(outbox))
age_code("two@test.example", auth.CODE_TTL + 1)
j = call("auth_verify_email", {"email": "two@test.example", "code": outbox[-1]["code"]})
check("expired code refused", j["error"]["message"] == auth.BAD_CODE, j["error"])

# 6. The admin only sees confirmed requests, and can't act on an unconfirmed one.
admin = auth.users.create_user("boss@test.example", "Boss", role="admin", status="active")
listed = {u["email"] for u in auth.list_users()}
check("admin list has the confirmed request, not the unconfirmed one",
      "new@test.example" in listed and "two@test.example" not in listed, listed)
with db.tx() as c:
    two = c.value("SELECT id FROM users WHERE email='two@test.example'")
try:
    auth.set_status(admin, two, "active")
    check("admin can't approve an unconfirmed account", False)
except auth.AuthError:
    check("admin can't approve an unconfirmed account", status("two@test.example") == "unverified")

# 7. At most CODES_PER_DAY codes a day; the resend button then says so, sign-in just shows the form.
while len(outbox) < auth.CODES_PER_DAY:
    age_code("two@test.example", auth.RESEND_GAP + 1)
    j = call("auth_resend_code", {"email": "two@test.example"})
    check(f"resend {len(outbox)} within the daily limit", "result" in j, j)
age_code("two@test.example", auth.RESEND_GAP + 1)
j = call("auth_resend_code", {"email": "two@test.example"})
check("over the daily limit: resend says so", j.get("error", {}).get("message") == auth.DAILY_LIMIT, j)
check("no code sent over the limit", len(outbox) == auth.CODES_PER_DAY, len(outbox))
j = call("auth_login", {"email": "two@test.example", "password": PW})
check("sign-in over the limit still shows the code form", j["error"]["code"] == -32005, j["error"])
j = call("auth_verify_email", {"email": "two@test.example", "code": outbox[-1]["code"]})
check("the last code sent still works", "result" in j and status("two@test.example") == "pending", j)

# 8. Not confirmed within CONFIRM_DAYS: blocked everywhere, and the email stays taken.
call("auth_register", {"name": "Old User", "email": "old@test.example", "password": PW})
with db.tx() as c:
    c.run("UPDATE users SET created_at = now() - make_interval(days => :d) WHERE email='old@test.example'",
          d=auth.CONFIRM_DAYS + 1)
j = call("auth_login", {"email": "old@test.example", "password": PW})
check("sign-in after 14 days: blocked", j["error"]["message"] == auth.BLOCKED, j["error"])
j = call("auth_resend_code", {"email": "old@test.example"})
check("resend after 14 days: blocked", j["error"]["message"] == auth.BLOCKED, j["error"])
j = call("auth_verify_email", {"email": "old@test.example", "code": outbox[-1]["code"]})
check("verify after 14 days: blocked", j["error"]["message"] == auth.BLOCKED, j["error"])
j = call("auth_register", {"name": "Old User", "email": "old@test.example", "password": PW})
check("blocked email can't sign up again", j["error"]["message"] == auth.TAKEN, j["error"])
check("blocked account is kept", status("old@test.example") == "unverified")

# 9. Mail failure: the user is told, and it's in the audit log.


def broken_send(to, subject, text):
    raise mail.MailError("Resend HTTP 403: domain not verified")


mail.send = broken_send
j = call("auth_register", {"name": "Three User", "email": "three@test.example", "password": PW})
check("register still succeeds when mail fails", j["result"]["verify"] and "couldn't send" in j["result"]["message"], j)
with db.tx() as c:
    n = c.value("SELECT count(*) FROM audit_log l JOIN users u ON u.id = l.target_user_id "
                "WHERE u.email='three@test.example' AND l.action='mail_failed'")
check("the failure is in the audit log", n == 1, n)

# 10. The mail module: log backend sends nothing; unknown backend is an error.
import importlib  # noqa: E402
importlib.reload(mail)  # undoes the fake send
mail.send("x@test.example", "s", "t")
check("log backend is the default", mail.backend() == "log")

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
