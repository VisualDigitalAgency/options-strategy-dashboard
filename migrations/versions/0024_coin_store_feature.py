"""The `coin_store` feature (issue #175): the Coin store page, off for every role until the owner
switches it on (Admin → Features, or a per-user grant). Levels never unlock it.

Revision ID: 0024
Revises: 0023
"""
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    INSERT INTO role_features (role, feature, enabled) VALUES
      ('sub_admin', 'coin_store', false), ('beta', 'coin_store', false), ('user', 'coin_store', false)
    ON CONFLICT (role, feature) DO NOTHING""")


def downgrade():
    op.execute("DELETE FROM role_features WHERE feature = 'coin_store'; "
               "DELETE FROM user_feature_overrides WHERE feature = 'coin_store'")
