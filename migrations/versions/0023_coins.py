"""Coins (issue #47): a second reward currency, earned on top of virtual-capital grants and exchanged
one way into virtual capital (1 coin = config.COIN_RUPEES).

`coin_ledger` holds every credit (positive, one per (kind, ref)) and every exchange (negative).
Private to the user under row-level security; the app may insert and read, never edit or delete.

Revision ID: 0023
Revises: 0022
"""
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE coin_ledger (
      id         BIGSERIAL PRIMARY KEY,
      user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      kind       TEXT NOT NULL,
      ref        TEXT NOT NULL DEFAULT '',
      coins      INTEGER NOT NULL CHECK (coins <> 0),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE (user_id, kind, ref)
    );
    ALTER TABLE coin_ledger ENABLE ROW LEVEL SECURITY;
    ALTER TABLE coin_ledger FORCE ROW LEVEL SECURITY;
    CREATE POLICY coin_ledger_own ON coin_ledger FOR ALL
      USING (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint)
      WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint);
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'theta_app') THEN
        GRANT SELECT, INSERT ON coin_ledger TO theta_app;
        GRANT USAGE ON SEQUENCE coin_ledger_id_seq TO theta_app;
      END IF;
    END $$;""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS coin_ledger")
