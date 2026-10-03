"""Email nudges opt-out (retention plan, phase 1).

`user_prefs.email_nudges`: the day-before emails for a stop-loss arming or a time exit. On unless
the user turns it off. user_prefs is already granted to the app role as a whole table.

Revision ID: 0028
Revises: 0027
"""
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE user_prefs ADD COLUMN email_nudges BOOLEAN NOT NULL DEFAULT true")


def downgrade():
    op.execute("ALTER TABLE user_prefs DROP COLUMN IF EXISTS email_nudges")
