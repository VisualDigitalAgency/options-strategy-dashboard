"""Buy legs in the strategy builder (issue #137).

`hedges` (buying an option leg on its own) is unlocked by Level 6; roles start without it, and the
owner can toggle it per role or grant it per account. Without it a buy must protect a sell.
The builder itself is open to everyone, so Level 2's `option_builder` unlock is gone (config).

Revision ID: 0017
Revises: 0016
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    INSERT INTO role_features (role, feature, enabled) VALUES
      ('sub_admin', 'hedges', false), ('beta', 'hedges', false), ('user', 'hedges', false)
    ON CONFLICT (role, feature) DO NOTHING;""")


def downgrade():
    op.execute("DELETE FROM role_features WHERE feature = 'hedges'")
