"""Market Calendar becomes the Level 3 unlock (issue #165).

Existing accounts keep it: every `user`/`beta` account whose role has it on today gets a per-user
grant (set_by NULL marks it as this migration's), unless the owner already set an override for it.
Then the two roles stop having it, so new accounts unlock it at Level 3.

Revision ID: 0021
Revises: 0020
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    INSERT INTO user_feature_overrides (user_id, feature, mode)
      SELECT u.id, 'market_calendar', 'grant' FROM users u
      JOIN role_features r ON r.role = u.role AND r.feature = 'market_calendar' AND r.enabled
      WHERE u.role IN ('user', 'beta')
    ON CONFLICT (user_id, feature) DO NOTHING;
    UPDATE role_features SET enabled = false, updated_at = now()
      WHERE feature = 'market_calendar' AND role IN ('user', 'beta');
    """)


def downgrade():
    op.execute("""
    UPDATE role_features SET enabled = true, updated_at = now()
      WHERE feature = 'market_calendar' AND role IN ('user', 'beta');
    DELETE FROM user_feature_overrides WHERE feature = 'market_calendar' AND mode = 'grant' AND set_by IS NULL;
    """)
