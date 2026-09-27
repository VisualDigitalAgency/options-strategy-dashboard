"""Broker-side stop losses for real orders (issue #43).

Real entries stay plain SELL LIMIT orders. Once a filled leg is SL_GRACE_DAYS old, the worker
installs a Kite "Alert Triggers Order" (ATO) alert for it: when the option's LTP reaches the stop
(the original premium), Kite itself places the BUY that closes the leg. Nothing is edited later;
these columns track the fill and that alert.

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE broker_orders
      ADD COLUMN average_price      NUMERIC(12,2),
      ADD COLUMN filled_at          TIMESTAMPTZ,
      ADD COLUMN sl_price           NUMERIC(12,2),
      ADD COLUMN sl_alert_uuid      TEXT,
      -- pending (not due / not filled yet) -> enabled (installed at Kite) -> triggered | disabled |
      -- deleted | cancelled (removed by us: the position was closed first) | skipped (never installed)
      ADD COLUMN sl_alert_status    TEXT NOT NULL DEFAULT 'pending'
        CHECK (sl_alert_status IN ('pending', 'enabled', 'triggered', 'disabled', 'deleted', 'cancelled', 'skipped')),
      ADD COLUMN sl_alert_error     TEXT,
      ADD COLUMN sl_alert_tried_at  TIMESTAMPTZ;
    """)


def downgrade():
    op.execute("""
    ALTER TABLE broker_orders
      DROP COLUMN IF EXISTS average_price, DROP COLUMN IF EXISTS filled_at, DROP COLUMN IF EXISTS sl_price,
      DROP COLUMN IF EXISTS sl_alert_uuid, DROP COLUMN IF EXISTS sl_alert_status,
      DROP COLUMN IF EXISTS sl_alert_error, DROP COLUMN IF EXISTS sl_alert_tried_at;
    """)
