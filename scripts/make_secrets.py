"""Creates ./secrets/ with a random password per service, for docker compose.

    python scripts/make_secrets.py

Existing files are left alone, so running it again never changes a password a running
database already uses. Hex passwords: no characters that need escaping in SQL or URLs.
"""

import os
import secrets
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "secrets"
NAMES = ("db_owner_password", "db_app_password", "redis_password")


def main() -> None:
    DIR.mkdir(exist_ok=True)
    for name in NAMES:
        f = DIR / name
        if f.exists():
            print(f"kept    {f.name}")
            continue
        f.write_text(secrets.token_hex(24), encoding="utf-8")
        try:
            os.chmod(f, 0o600)  # owner read/write only (no effect on Windows)
        except OSError:
            pass
        print(f"created {f.name}")


if __name__ == "__main__":
    main()
