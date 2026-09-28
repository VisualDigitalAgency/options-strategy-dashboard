"""Self-service password reset (issue #79).

A user who forgot their password gets an emailed link with a random token, valid 24 hours and
usable once. Only its hash is stored, mirroring the sign-up code columns from #6.

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE users
      ADD COLUMN password_reset_token_hash TEXT,
      ADD COLUMN password_reset_expires_at TIMESTAMPTZ,
      ADD COLUMN password_reset_sent_at    TIMESTAMPTZ;
    CREATE UNIQUE INDEX users_password_reset_token_hash_idx
      ON users (password_reset_token_hash) WHERE password_reset_token_hash IS NOT NULL;
    """)


def downgrade():
    op.execute("""
    DROP INDEX IF EXISTS users_password_reset_token_hash_idx;
    ALTER TABLE users
      DROP COLUMN IF EXISTS password_reset_token_hash,
      DROP COLUMN IF EXISTS password_reset_expires_at,
      DROP COLUMN IF EXISTS password_reset_sent_at;
    """)
