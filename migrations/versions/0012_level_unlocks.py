"""Levels unlock features, owner overrides per user, and the Level 6 Beta promotion (issue #123).

- `user_feature_overrides`: the owner's per-user grant or deny for one feature. Admin data like
  `role_features` (no RLS; only owner-gated RPCs touch it).
- `user_levels.auto_beta`: set once the Level 6 promotion has been considered, so an owner's later
  demotion from Beta is never undone by the nightly evaluation.

Revision ID: 0012
Revises: 0011
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE user_feature_overrides (
      user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      feature TEXT NOT NULL,
      mode    TEXT NOT NULL CHECK (mode IN ('grant', 'deny')),
      set_by  BIGINT REFERENCES users(id),
      set_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (user_id, feature)
    );
    ALTER TABLE user_levels ADD COLUMN auto_beta BOOLEAN NOT NULL DEFAULT false;
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'theta_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON user_feature_overrides TO theta_app;
      END IF;
    END $$;
    """)


def downgrade():
    op.execute("ALTER TABLE user_levels DROP COLUMN IF EXISTS auto_beta")
    op.execute("DROP TABLE IF EXISTS user_feature_overrides")
