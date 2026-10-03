"""Data plan D (#216): where a trade's prices came from. 'live' when the user priced it from their
own broker login; NULL for the end-of-day file or the NSE feed. A live trade never ranks.

Revision ID: 0031
Revises: 0030
"""
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE positions ADD COLUMN price_source text;
    ALTER TABLE trade_results ADD COLUMN price_source text;""")


def downgrade():
    op.execute("""
    ALTER TABLE trade_results DROP COLUMN IF EXISTS price_source;
    ALTER TABLE positions DROP COLUMN IF EXISTS price_source;""")
