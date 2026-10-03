"""Season champion certificates (retention plan, phase 2).

A share card of kind 'season' for a month's champion; `ref` is the month as YYYYMM.

Revision ID: 0029
Revises: 0028
"""
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE share_cards DROP CONSTRAINT IF EXISTS share_cards_kind_check;
    ALTER TABLE share_cards ADD CONSTRAINT share_cards_kind_check CHECK (kind IN ('level', 'course', 'season'));""")


def downgrade():
    op.execute("""
    DELETE FROM share_cards WHERE kind = 'season';
    ALTER TABLE share_cards DROP CONSTRAINT IF EXISTS share_cards_kind_check;
    ALTER TABLE share_cards ADD CONSTRAINT share_cards_kind_check CHECK (kind IN ('level', 'course'));""")
