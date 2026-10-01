"""Share cards (issue #126): only for a level reached or a course passed, % return only when asked,
never email or rupee amounts, one card per choice, public page with preview tags, PNG preview,
RLS (anyone reads, only the owner writes), and the RPC."""
import os
import sys

import server
from engine import auth, cards, db, lessons
from support import EXP, new_user

ORIGIN = "https://t.example"
os.environ["PUBLIC_URL"] = "https://theta.example"
server.ALLOWED_ORIGINS = {ORIGIN}
fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


uid = new_user("cards@test.example", 1_000_000)
with db.tx() as c:
    c.run("UPDATE users SET nickname='ashA_99' WHERE id=:u", u=uid)
with db.tx(uid) as c:
    c.run("INSERT INTO user_levels (user_id, level) VALUES (:u, 3)", u=uid)
    c.run("INSERT INTO trade_results (user_id, symbol, expiry, side, strike, short, lots, avg_price, realized_pnl,"
          " capital, opened_at, exit_reason, had_sl) VALUES (:u, 'SBIN', :e, 'CE', 1200, true, 1, 5, 25000,"
          " 1000000, now(), 'manual', true)", u=uid, e=EXP)

# 1. Level cards.
a = cards.create(uid, "level", 3)
p = cards.get(a["slug"])
check("level card shows nickname, level and title", p == {"kind": "level", "name": "ashA_99", "level": 3, "title": "Seller"}, p)
check("same choice reuses the card", cards.create(uid, "level", 3) == a)
b = cards.create(uid, "level", 3, show_return=True)
check("% return only when chosen", b != a and cards.get(b["slug"])["return_pct"] == 2.5, cards.get(b["slug"]))
for bad, why in (((uid, "level", 4), "level not reached"), ((uid, "course", 1), "course not passed"),
                 ((uid, "badge", 1), "unknown kind")):
    try:
        cards.create(*bad)
        check(f"refused: {why}", False)
    except ValueError as e:
        check(f"refused: {why}", True, e)

# 2. Course cards.
course = [l["slug"] for l in lessons.list_lessons() if l["level"] == 1]
with db.tx(uid) as c:
    for s in course:
        c.run("INSERT INTO lesson_progress (user_id, slug, attempts, best_score, passed_at) VALUES (:u, :s, 1, 100, now())",
              u=uid, s=s)
k = cards.get(cards.create(uid, "course", 1)["slug"])
check("course card counts the lessons", k == {"kind": "course", "name": "ashA_99", "course": 1, "lessons": len(course)}, k)

# 3. Nothing private on any card.
with db.tx() as c:
    stored = str(c.all("SELECT payload FROM share_cards"))
check("no email or rupee amount stored", "@" not in stored and "25000" not in stored and "1000000" not in stored, stored)

# 4. RLS: anyone reads, nobody writes for someone else.
other = new_user("other@test.example", 1_000_000)
with db.tx(other) as c:
    check("other users can read a card", c.value("SELECT count(*) FROM share_cards") == 3)
try:
    with db.tx(other) as c:
        c.run("INSERT INTO share_cards (slug, user_id, kind, ref, show_return, payload) VALUES ('x', :u, 'level', 1, false, '{}')", u=uid)
    check("can't create a card for someone else", False)
except Exception as e:
    check("can't create a card for someone else", "row-level security" in str(e), type(e).__name__)

# 5. Public page and image.
app = server.app.test_client()
r = app.get(f"/c/{b['slug']}")
html = r.get_data(as_text=True)
check("public page needs no sign-in", r.status_code == 200 and r.mimetype == "text/html", r.status_code)
check("preview tags point at the absolute image", f'og:image" content="https://theta.example/c/{b["slug"]}.png"' in html
      and 'twitter:card" content="summary_large_image"' in html)
check("page labels it paper trading and links to sign-up", "Paper trading · educational" in html and "https://theta.example/register" in html)
check("page has its own CSP allowing the image", "img-src 'self'" in r.headers["Content-Security-Policy"])
r = app.get(f"/c/{b['slug']}.png")
check("PNG preview 1200x630", r.status_code == 200 and r.mimetype == "image/png" and r.data[:8] == b"\x89PNG\r\n\x1a\n"
      and int.from_bytes(r.data[16:20], "big") == 1200 and int.from_bytes(r.data[20:24], "big") == 630)
check("image cached, not immutable (it follows the brand, #133)", "max-age" in r.headers["Cache-Control"] and "immutable" not in r.headers["Cache-Control"])
check("unknown card is a 404", app.get("/c/nope").status_code == 404 and app.get("/c/nope.png").status_code == 404)
with db.tx() as c:
    c.run("UPDATE users SET nickname='<b>x</b>' WHERE id=:u", u=other)
with db.tx(other) as c:
    c.run("INSERT INTO user_levels (user_id) VALUES (:u)", u=other)
html = app.get(f"/c/{cards.create(other, 'level', 1)['slug']}").get_data(as_text=True)
check("nickname is escaped on the page", "<b>x</b>" not in html and "&lt;b&gt;" in html)

# 6. RPC.
app.set_cookie(server.COOKIE, auth.new_session(uid, "127.0.0.1", "t"), domain="localhost")


def call(method, params=None):
    return app.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                    headers={"Origin": ORIGIN}).get_json()


r = call("card_create", {"kind": "level", "ref": 2})
check("card_create returns a slug", "result" in r and len(r["result"]["slug"]) >= 10, r)
r = call("card_create", {"kind": "level", "ref": 9})
check("card_create refuses an unearned level", r.get("error", {}).get("message") == "You haven't reached that level", r)
r = call("card_create", {"kind": "level", "ref": 2, "user_id": other})
check("client can't make a card as someone else", "error" in r, r)

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
