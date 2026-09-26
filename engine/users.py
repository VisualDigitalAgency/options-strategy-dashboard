"""Users and per-user setup. Passwords, sessions and approval live in engine/auth.py.

`bootstrap_local_user()` creates the first admin on a fresh database.
"""

import os

from . import config, db

LOCAL_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@theta.local").strip().lower()
GMAIL = ("gmail.com", "googlemail.com")


def canonical_email(email: str) -> str:
    """The mailbox an address really delivers to, so one person can't sign up twice with
    variants: `a.sha+2@gmail.com` and `asha@googlemail.com` are both `asha@gmail.com`.
    Plus-tags are dropped for every domain; dots only for Gmail, which ignores them."""
    local, _, domain = email.strip().lower().partition("@")
    local = local.split("+", 1)[0]
    if domain in GMAIL:
        return local.replace(".", "") + "@gmail.com"
    return f"{local}@{domain}"


def create_user(email: str, name: str, role: str = "user", status: str = "pending", ip: str | None = None) -> int:
    """Adds the user plus their account and auto-trade rows. The unique index on
    email_canonical refuses a second account for the same mailbox, even under a race."""
    with db.tx() as c:
        uid = c.value("INSERT INTO users (email, email_canonical, name, role, status, signup_ip) "
                      "VALUES (:e, :ce, :n, :r, :s, CAST(:ip AS inet)) RETURNING id",
                      e=email.strip().lower(), ce=canonical_email(email), n=name, r=role, s=status, ip=ip)
    with db.tx(uid) as c:
        c.run("INSERT INTO accounts (user_id, starting_capital) VALUES (:u, :cap)",
              u=uid, cap=config.STARTING_CAPITAL)
        c.run("INSERT INTO autotrade_settings (user_id) VALUES (:u)", u=uid)
    return uid


def bootstrap_local_user() -> int:
    """The first admin: created once on a fresh database, with no password until
    scripts/set_admin.py sets one. Idempotent, and never adds a second admin."""
    with db.tx() as c:
        uid = c.value("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1")
    return uid or create_user(LOCAL_EMAIL, "Admin", role="admin", status="active")


def active_user_ids() -> list[int]:
    """Background jobs (SL monitor, auto-trade) act only for active users."""
    with db.tx() as c:
        return [r["id"] for r in c.all("SELECT id FROM users WHERE status = 'active' ORDER BY id")]
