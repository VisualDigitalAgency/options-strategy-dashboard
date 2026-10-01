"""Saved strategies in the builder (issue #150, the Level 5 `saved_strategies` unlock).

`saved_strategies` keeps a user's named strategies: stock, expiry and legs (side, strike,
action, lots and the delta each leg had when saved, used to move an expired strategy to a live
expiry). Private to the user under row-level security. Roles start without the feature; Level 5
unlocks it and the owner can grant it.

Revision ID: 0020
Revises: 0019
"""
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE saved_strategies (
      id         BIGSERIAL PRIMARY KEY,
      user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      name       TEXT NOT NULL CHECK (char_length(name) BETWEEN 1 AND 40),
      symbol     TEXT NOT NULL,
      expiry     DATE NOT NULL,
      legs       JSONB NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX saved_strategies_name ON saved_strategies (user_id, lower(name));
    ALTER TABLE saved_strategies ENABLE ROW LEVEL SECURITY;
    ALTER TABLE saved_strategies FORCE ROW LEVEL SECURITY;
    CREATE POLICY saved_strategies_own ON saved_strategies FOR ALL
      USING (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint)
      WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint);
    INSERT INTO role_features (role, feature, enabled) VALUES
      ('sub_admin', 'saved_strategies', false), ('beta', 'saved_strategies', false), ('user', 'saved_strategies', false)
    ON CONFLICT (role, feature) DO NOTHING;
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'theta_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON saved_strategies TO theta_app;
        GRANT USAGE ON SEQUENCE saved_strategies_id_seq TO theta_app;
      END IF;
    END $$;""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS saved_strategies; DELETE FROM role_features WHERE feature = 'saved_strategies'")
