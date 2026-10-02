"""Virtual-account risk management (issue #178): square-off charges and the shortfall penalty.

- `account_charges`: every charge debited from a virtual account (kind `rms_charge` per square-off
  order, `margin_penalty` per day of shortfall). Charges reduce account value and return %.
- `margin_shortfalls`: the day's peak margin shortfall per user, and the margin required at that
  moment, which the end-of-day penalty is computed from.
Both private to the user under row-level security.

Revision ID: 0025
Revises: 0024
"""
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE account_charges (
      id         BIGSERIAL PRIMARY KEY,
      user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      kind       TEXT NOT NULL CHECK (kind IN ('rms_charge', 'margin_penalty')),
      ref        TEXT NOT NULL,
      amount     NUMERIC(14,2) NOT NULL CHECK (amount > 0),
      note       TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE (user_id, kind, ref)
    );
    CREATE TABLE margin_shortfalls (
      user_id  BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      day      DATE NOT NULL,
      peak     NUMERIC(14,2) NOT NULL CHECK (peak > 0),
      required NUMERIC(14,2) NOT NULL,
      PRIMARY KEY (user_id, day)
    );
    ALTER TABLE account_charges ENABLE ROW LEVEL SECURITY;
    ALTER TABLE account_charges FORCE ROW LEVEL SECURITY;
    CREATE POLICY account_charges_own ON account_charges FOR ALL
      USING (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint)
      WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint);
    ALTER TABLE margin_shortfalls ENABLE ROW LEVEL SECURITY;
    ALTER TABLE margin_shortfalls FORCE ROW LEVEL SECURITY;
    CREATE POLICY margin_shortfalls_own ON margin_shortfalls FOR ALL
      USING (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint)
      WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint);
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'theta_app') THEN
        GRANT SELECT, INSERT ON account_charges TO theta_app;
        GRANT USAGE ON SEQUENCE account_charges_id_seq TO theta_app;
        GRANT SELECT, INSERT, UPDATE ON margin_shortfalls TO theta_app;
      END IF;
    END $$;""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS account_charges; DROP TABLE IF EXISTS margin_shortfalls")
