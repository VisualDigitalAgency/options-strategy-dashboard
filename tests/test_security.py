"""Regression tests for the issue #39 security review: login limits under parallel guesses,
string length caps, and DB errors that must not carry bound values into logs."""
import sys
import threading

from sqlalchemy.exc import IntegrityError

import server
from engine import auth, db, users

ORIGIN = "https://t.example"
server.ALLOWED_ORIGINS = {ORIGIN}
server.universe = lambda: ["SBIN"]
fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def call(method, params, ip="10.0.0.1"):
    c = server.app.test_client()
    r = c.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
               headers={"Origin": ORIGIN}, environ_base={"REMOTE_ADDR": ip})
    return r.get_json()


uid = users.create_user("victim@test.example", "Victim", status="active")
with db.tx() as c:
    c.run("UPDATE users SET password_hash=:h WHERE id=:u", h=auth.hash_password("correct-horse-battery"), u=uid)

# 1. Parallel wrong guesses: at most FAILS_PER_PAIR get a password check, the rest are refused.
go, answers = threading.Barrier(12), []


def guess(i):
    go.wait()
    j = call("auth_login", {"email": "victim@test.example", "password": f"wrong-guess-{i:04d}"})
    answers.append(j["error"]["message"])


threads = [threading.Thread(target=guess, args=(i,)) for i in range(12)]
for t in threads:
    t.start()
for t in threads:
    t.join()
checked = sum(1 for a in answers if a == auth.WRONG)
check(f"12 parallel guesses: at most {auth.FAILS_PER_PAIR} reach the password check",
      checked <= auth.FAILS_PER_PAIR and len(answers) == 12, answers)
j = call("auth_login", {"email": "victim@test.example", "password": "correct-horse-battery"})
check("even the right password waits out the lockout from that IP", "Too many" in j["error"]["message"], j)

# 2. Another IP isn't affected, and a success there leaves that IP's counter at zero.
j = call("auth_login", {"email": "victim@test.example", "password": "correct-horse-battery"}, ip="10.0.0.2")
check("sign-in from a different IP works", j.get("result", {}).get("id") == uid, j)
_, per_ip = auth._fail_keys("victim@test.example", "10.0.0.2")
check("a successful sign-in doesn't count against its IP", auth._count(per_ip) == 0, auth._count(per_ip))

# 3. Oversized strings are refused at the trust boundary, before any engine code.
j = call("auth_login", {"email": "a@b.example", "password": "x" * 5000})
check("an oversized string param is refused as invalid params",
      j["error"]["code"] == -32602 and "too long" in j["error"]["message"], j["error"])

# 4. A DB error's message doesn't carry the bound values (they'd be logged with the traceback).
secret_value = "argon2-hash-that-must-not-be-logged"
try:
    with db.tx() as c:
        c.run("INSERT INTO users (id, email, email_canonical, name, password_hash) VALUES (:i, :e, :e, 'x', :h)",
              i=uid, e="dup@test.example", h=secret_value)
    check("duplicate insert raised", False)
except IntegrityError as e:
    check("DB error text hides bound parameters", secret_value not in str(e), str(e)[:200])

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
