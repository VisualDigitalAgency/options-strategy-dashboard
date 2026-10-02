"""Stop-loss orders on the virtual account (issue #183): SL (trigger + limit) and SL-M (trigger, then
market), placed on an open leg to exit it.

`pending_orders` gains `order_type` (limit | sl | slm), `trigger_price` and `triggered_at`. An SL
or SL-M order waits untriggered until the price reaches the trigger; then SL-M fills at the touch
and SL becomes an ordinary limit order.

Revision ID: 0026
Revises: 0025
"""
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE pending_orders
      ADD COLUMN order_type    TEXT NOT NULL DEFAULT 'limit' CHECK (order_type IN ('limit', 'sl', 'slm')),
      ADD COLUMN trigger_price NUMERIC(12,2) CHECK (trigger_price IS NULL OR trigger_price > 0),
      ADD COLUMN triggered_at  TIMESTAMPTZ,
      ADD CONSTRAINT pending_orders_trigger CHECK ((order_type = 'limit') = (trigger_price IS NULL))""")


def downgrade():
    op.execute("""
    DELETE FROM pending_orders WHERE order_type <> 'limit';
    ALTER TABLE pending_orders DROP CONSTRAINT IF EXISTS pending_orders_trigger,
      DROP COLUMN IF EXISTS triggered_at, DROP COLUMN IF EXISTS trigger_price, DROP COLUMN IF EXISTS order_type""")
