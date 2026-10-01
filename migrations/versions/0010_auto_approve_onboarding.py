"""Sign-ups without the manual-approval wall, plus first-login onboarding (issue #121).

- `app_settings`: owner-managed switches. `auto_approve` (on by default) makes a confirmed email
  enough to use the app; with it off, new accounts wait in `pending` as before.
- `users.nickname` (unique, case-insensitive) and `users.leaderboard_opt_in`, asked once on first
  login and used by the leaderboard (#125).

Revision ID: 0010
Revises: 0009
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE app_settings (
      key        TEXT PRIMARY KEY,
      value      JSONB NOT NULL,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_by BIGINT REFERENCES users(id)
    );
    INSERT INTO app_settings (key, value) VALUES ('auto_approve', 'true');
    ALTER TABLE users
      ADD COLUMN nickname           TEXT,
      ADD COLUMN leaderboard_opt_in BOOLEAN NOT NULL DEFAULT false;
    CREATE UNIQUE INDEX users_nickname_lower ON users (lower(nickname)) WHERE nickname IS NOT NULL;
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'theta_app') THEN
        GRANT SELECT, INSERT, UPDATE ON app_settings TO theta_app;
      END IF;
    END $$;
    """)


def downgrade():
    op.execute("""
    DROP INDEX IF EXISTS users_nickname_lower;
    ALTER TABLE users DROP COLUMN IF EXISTS nickname, DROP COLUMN IF EXISTS leaderboard_opt_in;
    DROP TABLE IF EXISTS app_settings;
    """)
