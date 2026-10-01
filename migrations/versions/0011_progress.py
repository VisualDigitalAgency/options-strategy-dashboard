"""Learning-path progress: trade log, XP ledger and levels (issue #122, part of #120).

- `positions.entry_delta`: |delta| of a short leg when it opened, so "sold below 0.15" can be scored.
  Null for buys and for limit orders that filled later.
- `trade_results`: one row per closed position, written when it closes. A virtual-account reset
  deletes orders and positions but not this, so rolling metrics survive it (a reset only restarts
  the current level's gate, via accounts.created_at).
- `xp_ledger`: append-only awards and deductions. (user_id, reason, ref) is unique, so the same
  event can never score twice.
- `user_levels`: current level and when it was reached.

Revision ID: 0011
Revises: 0010
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

TABLES = ("trade_results", "xp_ledger", "user_levels")


def upgrade():
    op.execute("""
    ALTER TABLE positions ADD COLUMN entry_delta NUMERIC(6,4);

    CREATE TABLE trade_results (
      id            BIGSERIAL PRIMARY KEY,
      user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      position_id   BIGINT,
      symbol        TEXT NOT NULL,
      expiry        DATE NOT NULL,
      side          TEXT NOT NULL,
      strike        NUMERIC(12,2) NOT NULL,
      short         BOOLEAN NOT NULL,
      lots          INTEGER NOT NULL,
      avg_price     NUMERIC(12,4) NOT NULL,
      exit_price    NUMERIC(12,2),
      realized_pnl  NUMERIC(14,2) NOT NULL,
      capital       NUMERIC(14,2) NOT NULL,
      opened_at     TIMESTAMPTZ NOT NULL,
      closed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
      exit_reason   TEXT NOT NULL,
      had_sl        BOOLEAN NOT NULL,
      entry_delta   NUMERIC(6,4)
    );
    CREATE INDEX trade_results_user_closed ON trade_results (user_id, closed_at);

    CREATE TABLE xp_ledger (
      id      BIGSERIAL PRIMARY KEY,
      user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
      points  INTEGER NOT NULL,
      reason  TEXT NOT NULL,
      ref     TEXT NOT NULL,
      UNIQUE (user_id, reason, ref)
    );

    CREATE TABLE user_levels (
      user_id     BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
      level       INTEGER NOT NULL DEFAULT 1 CHECK (level BETWEEN 1 AND 10),
      level_since TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    for t in TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY {t}_owner ON {t}
            USING (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint)
            WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint)""")
    # Logs are append-only for the app: no UPDATE or DELETE on trade_results or xp_ledger.
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'theta_app') THEN
        GRANT SELECT, INSERT ON trade_results, xp_ledger TO theta_app;
        GRANT SELECT, INSERT, UPDATE ON user_levels TO theta_app;
        GRANT USAGE, SELECT ON SEQUENCE trade_results_id_seq, xp_ledger_id_seq TO theta_app;
      END IF;
    END $$;""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS user_levels, xp_ledger, trade_results")
    op.execute("ALTER TABLE positions DROP COLUMN IF EXISTS entry_delta")
