"""The screener becomes a Pro feature (issue #136).

New `screener` feature: on for sub-admins and beta, off for plain users. Pro users get it through
the owner's per-user grant. Every account that exists now keeps it (a grant), so nobody loses the
screener on the day this ships. Auto-trade trades the screen's picks, so it needs `screener` too
(engine/permissions.py).

Revision ID: 0016
Revises: 0015
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    INSERT INTO role_features (role, feature, enabled) VALUES
      ('sub_admin', 'screener', true), ('beta', 'screener', true), ('user', 'screener', false)
    ON CONFLICT (role, feature) DO NOTHING;
    INSERT INTO user_feature_overrides (user_id, feature, mode)
      SELECT id, 'screener', 'grant' FROM users WHERE role = 'user'
    ON CONFLICT (user_id, feature) DO NOTHING;""")


def downgrade():
    op.execute("""
    DELETE FROM user_feature_overrides WHERE feature = 'screener';
    DELETE FROM role_features WHERE feature = 'screener';""")
