"""Owner-managed app switches (issue #121), stored in `app_settings`.

Only the keys in SETTINGS exist; each has a type and a default used if its row is ever missing.
Read on every use, so a change applies at once.
"""

import json

from . import db

SETTINGS = {
    "auto_approve": (bool, True, "New accounts can use the app as soon as their email is confirmed. "
                                  "Off: they wait for approval on the Admin page."),
    "google_login": (bool, False, "Sign in with Google: a \"Continue with Google\" button on the sign-in and join pages. "
                                  "Needs GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET on the server. The owner account "
                                  "always signs in with its password."),
    # Reader (#163): what a signed-out visitor may open. Off sends them to sign in instead.
    "reader_builder": (bool, True, "Reader (signed out): the strategy builder. Placing an order asks them to join."),
    "reader_learn": (bool, True, "Reader (signed out): lessons. Quizzes always need an account."),
    "reader_progress": (bool, True, "Reader (signed out): the levels and what each unlocks, with a join prompt."),
    "reader_leaderboard": (bool, True, "Reader (signed out): the monthly leaderboard."),
    # Off by default. Turn on only with a written legal opinion (doc/2026-10-03-prize-draw.md).
    "prize_draw": (bool, False, "Monthly prize draw among disciplined players who opt in (random, never for "
                                "returns). Needs a written legal opinion before you turn it on."),
    # Data plan B (#216): off until the owner has checked real files with scripts/check_eod.py.
    "eod_prices": (bool, False, "End-of-day prices: the virtual account prices from NSE's end-of-day file instead of "
                                "the live feed. Orders fill at the next closing settlement; stops and exits run once a "
                                "day after 18:30, and the screener, builder and scheduled auto-trade use the same file."),
}
READER_PAGES = ("builder", "learn", "progress", "leaderboard")


def reader_pages() -> list[str]:
    """The pages a signed-out visitor may open right now."""
    return [p for p in READER_PAGES if get(f"reader_{p}")]


def require_reader(user, page: str) -> None:
    """Signed-in users pass; a visitor needs the owner to have the page on for readers."""
    if not user and page not in reader_pages():
        raise ValueError("Sign in to see this")


def get(key: str):
    kind, default, _ = SETTINGS[key]
    with db.tx() as c:
        v = c.value("SELECT value FROM app_settings WHERE key=:k", k=key)
    return default if v is None else kind(v)


def all_settings() -> list[dict]:
    """Every setting with its current value and description, for the owner's Admin tab."""
    return [{"key": k, "value": get(k), "label": label} for k, (_, _, label) in SETTINGS.items()]


def set_value(owner_id: int, key: str, value, ip: str | None = None) -> list[dict]:
    from . import auth  # auth imports this module
    if key not in SETTINGS:
        raise ValueError("Unknown setting")
    kind = SETTINGS[key][0]
    if type(value) is not kind:
        raise ValueError(f"{key} must be a {kind.__name__}")
    if key == "google_login" and value:
        from . import google_auth
        if not google_auth.configured():
            raise ValueError("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET on the server first")
    was = get(key)
    with db.tx() as c:
        c.run("INSERT INTO app_settings (key, value, updated_at, updated_by) VALUES (:k, CAST(:v AS jsonb), now(), :o) "
              "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now(), updated_by=:o",
              k=key, v=json.dumps(value), o=owner_id)
    if was != value:
        auth.audit("setting_changed", actor_id=owner_id, ip=ip, key=key, was=was, value=value)
    return all_settings()
