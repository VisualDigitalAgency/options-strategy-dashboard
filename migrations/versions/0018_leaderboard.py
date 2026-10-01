"""Monthly paper-trading leaderboard (issue #125, part of #120).

`leaderboard_entries` holds each finished month's ranked rows, written by the worker on the 1st.
The board is public, so anyone may read a row. Writes are allowed only outside a per-user
transaction (no `app.user_id` set), i.e. from the worker's job, never from a request acting for a
user. A row holds the nickname and ratios only: no user id, email or rupee amount.

Revision ID: 0018
Revises: 0017
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE leaderboard_entries (
      month       TEXT NOT NULL CHECK (month ~ '^[0-9]{4}-[0-9]{2}$'),
      band        TEXT NOT NULL,
      rank        INTEGER NOT NULL,
      nickname    TEXT NOT NULL,
      level       INTEGER NOT NULL,
      ratio       NUMERIC(10,2) NOT NULL,
      return_pct  NUMERIC(10,2) NOT NULL,
      max_dd_pct  NUMERIC(10,2) NOT NULL,
      trades      INTEGER NOT NULL,
      win_rate    NUMERIC(5,1) NOT NULL,
      PRIMARY KEY (month, band, rank)
    );
    ALTER TABLE leaderboard_entries ENABLE ROW LEVEL SECURITY;
    ALTER TABLE leaderboard_entries FORCE ROW LEVEL SECURITY;
    CREATE POLICY leaderboard_read ON leaderboard_entries FOR SELECT USING (true);
    CREATE POLICY leaderboard_write ON leaderboard_entries FOR ALL
      USING (COALESCE(current_setting('app.user_id', true), '') = '')
      WITH CHECK (COALESCE(current_setting('app.user_id', true), '') = '');
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'theta_app') THEN
        GRANT SELECT, INSERT, DELETE ON leaderboard_entries TO theta_app;
      END IF;
    END $$;""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS leaderboard_entries")
