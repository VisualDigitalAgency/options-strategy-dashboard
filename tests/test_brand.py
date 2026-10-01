"""Owner-editable branding (issue #133): only the owner may rename the app or change its logo, even
against a sub-admin holding every feature; only real PNG/WebP is accepted and is re-encoded to PNG;
the name reaches emails, share cards and app_info; reset goes back to the built-in mark."""
import io
import os
import sys

from PIL import Image

import server
from engine import auth, brand, cards, db, mail, permissions, users

ORIGIN = "https://t.example"
os.environ["PUBLIC_URL"] = "https://brand.example"
server.ALLOWED_ORIGINS = {ORIGIN}
fails = []


def check(name, cond, got=""):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def client(uid):
    c = server.app.test_client()
    if uid:
        c.set_cookie(server.COOKIE, auth.new_session(uid, "10.0.0.9", "ua"), domain="localhost")
    return c


def rpc(c, method, params=None):
    return c.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                  headers={"Origin": ORIGIN}).get_json()


def upload(c, data, ctype="image/png", origin=ORIGIN):
    r = c.post("/brand/logo", data=data, headers={"Origin": origin, "Content-Type": ctype})
    return r.status_code, r.get_json()


def img(fmt, size=(300, 200), **kw):
    buf = io.BytesIO()
    Image.new("RGBA", size, (200, 30, 30, 255)).save(buf, fmt, **kw)
    return buf.getvalue()


owner = users.create_user("owner@test.example", "Owner", role="owner", status="active")
sub = users.create_user("sub@test.example", "Sub", role="sub_admin", status="active")
plain = users.create_user("user@test.example", "User", status="active")
O, S, U, anon = client(owner), client(sub), client(plain), client(None)
for f in permissions.FEATURES:  # a sub-admin with everything the owner can hand out
    rpc(O, "admin_set_feature", {"role": "sub_admin", "feature": f, "enabled": True})

# 1. Defaults.
info = rpc(anon, "app_info")["result"]
check("app_info is public and defaults to the built-in brand", info == {"name": brand.DEFAULT_NAME, "logo": None}, info)
os.environ["APP_NAME"] = "Env Name"
check("APP_NAME sets the first-start name", brand.name() == "Env Name")
check("no logo: /brand/logo.png is 404", anon.get("/brand/logo.png").status_code == 404)

# 2. Only the owner.
for who, c in (("sub-admin with every feature", S), ("user", U), ("signed-out", anon)):
    r = rpc(c, "admin_set_brand_name", {"name": "Hijack"})
    check(f"{who} can't rename", "error" in r, r)
    r = rpc(c, "admin_reset_logo")
    check(f"{who} can't reset the logo", "error" in r, r)
    code, _ = upload(c, img("PNG"))
    check(f"{who} can't upload a logo", code in (401, 403), code)
code, _ = upload(O, img("PNG"), origin="https://evil.example")
check("upload from another site refused", code == 403, code)
check("name unchanged", brand.name() == "Env Name")

# 3. Owner renames; it shows everywhere.
r = rpc(O, "admin_set_brand_name", {"name": "  Nifty   Dojo "})
check("owner renames (spaces tidied)", r.get("result", {}).get("name") == "Nifty Dojo", r)
check("database name beats APP_NAME", brand.name() == "Nifty Dojo")
for bad in ("", "x" * 41):
    check(f"bad name refused ({len(bad)} chars)", "error" in rpc(O, "admin_set_brand_name", {"name": bad}))
sent = []
mail.send = lambda to, subject, text: sent.append((subject, text))
auth._send_code(plain, "user@test.example", None)
check("verification email uses the name", "Nifty Dojo" in sent[-1][0] and "Nifty Dojo" in sent[-1][1], sent[-1][0])
check("default sender uses name and PUBLIC_URL host", mail._sender() == "Nifty Dojo <no-reply@brand.example>", mail._sender())
with db.tx(owner) as c:
    c.run("INSERT INTO user_levels (user_id, level) VALUES (:u, 2)", u=owner)
slug = cards.create(owner, "level", 2)["slug"]
page = anon.get(f"/c/{slug}").get_data(as_text=True)
check("share card page uses the name", 'og:site_name" content="Nifty Dojo"' in page and "Theta" not in page)
check("unnamed trader uses the name", "A Nifty Dojo trader" in cards.headline(cards.get(slug), brand.name())[1])
with db.tx() as c:
    audit = [r["detail"] for r in c.all("SELECT detail FROM audit_log WHERE action='brand_changed'")]
check("rename audited", any(d.get("value") == "Nifty Dojo" for d in audit), audit)

# 4. Uploads: PNG and WebP only, checked by content, re-encoded.
for label, data, ctype in (("SVG", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "image/png"),
                           ("random bytes", os.urandom(500), "image/png"),
                           ("SVG content type", b"<svg/>", "image/svg+xml"),
                           ("empty", b"", "image/png")):
    code, body = upload(O, data, ctype)
    check(f"{label} refused", code in (400, 415) and "error" in body, (code, body))
jpeg = io.BytesIO()
Image.new("RGB", (10, 10)).save(jpeg, "JPEG")
code, body = upload(O, jpeg.getvalue())
check("real JPEG refused", code == 400, (code, body))
code, body = upload(O, b"\x89PNG\r\n\x1a\n" + b"0" * (brand.MAX_UPLOAD + 10))
check("over 1 MB refused", code in (400, 413), code)
code, body = upload(O, img("PNG", size=(5000, 4000)))
check("huge dimensions refused", code in (400, 413), (code, body))

code, body = upload(O, img("PNG"))
check("owner uploads PNG", code == 200 and body["result"]["logo"], (code, body))
v = body["result"]["logo"]
for kind, size in brand.SIZES.items():
    r = anon.get(f"/brand/{kind}.png?v={v}")
    with Image.open(io.BytesIO(r.data)) as im:
        check(f"{kind} served as {size}px PNG", r.status_code == 200 and r.mimetype == "image/png"
              and im.format == "PNG" and im.size == (size, size), (r.status_code, im.format, im.size))
    check(f"{kind} sandboxed and nosniff", "sandbox" in r.headers["Content-Security-Policy"]
          and r.headers["X-Content-Type-Options"] == "nosniff")
r = anon.get("/brand/logo.png", headers={"If-None-Match": f'"{brand.asset("logo")[1]}"'})
check("ETag gives 304", r.status_code == 304, r.status_code)
check("unknown asset kind 404", anon.get("/brand/secret.png").status_code == 404)
check("share card PNG renders with the logo", anon.get(f"/c/{slug}.png").status_code == 200)

frames = [Image.new("RGBA", (64, 64), c) for c in ((0, 255, 0, 255), (0, 0, 255, 255))]
buf = io.BytesIO()
frames[0].save(buf, "WEBP", save_all=True, append_images=frames[1:], duration=100, loop=0)
code, body = upload(O, buf.getvalue(), "image/webp")
check("animated WebP accepted", code == 200 and body["result"]["logo"] != v, (code, body))
with Image.open(io.BytesIO(brand.asset("logo")[0])) as im:
    check("stored as a still PNG, first frame", im.format == "PNG" and not getattr(im, "is_animated", False)
          and im.convert("RGB").getpixel((256, 256))[1] > 200, im.convert("RGB").getpixel((256, 256)))  # green, not blue

# 5. Reset.
r = rpc(O, "admin_reset_logo")
check("reset goes back to the built-in mark", r.get("result", {}).get("logo") is None, r)
check("reset removes the favicon too", anon.get("/brand/favicon.png").status_code == 404)

sys.exit(1 if fails else 0)
