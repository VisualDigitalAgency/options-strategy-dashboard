"""Sets the owner's (top admin's) sign-in email and password.

    python scripts/set_admin.py you@example.com          # asks for the password twice (hidden)

The admin is the account your SQLite data was migrated into (admin@theta.local until you run
this). Running it again changes the email or password. For unattended setup (Docker), set
ADMIN_EMAIL and ADMIN_PASSWORD instead; that password must be changed on first sign-in.
"""

import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import auth, db, users  # noqa: E402


def main() -> int:
    email = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ADMIN_EMAIL", "")).strip().lower()
    if not auth.EMAIL_RE.match(email):
        print("Usage: python scripts/set_admin.py you@example.com")
        return 1
    from_env = "ADMIN_PASSWORD" in os.environ
    if from_env:
        password = os.environ["ADMIN_PASSWORD"]
    else:
        password = getpass.getpass("New admin password: ")
        if password != getpass.getpass("Same again: "):
            print("The two passwords differ. Nothing changed.")
            return 1
    try:
        auth.check_password(password, email)
    except auth.AuthError as e:
        print(f"{e}. Nothing changed.")
        return 1

    with db.tx() as c:
        admin = c.one("SELECT id, email FROM users WHERE role='owner'")
        taken = c.value("SELECT id FROM users WHERE email_canonical=:ce", ce=users.canonical_email(email))
    if admin is None:
        admin = {"id": users.bootstrap_local_user(), "email": users.LOCAL_EMAIL}
    if taken and taken != admin["id"]:
        print(f"{email} already belongs to another user. Nothing changed.")
        return 1
    with db.tx() as c:
        c.run("UPDATE users SET email=:e, email_canonical=:ce, password_hash=:h, status='active', "
              "must_change_password=:m WHERE id=:u", e=email, ce=users.canonical_email(email),
              h=auth.hash_password(password), m=from_env, u=admin["id"])
    auth.end_all_sessions(admin["id"])
    auth.audit("admin_password_set", target_user_id=admin["id"], old_email=admin["email"], email=email)
    print(f"Admin (user {admin['id']}) signs in as {email}." + (" Change the password on first sign-in." if from_env else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
