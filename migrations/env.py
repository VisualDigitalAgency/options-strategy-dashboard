"""Alembic runs as the owner role; the app connects as theta_app, which has no DDL rights."""
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.settings import owner_database_url  # noqa: E402

URL = owner_database_url()

with create_engine(URL).connect() as conn:
    context.configure(connection=conn, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
