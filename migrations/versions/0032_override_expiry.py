"""Time-limited feature grants (retention plan, phase 3).

`user_feature_overrides.expires_at`: a grant that lapses on its own, such as a free month of Pro
for a season champion. NULL keeps an override permanent, as before. The app role already has
SELECT/INSERT/UPDATE/DELETE on the table.

Revision ID: 0032
Revises: 0031
"""
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE user_feature_overrides ADD COLUMN expires_at TIMESTAMPTZ")


def downgrade():
    op.execute("DELETE FROM user_feature_overrides WHERE expires_at IS NOT NULL")
    op.execute("ALTER TABLE user_feature_overrides DROP COLUMN IF EXISTS expires_at")
