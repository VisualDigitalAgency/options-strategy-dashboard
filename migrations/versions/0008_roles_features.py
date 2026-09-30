"""Role hierarchy and owner-managed feature toggles (issue #46).

Roles: owner (exactly one), sub_admin, beta, user. The first admin becomes the owner, any other
admins become sub-admins. `role_features` holds which feature each non-owner role has; the owner
has every feature and is not stored. The feature list itself lives in engine/permissions.py.
Seeds match what each role could do before this migration, except that sub-admins (former extra
admins) no longer connect a broker until the owner turns live trading on for them.

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

SEED = {
    "sub_admin": ("manage_users", "manage_roles", "autotrade", "market_calendar"),
    "beta": ("autotrade", "market_calendar"),
    "user": ("autotrade", "market_calendar"),
}
FEATURES = ("manage_users", "manage_roles", "live_trading", "autotrade", "market_calendar")


def upgrade():
    op.execute("""
    ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
    UPDATE users SET role = 'owner' WHERE id = (SELECT min(id) FROM users WHERE role = 'admin');
    UPDATE users SET role = 'sub_admin' WHERE role = 'admin';
    ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('owner', 'sub_admin', 'beta', 'user'));
    CREATE UNIQUE INDEX users_one_owner ON users ((true)) WHERE role = 'owner';

    CREATE TABLE role_features (
      role       TEXT NOT NULL CHECK (role IN ('sub_admin', 'beta', 'user')),
      feature    TEXT NOT NULL,
      enabled    BOOLEAN NOT NULL,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_by BIGINT REFERENCES users(id),
      PRIMARY KEY (role, feature)
    );
    """)
    rows = ", ".join(f"('{r}', '{f}', {'true' if f in on else 'false'})" for r, on in SEED.items() for f in FEATURES)
    op.execute(f"INSERT INTO role_features (role, feature, enabled) VALUES {rows}")
    # Global settings, not user-owned rows: no RLS. The app may read and flip them, never add or drop.
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'theta_app') THEN
        GRANT SELECT, UPDATE ON role_features TO theta_app;
      END IF;
    END $$;""")


def downgrade():
    op.execute("""
    DROP TABLE IF EXISTS role_features;
    DROP INDEX IF EXISTS users_one_owner;
    ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
    UPDATE users SET role = 'admin' WHERE role IN ('owner', 'sub_admin');
    UPDATE users SET role = 'user' WHERE role = 'beta';
    ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('admin', 'user'));
    """)
