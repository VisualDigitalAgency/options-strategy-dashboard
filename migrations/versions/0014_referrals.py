"""Referral links (issue #126, part C). A metric only for now; rewards come later.

- `users.ref_code`: the user's invite code, made the first time they look at their invite link.
- `users.referred_by`: who invited this account, set once at sign-up from `?ref=`.

Revision ID: 0014
Revises: 0013
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE users ADD COLUMN ref_code TEXT UNIQUE;
    ALTER TABLE users ADD COLUMN referred_by BIGINT REFERENCES users(id) ON DELETE SET NULL;
    CREATE INDEX users_referred_by ON users (referred_by) WHERE referred_by IS NOT NULL;
    """)


def downgrade():
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS referred_by, DROP COLUMN IF EXISTS ref_code")
