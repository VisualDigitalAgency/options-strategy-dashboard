"""Shareable achievement cards (issue #126, part of #120).

`share_cards` holds a frozen snapshot of what a card shows (nickname, level, course, optional %
return), keyed by a random slug. Cards are public by design, so anyone may read a row; only the
owner can create or delete theirs. The snapshot never holds an email or a rupee amount.

Revision ID: 0013
Revises: 0012
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE share_cards (
      slug        TEXT PRIMARY KEY,
      user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      kind        TEXT NOT NULL CHECK (kind IN ('level', 'course')),
      ref         INTEGER NOT NULL,
      show_return BOOLEAN NOT NULL,
      payload     JSONB NOT NULL,
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE (user_id, kind, ref, show_return)
    );
    ALTER TABLE share_cards ENABLE ROW LEVEL SECURITY;
    ALTER TABLE share_cards FORCE ROW LEVEL SECURITY;
    CREATE POLICY share_cards_read ON share_cards FOR SELECT USING (true);
    CREATE POLICY share_cards_write ON share_cards FOR INSERT
      WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint);
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'theta_app') THEN
        GRANT SELECT, INSERT ON share_cards TO theta_app;
      END IF;
    END $$;""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS share_cards")
