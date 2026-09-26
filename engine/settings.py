"""Connection settings from the environment, with passwords read from Docker secret files.

Local dev: nothing set, the defaults point at the dev containers in the README.
Docker: DB_HOST / REDIS_HOST are set, and each password comes from a file named by a
*_FILE variable (/run/secrets/...), so no password sits in an env var, image or git.
"""

import os
from urllib.parse import quote

DEV_DB = "postgresql+psycopg://theta_app:theta_app_dev@127.0.0.1:5433/theta"
DEV_OWNER_DB = "postgresql+psycopg://theta:theta_dev@127.0.0.1:5433/theta"
DEV_REDIS = "redis://:theta_redis_dev@127.0.0.1:6380/0"


def secret(name: str) -> str | None:
    """Value of NAME from the file at NAME_FILE, else from NAME itself."""
    path = os.environ.get(f"{name}_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    return os.environ.get(name)


def _pg(user_var: str, password_var: str, default_user: str) -> str:
    user = os.environ.get(user_var, default_user)
    password = quote(secret(password_var) or "", safe="")
    host, port = os.environ["DB_HOST"], os.environ.get("DB_PORT", "5432")
    name = os.environ.get("DB_NAME", "theta")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


def database_url() -> str:
    """The app role (row read/write only)."""
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    return _pg("DB_USER", "DB_PASSWORD", "theta_app") if os.environ.get("DB_HOST") else DEV_DB


def owner_database_url() -> str:
    """The owner role, for migrations only."""
    if os.environ.get("MIGRATE_DATABASE_URL"):
        return os.environ["MIGRATE_DATABASE_URL"]
    return _pg("OWNER_DB_USER", "OWNER_DB_PASSWORD", "theta_owner") if os.environ.get("DB_HOST") else DEV_OWNER_DB


def redis_url() -> str:
    if os.environ.get("REDIS_URL"):
        return os.environ["REDIS_URL"]
    if os.environ.get("REDIS_HOST"):
        password = quote(secret("REDIS_PASSWORD") or "", safe="")
        return f"redis://:{password}@{os.environ['REDIS_HOST']}:{os.environ.get('REDIS_PORT', '6379')}/0"
    return DEV_REDIS
