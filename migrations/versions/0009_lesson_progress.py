"""Lesson quiz progress for the learning path (issue #124).

One row per user and lesson: attempts, best score, when it was first passed, and when a failed quiz
may be retaken. The XP ledger (#122) reads `passed_at` to award lesson XP once.

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE lesson_progress (
      user_id          BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      slug             TEXT NOT NULL,
      attempts         INTEGER NOT NULL DEFAULT 0,
      best_score       INTEGER NOT NULL DEFAULT 0 CHECK (best_score BETWEEN 0 AND 100),
      passed_at        TIMESTAMPTZ,
      last_attempt_at  TIMESTAMPTZ,
      retry_at         TIMESTAMPTZ,
      PRIMARY KEY (user_id, slug)
    );
    ALTER TABLE lesson_progress ENABLE ROW LEVEL SECURITY;
    ALTER TABLE lesson_progress FORCE ROW LEVEL SECURITY;
    CREATE POLICY lesson_progress_owner ON lesson_progress
      USING (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint)
      WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint);
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'theta_app') THEN
        GRANT SELECT, INSERT, UPDATE ON lesson_progress TO theta_app;
      END IF;
    END $$;
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS lesson_progress")
