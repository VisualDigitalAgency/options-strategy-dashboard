"""Email verification on sign-up (issue #45).

A new sign-up starts as `unverified` and gets a 6-digit code by email. Entering it moves the
account to `pending`, where the admin approves it as before. The code is stored only as a hash,
with its expiry, a wrong-guess counter and when it was last sent (for the resend throttle).
Accounts that exist already are marked verified: they were approved without this step.
`unblocked_at` is set when the admin unblocks a sign-up that passed its 14 days: the 14 days
and the daily code limit then count from it.

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE users DROP CONSTRAINT users_status_check;
    ALTER TABLE users ADD CONSTRAINT users_status_check
      CHECK (status IN ('unverified', 'pending', 'active', 'rejected', 'disabled'));
    ALTER TABLE users
      ADD COLUMN email_verified_at     TIMESTAMPTZ,
      ADD COLUMN email_code_hash       TEXT,
      ADD COLUMN email_code_expires_at TIMESTAMPTZ,
      ADD COLUMN email_code_attempts   INT NOT NULL DEFAULT 0,
      ADD COLUMN email_code_sent_at    TIMESTAMPTZ,
      ADD COLUMN unblocked_at          TIMESTAMPTZ;
    UPDATE users SET email_verified_at = created_at;
    """)


def downgrade():
    op.execute("""
    UPDATE users SET status = 'pending' WHERE status = 'unverified';
    ALTER TABLE users
      DROP COLUMN IF EXISTS email_verified_at, DROP COLUMN IF EXISTS email_code_hash,
      DROP COLUMN IF EXISTS email_code_expires_at, DROP COLUMN IF EXISTS email_code_attempts,
      DROP COLUMN IF EXISTS email_code_sent_at, DROP COLUMN IF EXISTS unblocked_at;
    ALTER TABLE users DROP CONSTRAINT users_status_check;
    ALTER TABLE users ADD CONSTRAINT users_status_check
      CHECK (status IN ('pending', 'active', 'rejected', 'disabled'));
    """)
