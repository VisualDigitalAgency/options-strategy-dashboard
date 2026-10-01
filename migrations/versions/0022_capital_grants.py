"""Virtual capital: ₹2 lakh start, more by completing task milestones (issue #47).

- `accounts.base_capital`: what a reset restarts from (before grants). Existing accounts keep their
  current capital as their base, so nobody loses money; new accounts get config.STARTING_CAPITAL.
- `capital_grants`: one row per task paid (unique per user, task and ref, so a task pays once).
  Private to the user under row-level security; the app may insert and read, never edit or delete.

Revision ID: 0022
Revises: 0021
"""
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE accounts ADD COLUMN base_capital NUMERIC(14,2);
    UPDATE accounts SET base_capital = starting_capital;
    ALTER TABLE accounts ALTER COLUMN base_capital SET NOT NULL;
    CREATE TABLE capital_grants (
      id         BIGSERIAL PRIMARY KEY,
      user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      task       TEXT NOT NULL,
      ref        TEXT NOT NULL DEFAULT '',
      amount     NUMERIC(14,2) NOT NULL CHECK (amount > 0),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE (user_id, task, ref)
    );
    ALTER TABLE capital_grants ENABLE ROW LEVEL SECURITY;
    ALTER TABLE capital_grants FORCE ROW LEVEL SECURITY;
    CREATE POLICY capital_grants_own ON capital_grants FOR ALL
      USING (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint)
      WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint);
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'theta_app') THEN
        GRANT SELECT, INSERT ON capital_grants TO theta_app;
        GRANT USAGE ON SEQUENCE capital_grants_id_seq TO theta_app;
      END IF;
    END $$;""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS capital_grants; ALTER TABLE accounts DROP COLUMN IF EXISTS base_capital")
