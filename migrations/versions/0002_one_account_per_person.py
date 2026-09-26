"""One account per person: canonical email, sign-up IP and the browsers each user signs in from.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE users ADD COLUMN email_canonical TEXT, ADD COLUMN signup_ip INET;
    -- Existing rows: lower-cased email, plus-tag removed; Gmail dots removed too.
    UPDATE users SET email_canonical =
      CASE WHEN split_part(email, '@', 2) IN ('gmail.com', 'googlemail.com')
           THEN replace(split_part(split_part(email, '@', 1), '+', 1), '.', '') || '@gmail.com'
           ELSE split_part(split_part(email, '@', 1), '+', 1) || '@' || split_part(email, '@', 2) END;
    ALTER TABLE users ALTER COLUMN email_canonical SET NOT NULL;
    CREATE UNIQUE INDEX users_email_canonical ON users (email_canonical);

    -- A browser is a random id in a long-lived cookie; only its SHA-256 is stored.
    CREATE TABLE user_devices (
      user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      device_hash TEXT NOT NULL,
      first_seen  TIMESTAMPTZ NOT NULL DEFAULT now(),
      last_seen   TIMESTAMPTZ NOT NULL DEFAULT now(),
      last_ip     INET,
      PRIMARY KEY (user_id, device_hash)
    );
    CREATE INDEX user_devices_hash ON user_devices (device_hash);
    """)
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'theta_app') THEN
        GRANT SELECT, INSERT, UPDATE ON user_devices TO theta_app;
      END IF;
    END $$;""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS user_devices")
    op.execute("DROP INDEX IF EXISTS users_email_canonical")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email_canonical, DROP COLUMN IF EXISTS signup_ip")
