"""Lessons and quizzes (issue #124): public reading, answers never sent to the browser, scoring,
pass recorded once, 24-hour retry lock after a fail, and per-user privacy of progress."""
import sys

import server
from engine import auth, db, lessons, users

ORIGIN = "https://t.example"
server.ALLOWED_ORIGINS = {ORIGIN}
server.universe = lambda: ["SBIN"]
fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def call(method, params=None, token=None):
    c = server.app.test_client()
    if token:
        c.set_cookie(server.COOKIE, token, domain="localhost")
    r = c.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
               headers={"Origin": ORIGIN}, environ_base={"REMOTE_ADDR": "10.0.0.7"})
    return r.get_json()


# 1. Content loads and every quiz is well formed.
all_lessons = lessons.list_lessons()
check("fourteen lessons in level order", len(all_lessons) == 14 and all_lessons[0]["slug"] == "what-is-an-option"
      and [l["level"] for l in all_lessons] == sorted(l["level"] for l in all_lessons), [l["slug"] for l in all_lessons])
check("every lesson has 5 questions", all(l["questions"] == 5 for l in all_lessons))

# 2. Reading is public; answers never leave the server.
r = call("lessons_list")
check("lessons_list works signed out", "result" in r and len(r["result"]) == 14, r.get("error"))
r = call("lessons_get", {"slug": "margin"})
q = r["result"]["questions"]
check("lessons_get works signed out", r["result"]["title"].startswith("Margin"), r.get("error"))
check("no answers or explanations in the lesson payload", all(set(x) == {"q", "options"} for x in q), q[0])
check("prev/next links", r["result"]["prev"] == "delta-and-the-015-rule" and r["result"]["next"] == "stop-losses")
r = call("lessons_get", {"slug": "../../etc/passwd"})
check("unknown slug refused", r.get("error", {}).get("message") == "Lesson not found", r)

# 3. Quizzes need an account.
r = call("lesson_submit_quiz", {"slug": "margin", "answers": [1, 2, 1, 1, 1]})
check("quiz refused signed out", r.get("error", {}).get("code") == server.NOT_SIGNED_IN, r)

uid = users.create_user("learner@test.example", "Learner", status="active")
other = users.create_user("other@test.example", "Other", status="active")
tok = auth.new_session(uid, "10.0.0.7", "ua")
key = [q["answer"] for q in lessons._lesson("margin")["questions"]]

# 4. A failed attempt: scored, answers hidden, locked for 24 hours.
wrong = [(a + 1) % 4 for a in key]
r = call("lesson_submit_quiz", {"slug": "margin", "answers": wrong[:3] + key[3:]}, tok)["result"]
check("fail scored 40%", r["score"] == 40 and not r["passed"] and r["retry_at"], r)
check("fail hides the right answers", all("answer" not in x for x in r["results"]) and all(x["why"] for x in r["results"]))
r = call("lesson_submit_quiz", {"slug": "margin", "answers": key}, tok)
check("retry locked for 24 hours", "24 hours" in r.get("error", {}).get("message", ""), r)
r = call("lesson_submit_quiz", {"slug": "margin", "answers": key[:4]}, tok)
check("must answer every question", "Answer all 5" in r.get("error", {}).get("message", ""), r)

# 5. After the lock, a pass is recorded once.
with db.tx(uid) as c:
    c.run("UPDATE lesson_progress SET retry_at = now() - interval '1 minute' WHERE user_id=:u", u=uid)
r = call("lesson_submit_quiz", {"slug": "margin", "answers": key}, tok)["result"]
check("pass 100% and first pass", r["score"] == 100 and r["passed"] and r["first_pass"] and not r["retry_at"], r)
check("pass reveals the answers", [x["answer"] for x in r["results"]] == key)
r = call("lesson_submit_quiz", {"slug": "margin", "answers": wrong}, tok)["result"]
check("retake after a pass: no lock, not a first pass", not r["passed"] and not r["first_pass"] and not r["retry_at"], r)
p = call("lesson_progress", {}, tok)["result"]
check("progress keeps the pass and best score", len(p) == 1 and p[0]["passed_at"] and p[0]["best_score"] == 100
      and p[0]["attempts"] == 3, p)

# 6. Progress is private (row-level security).
check("another user sees none of it", lessons.progress(other) == [])
with db.tx(other) as c:
    seen = c.all("SELECT * FROM lesson_progress")
check("RLS hides other users' rows", seen == [], seen)

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
