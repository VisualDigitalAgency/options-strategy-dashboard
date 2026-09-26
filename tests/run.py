"""Run the integration tests, each file against its own freshly migrated database.

    python tests/run.py                  # every tests/test_*.py
    python tests/run.py test_pivots.py   # just these

Needs a Postgres whose owner role can CREATE DATABASE, and a Redis it may flush:
    DB_HOST, OWNER_DB_PASSWORD (owner user theta_owner by default), DB_APP_PASSWORD, REDIS_URL
CI provides both as service containers. Locally, `make test` starts throwaway ones in Docker.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import redis  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from engine import settings  # noqa: E402


def fresh_database(name: str) -> None:
    admin = create_engine(settings.owner_database_url().rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    for attempt in range(30):  # a just-started Postgres container takes a few seconds
        try:
            admin.connect().close()
            break
        except Exception:
            if attempt == 29:
                raise
            time.sleep(1)
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()


def main() -> int:
    for var in ("DB_HOST", "OWNER_DB_PASSWORD", "DB_APP_PASSWORD", "REDIS_URL"):
        if not os.environ.get(var):
            sys.exit(f"{var} is not set (see the docstring of tests/run.py)")
    files = [Path(__file__).parent / f for f in sys.argv[1:]] or sorted(Path(__file__).parent.glob("test_*.py"))
    results = []
    for i, f in enumerate(files):
        db = f"theta_test_{i}"
        env = {**os.environ, "DB_NAME": db, "DB_PASSWORD": os.environ["DB_APP_PASSWORD"],
               "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "tests")]), "TZ": "Asia/Kolkata",
               "COOKIE_SECURE": "0"}
        os.environ["DB_NAME"] = db  # for fresh_database's owner URL
        fresh_database(db)
        redis.Redis.from_url(os.environ["REDIS_URL"]).flushdb()
        for cmd in (["scripts/ensure_app_role.py"], ["-m", "alembic", "upgrade", "head"]):
            r = subprocess.run([sys.executable, *cmd], cwd=ROOT, env=env, capture_output=True, text=True)
            if r.returncode:
                print(r.stdout, r.stderr)
                sys.exit(f"setup failed for {f.name}: {' '.join(cmd)}")
        print(f"\n===== {f.name}", flush=True)
        t = time.monotonic()
        r = subprocess.run([sys.executable, str(f)], cwd=ROOT, env=env, timeout=300)
        results.append((f.name, r.returncode == 0, time.monotonic() - t))
    print("\n===== summary")
    for name, ok, secs in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  ({secs:.1f}s)")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
