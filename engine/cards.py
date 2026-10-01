"""Shareable achievement cards (issue #126, part B).

A card is a frozen snapshot made when the user shares it: nickname, level and title or a finished
course, and their % return only if they choose to show it. It never holds an email or a rupee
amount. Anyone with the link can see it at /c/<slug>; the PNG at /c/<slug>.png is the link preview
WhatsApp and X show.
"""

import io
import json
import secrets
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from . import config, db, lessons, progress

KINDS = ("level", "course")
LABEL = "Paper trading · educational"
W, H = 1200, 630


class CardError(ValueError):
    pass


def _payload(c, user_id: int, kind: str, ref: int, show_return: bool) -> dict:
    nick = c.value("SELECT nickname FROM users WHERE id=:u", u=user_id)
    level = c.value("SELECT level FROM user_levels WHERE user_id=:u", u=user_id) or 1
    out = {"kind": kind, "name": nick}
    if kind == "level":
        if not 1 <= ref <= level:
            raise CardError("You haven't reached that level")
        out |= {"level": ref, "title": config.LEVEL_TITLES[ref]}
    else:
        course = [l["slug"] for l in lessons.list_lessons() if l["level"] == ref]
        passed = {r["slug"] for r in c.all("SELECT slug FROM lesson_progress WHERE user_id=:u AND passed_at IS NOT NULL",
                                           u=user_id)}
        if not course or not set(course) <= passed:
            raise CardError("Pass every lesson in that course first")
        out |= {"course": ref, "lessons": len(course)}
    if show_return:
        trades = c.all("SELECT capital, realized_pnl FROM trade_results WHERE user_id=:u ORDER BY closed_at, id", u=user_id)
        out["return_pct"] = progress.metrics(trades)["return_pct"]
    return out


def create(user_id: int, kind: str, ref: int, show_return: bool = False) -> dict:
    """Makes (or reuses) a share card for a level reached or a course finished and returns its
    slug. `show_return` adds the paper-trading % return; rupee amounts and email are never shown."""
    if kind not in KINDS:
        raise CardError("Unknown card type")
    with db.tx(user_id) as c:
        old = c.value("SELECT slug FROM share_cards WHERE user_id=:u AND kind=:k AND ref=:r AND show_return=:s",
                      u=user_id, k=kind, r=ref, s=show_return)
        if old:
            return {"slug": old}
        payload = _payload(c, user_id, kind, ref, show_return)
        slug = secrets.token_urlsafe(9)
        c.run("INSERT INTO share_cards (slug, user_id, kind, ref, show_return, payload) "
              "VALUES (:sl, :u, :k, :r, :s, CAST(:p AS jsonb))",
              sl=slug, u=user_id, k=kind, r=ref, s=show_return, p=json.dumps(payload))
    from . import capital
    capital.evaluate(user_id)  # the first card of each kind pays a share reward (#47)
    return {"slug": slug}


def get(slug: str) -> dict | None:
    with db.tx() as c:
        return c.value("SELECT payload FROM share_cards WHERE slug=:s", s=slug)


def owner(slug: str) -> int:
    with db.tx() as c:
        return c.value("SELECT user_id FROM share_cards WHERE slug=:s", s=slug)


def headline(p: dict, app: str) -> tuple[str, str]:
    """(big line, small line) for a card, shared by the image and the page. `app` is the app's
    current name, so a rename shows on old cards too."""
    who = p["name"] or f"A {app} trader"
    if p["kind"] == "level":
        return f"Level {p['level']} · {p['title']}", f"{who} reached Level {p['level']} on {app}"
    return f"Level {p['course']} course complete", f"{who} passed all {p['lessons']} lessons on {app}"


@lru_cache(maxsize=8)
def _font(size: int):
    return ImageFont.load_default(size=size)


def png(p: dict, site: str, app: str, logo: bytes | None = None) -> bytes:
    """The 1200×630 preview image. `logo` is the owner's uploaded logo as PNG, if any."""
    img = Image.new("RGB", (W, H), "#0f1720")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 14, H), fill="#2bb673")
    x = 70
    if logo:
        with Image.open(io.BytesIO(logo)) as mark:
            mark = mark.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
            img.paste(mark, (70, 50), mark)
        x = 150
    d.text((x, 60), app, font=_font(40), fill="#e6edf3", stroke_width=1, stroke_fill="#e6edf3")
    big, small = headline(p, app)
    d.text((70, 210), big, font=_font(76), fill="#ffffff", stroke_width=2, stroke_fill="#ffffff")
    d.text((70, 320), small, font=_font(34), fill="#9fb0c0")
    if "return_pct" in p:
        r = p["return_pct"]
        d.text((70, 390), f"Paper-trading return: {'+' if r > 0 else ''}{r:.1f}%", font=_font(38),
               fill="#2bb673" if r >= 0 else "#f0645c")
    d.text((70, H - 90), LABEL, font=_font(28), fill="#9fb0c0")
    d.text((W - 70, H - 90), site, font=_font(28), fill="#e6edf3", anchor="ra")
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
