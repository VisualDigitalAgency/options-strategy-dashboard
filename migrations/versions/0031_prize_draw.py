"""Monthly prize draw, off by default (retention plan, "least risky cash shape").

- `user_prefs.prize_draw_opt_in`: entry is explicit; nobody is entered by default.
- `prize_draws`: one row per winner. Written only by the worker and the owner (no app.user_id set);
  a signed-in user reads only their own rows.
Nothing runs until the owner turns on the `prize_draw` setting, and that needs a written legal
opinion first (doc/2026-10-03-prize-draw.md).

Revision ID: 0031
Revises: 0030
"""
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE user_prefs ADD COLUMN prize_draw_opt_in BOOLEAN NOT NULL DEFAULT false;
    CREATE TABLE prize_draws (
      id         BIGSERIAL PRIMARY KEY,
      month      TEXT NOT NULL,
      user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
      prize      NUMERIC(12,2) NOT NULL CHECK (prize > 0),
      tds        NUMERIC(12,2) NOT NULL CHECK (tds >= 0),
      entrants   INTEGER NOT NULL,
      seed       TEXT NOT NULL,
      status     TEXT NOT NULL DEFAULT 'pending_kyc' CHECK (status IN ('pending_kyc', 'paid', 'void')),
      note       TEXT,
      drawn_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ,
      UNIQUE (month, user_id)
    );
    ALTER TABLE prize_draws ENABLE ROW LEVEL SECURITY;
    ALTER TABLE prize_draws FORCE ROW LEVEL SECURITY;
    CREATE POLICY prize_draws_read ON prize_draws FOR SELECT USING (
      COALESCE(current_setting('app.user_id', true), '') = ''
      OR user_id = NULLIF(current_setting('app.user_id', true), '')::bigint);
    CREATE POLICY prize_draws_write ON prize_draws FOR ALL
      USING (COALESCE(current_setting('app.user_id', true), '') = '')
      WITH CHECK (COALESCE(current_setting('app.user_id', true), '') = '');
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'theta_app') THEN
        GRANT SELECT, INSERT, UPDATE ON prize_draws TO theta_app;
        GRANT USAGE, SELECT ON SEQUENCE prize_draws_id_seq TO theta_app;
      END IF;
    END $$;""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS prize_draws")
    op.execute("ALTER TABLE user_prefs DROP COLUMN IF EXISTS prize_draw_opt_in")
