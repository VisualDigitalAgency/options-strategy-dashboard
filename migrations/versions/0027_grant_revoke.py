"""Revoke a capital grant (issue #194, part of #47).

A revoked grant stays as a row, so its unique (user, task, ref) key still stops the same task
being paid again. The app role may set only these two columns, never edit a grant otherwise.

Revision ID: 0027
Revises: 0026
"""
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE capital_grants ADD COLUMN revoked_at TIMESTAMPTZ;
    ALTER TABLE capital_grants ADD COLUMN revoked_by BIGINT REFERENCES users(id) ON DELETE SET NULL;
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'theta_app') THEN
        GRANT UPDATE (revoked_at, revoked_by) ON capital_grants TO theta_app;
      END IF;
    END $$;""")


def downgrade():
    op.execute("ALTER TABLE capital_grants DROP COLUMN IF EXISTS revoked_by, DROP COLUMN IF EXISTS revoked_at")
