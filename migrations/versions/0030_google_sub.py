"""Sign in with Google: the Google account id (`sub`) linked to a user, null for password-only users.

Revision ID: 0030
Revises: 0029
"""
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE users ADD COLUMN google_sub text;
    CREATE UNIQUE INDEX users_google_sub ON users (google_sub) WHERE google_sub IS NOT NULL;""")


def downgrade():
    op.execute("DROP INDEX IF EXISTS users_google_sub; ALTER TABLE users DROP COLUMN IF EXISTS google_sub;")
