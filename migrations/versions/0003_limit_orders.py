"""Limit orders for the virtual account: open (resting) orders, and the limit price on every fill.

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE orders
      ADD COLUMN order_type TEXT NOT NULL DEFAULT 'LIMIT' CHECK (order_type = 'LIMIT'),
      ADD COLUMN limit_price NUMERIC(12,2);

    -- A limit order that hasn't filled yet. It fills when the market reaches its price, or
    -- expires at the close of the session it is valid for.
    CREATE TABLE pending_orders (
      id             BIGSERIAL PRIMARY KEY,
      user_id        BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      symbol         TEXT NOT NULL,
      expiry         DATE NOT NULL,
      side           TEXT NOT NULL CHECK (side IN ('CE', 'PE')),
      strike         NUMERIC(12,2) NOT NULL,
      action         TEXT NOT NULL CHECK (action IN ('BUY', 'SELL')),
      qty            INTEGER NOT NULL CHECK (qty > 0),
      lot_size       INTEGER NOT NULL CHECK (lot_size > 0),
      limit_price    NUMERIC(12,2) NOT NULL CHECK (limit_price > 0),
      reason         TEXT NOT NULL,
      note           TEXT,
      sl_mode        TEXT NOT NULL DEFAULT 'auto' CHECK (sl_mode IN ('auto', 'alert', 'off')),
      blocked_margin NUMERIC(14,2) NOT NULL DEFAULT 0,
      valid_until    DATE NOT NULL,
      status         TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'filled', 'cancelled', 'expired')),
      fill_price     NUMERIC(12,2),
      created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX pending_orders_user_status ON pending_orders (user_id, status);
    ALTER TABLE pending_orders ENABLE ROW LEVEL SECURITY;
    ALTER TABLE pending_orders FORCE ROW LEVEL SECURITY;
    CREATE POLICY pending_orders_owner ON pending_orders
      USING (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint)
      WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint);
    """)
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'theta_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON pending_orders TO theta_app;
        GRANT USAGE, SELECT ON SEQUENCE pending_orders_id_seq TO theta_app;
      END IF;
    END $$;""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS pending_orders")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS order_type, DROP COLUMN IF EXISTS limit_price")
