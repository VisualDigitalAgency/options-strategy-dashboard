"""PostgreSQL access: one engine, plain SQL, rows back as dicts.

Every user-owned table has row-level security keyed on the `app.user_id` setting, so
`tx(user_id)` sets it for the transaction. A query that forgets `WHERE user_id` still
only sees that user's rows. `tx()` without a user is for cross-user work (the worker
listing users, bootstrap) and only reaches the `users` table.

Connection settings: engine/settings.py.
"""

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine, text

from . import settings

IST = timezone(timedelta(hours=5, minutes=30))
DATABASE_URL = settings.database_url()

_engine = None


def engine():
    global _engine
    if _engine is None:
        # hide_parameters: a DB error's message otherwise carries every bound value (password
        # hashes, encrypted broker tokens), and server.py logs that traceback in full.
        _engine = create_engine(DATABASE_URL, pool_size=5, max_overflow=5, pool_pre_ping=True, future=True,
                                hide_parameters=True)
    return _engine


def _plain(v):
    """DB types to the JSON-friendly shapes the API has always returned."""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.isoformat()
    return v


class Tx:
    def __init__(self, conn):
        self.conn = conn

    def all(self, sql: str, **params) -> list[dict]:
        return [{k: _plain(v) for k, v in r._mapping.items()} for r in self.conn.execute(text(sql), params)]

    def one(self, sql: str, **params) -> dict | None:
        rows = self.all(sql, **params)
        return rows[0] if rows else None

    def value(self, sql: str, **params):
        return _plain(self.conn.execute(text(sql), params).scalar())

    def run(self, sql: str, **params) -> int:
        return self.conn.execute(text(sql), params).rowcount


@contextmanager
def tx(user_id: int | None = None):
    """One transaction. Commits on success, rolls back on any exception."""
    with engine().begin() as conn:
        if user_id is not None:
            conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(int(user_id))})
        yield Tx(conn)


def now() -> datetime:
    return datetime.now(timezone.utc)
