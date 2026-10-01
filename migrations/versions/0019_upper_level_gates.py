"""Gates for Levels 6-10 (issue #146, part of #120).

- `leaderboard_entries.user_id`: who a finished board's row belongs to, for the Level 8 "top 20% of
  their band" check. Nicknames can change, so they can't identify a person across months. Months
  finalised before this have no user id and never count. The public board still shows nicknames
  only (engine/leaderboard.FIELDS).
- `user_levels.final_approved_at` / `final_approved_by`: the owner's sign-off on the Level 10 final
  assessment.

Revision ID: 0019
Revises: 0018
"""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE leaderboard_entries ADD COLUMN user_id BIGINT REFERENCES users(id) ON DELETE SET NULL;
    CREATE INDEX leaderboard_entries_user ON leaderboard_entries (user_id) WHERE user_id IS NOT NULL;
    ALTER TABLE user_levels
      ADD COLUMN final_approved_at TIMESTAMPTZ,
      ADD COLUMN final_approved_by BIGINT REFERENCES users(id) ON DELETE SET NULL;""")


def downgrade():
    op.execute("""
    ALTER TABLE user_levels DROP COLUMN IF EXISTS final_approved_at, DROP COLUMN IF EXISTS final_approved_by;
    DROP INDEX IF EXISTS leaderboard_entries_user;
    ALTER TABLE leaderboard_entries DROP COLUMN IF EXISTS user_id;""")
