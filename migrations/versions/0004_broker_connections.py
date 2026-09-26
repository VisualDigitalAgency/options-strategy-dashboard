"""Real broker connections (phase 1: Zerodha only) and the real orders placed through them.

Only one broker may be connected per user at a time, enforced by a partial unique index on
`user_id` where `status = 'active'` (same technique as `positions_one_open`).

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    -- One row per broker connection a user has ever made. access_token/public_token are
    -- Fernet-encrypted by engine/broker_crypto.py before they ever reach this table.
    CREATE TABLE broker_connections (
      id                BIGSERIAL PRIMARY KEY,
      user_id           BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      broker            TEXT NOT NULL CHECK (broker IN ('zerodha')),
      status            TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disconnected', 'expired')),
      broker_user_id    TEXT,
      access_token_enc  BYTEA NOT NULL,
      public_token_enc  BYTEA,
      connected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
      token_expires_at  TIMESTAMPTZ NOT NULL,
      disconnected_at   TIMESTAMPTZ,
      last_synced_at    TIMESTAMPTZ
    );
    CREATE UNIQUE INDEX broker_connections_one_active ON broker_connections (user_id) WHERE status = 'active';
    CREATE INDEX broker_connections_user ON broker_connections (user_id);
    ALTER TABLE broker_connections ENABLE ROW LEVEL SECURITY;
    ALTER TABLE broker_connections FORCE ROW LEVEL SECURITY;
    CREATE POLICY broker_connections_owner ON broker_connections
      USING (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint)
      WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint);

    -- Real orders placed at the broker. One row per leg, mirroring `orders`/`positions`'s shape.
    -- Every leg here is a SELL limit order (the app only sells options), placed sequentially:
    -- Kite Connect has no atomic multi-leg order, so a later leg can fail after an earlier one
    -- already filled at the broker; see engine/brokers/zerodha.py for the stop-on-first-failure rule.
    CREATE TABLE broker_orders (
      id              BIGSERIAL PRIMARY KEY,
      user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      broker          TEXT NOT NULL CHECK (broker IN ('zerodha')),
      kite_order_id   TEXT,
      symbol          TEXT NOT NULL,
      expiry          DATE NOT NULL,
      side            TEXT NOT NULL CHECK (side IN ('CE', 'PE')),
      strike          NUMERIC(12,2) NOT NULL,
      qty             INTEGER NOT NULL CHECK (qty > 0),
      limit_price     NUMERIC(12,2) NOT NULL CHECK (limit_price > 0),
      leg_index       INTEGER NOT NULL,
      status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'open', 'complete', 'rejected', 'cancelled')),
      reject_reason   TEXT,
      created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX broker_orders_user_status ON broker_orders (user_id, status);
    ALTER TABLE broker_orders ENABLE ROW LEVEL SECURITY;
    ALTER TABLE broker_orders FORCE ROW LEVEL SECURITY;
    CREATE POLICY broker_orders_owner ON broker_orders
      USING (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint)
      WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint);
    """)
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'theta_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON broker_connections TO theta_app;
        GRANT USAGE, SELECT ON SEQUENCE broker_connections_id_seq TO theta_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON broker_orders TO theta_app;
        GRANT USAGE, SELECT ON SEQUENCE broker_orders_id_seq TO theta_app;
      END IF;
    END $$;""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS broker_orders")
    op.execute("DROP TABLE IF EXISTS broker_connections")
