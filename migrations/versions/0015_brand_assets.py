"""Owner-editable branding (issue #133).

`brand_assets` holds the uploaded logo and the favicon made from it, already re-encoded to PNG by
the server. The app name lives in `app_settings` under `app_name`. Shared across all users, so no
row-level security; only the owner's admin calls write here.

Revision ID: 0015
Revises: 0014
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE brand_assets (
      kind       TEXT PRIMARY KEY CHECK (kind IN ('logo', 'favicon', 'touch')),
      data       BYTEA NOT NULL,
      sha        TEXT NOT NULL,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_by BIGINT REFERENCES users(id) ON DELETE SET NULL
    );
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'theta_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON brand_assets TO theta_app;
      END IF;
    END $$;""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS brand_assets; DELETE FROM app_settings WHERE key = 'app_name'")
