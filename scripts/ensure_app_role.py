"""Create the theta_app role, or reset its password, before migrations run.

    python scripts/ensure_app_role.py

Runs as the owner (the same connection as migrations) on every start of the migrate service.
The Postgres image's init scripts only run when the data volume is first created, and on
Coolify they can't be bind-mounted from the repo at all. Doing it here means a fresh volume,
an existing one, and a changed DB_APP_PASSWORD all end in the same state. Grants stay in the
migrations, which run right after this.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402

from engine import settings  # noqa: E402


def main() -> None:
    password = settings.secret("DB_APP_PASSWORD")
    if not password:
        sys.exit("DB_APP_PASSWORD (or DB_APP_PASSWORD_FILE) is not set")
    with create_engine(settings.owner_database_url()).begin() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'theta_app'")).scalar()
        verb = "ALTER" if exists else "CREATE"
        # format(%L) quotes the password as a literal on the server side; nothing is spliced in Python.
        sql = conn.execute(text(
            f"SELECT format('{verb} ROLE theta_app LOGIN PASSWORD %L "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS', CAST(:pw AS text))"), {"pw": password}).scalar()
        conn.execute(text(sql))
        db = conn.execute(text("SELECT current_database()")).scalar()
        conn.execute(text(f'REVOKE ALL ON DATABASE "{db}" FROM PUBLIC'))
        conn.execute(text(f'GRANT CONNECT ON DATABASE "{db}" TO theta_app'))
        conn.execute(text("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))
    print(f"theta_app role {'updated' if exists else 'created'}")


if __name__ == "__main__":
    main()
