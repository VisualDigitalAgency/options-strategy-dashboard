"""Initial multi-user schema: users, per-user virtual accounts, row-level security.

Revision ID: 0001
Revises:
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Tables whose rows belong to one user. Each gets an RLS policy on app.user_id.
# NULLIF: a pooled connection that served a user earlier reads the setting back as '', not NULL.
USER_TABLES = ("accounts", "positions", "orders", "autotrade_settings", "autotrade_runs", "user_prefs")

SCHEMA = """
CREATE TABLE users (
  id                   BIGSERIAL PRIMARY KEY,
  email                TEXT NOT NULL UNIQUE CHECK (email = lower(email)),
  name                 TEXT NOT NULL,
  password_hash        TEXT,
  role                 TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
  status               TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'rejected', 'disabled')),
  approved_by          BIGINT REFERENCES users(id),
  approved_at          TIMESTAMPTZ,
  must_change_password BOOLEAN NOT NULL DEFAULT false,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_login_at        TIMESTAMPTZ
);

CREATE TABLE audit_log (
  id             BIGSERIAL PRIMARY KEY,
  ts             TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor_id       BIGINT REFERENCES users(id),
  action         TEXT NOT NULL,
  target_user_id BIGINT REFERENCES users(id),
  ip             INET,
  detail         JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX audit_log_ts ON audit_log (ts DESC);

CREATE TABLE accounts (
  user_id          BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  starting_capital NUMERIC(14,2) NOT NULL CHECK (starting_capital > 0),
  sl_mode_default  TEXT NOT NULL DEFAULT 'auto' CHECK (sl_mode_default IN ('auto', 'alert', 'off')),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE positions (
  id              BIGSERIAL PRIMARY KEY,
  user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  symbol          TEXT NOT NULL,
  expiry          DATE NOT NULL,
  side            TEXT NOT NULL CHECK (side IN ('CE', 'PE')),
  strike          NUMERIC(12,2) NOT NULL,
  qty             INTEGER NOT NULL,
  avg_price       NUMERIC(12,4) NOT NULL,
  lot_size        INTEGER NOT NULL CHECK (lot_size > 0),
  status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
  opened_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  closed_at       TIMESTAMPTZ,
  realized_pnl    NUMERIC(14,2) NOT NULL DEFAULT 0,
  exit_price      NUMERIC(12,2),
  sl_mode         TEXT NOT NULL DEFAULT 'off' CHECK (sl_mode IN ('auto', 'alert', 'off')),
  sl_price        NUMERIC(12,4),
  sl_activates_on DATE,
  sl_alert_at     TIMESTAMPTZ
);
CREATE INDEX positions_user_status ON positions (user_id, status);
-- One open row per contract per user: _apply_trade nets into it.
CREATE UNIQUE INDEX positions_one_open ON positions (user_id, symbol, expiry, side, strike) WHERE status = 'open';

CREATE TABLE orders (
  id           BIGSERIAL PRIMARY KEY,
  user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  position_id  BIGINT REFERENCES positions(id) ON DELETE SET NULL,
  ts           TIMESTAMPTZ NOT NULL DEFAULT now(),
  symbol       TEXT NOT NULL,
  expiry       DATE NOT NULL,
  side         TEXT NOT NULL CHECK (side IN ('CE', 'PE')),
  strike       NUMERIC(12,2) NOT NULL,
  action       TEXT NOT NULL CHECK (action IN ('BUY', 'SELL')),
  qty          INTEGER NOT NULL CHECK (qty > 0),
  price        NUMERIC(12,2) NOT NULL,
  reason       TEXT NOT NULL,
  realized_pnl NUMERIC(14,2) NOT NULL DEFAULT 0,
  note         TEXT
);
CREATE INDEX orders_user_ts ON orders (user_id, ts DESC, id DESC);

CREATE TABLE autotrade_settings (
  user_id       BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  enabled       BOOLEAN NOT NULL DEFAULT false,
  run_at        TEXT NOT NULL DEFAULT '10:00' CHECK (run_at ~ '^\\d{2}:\\d{2}$'),
  min_pop       NUMERIC(5,2) NOT NULL DEFAULT 85,
  reserve_pct   NUMERIC(5,2) NOT NULL DEFAULT 20,
  max_trade_pct NUMERIC(5,2) NOT NULL DEFAULT 10,
  last_run_date DATE
);

CREATE TABLE autotrade_runs (
  id      BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
  trigger TEXT NOT NULL,
  placed  INTEGER NOT NULL,
  summary JSONB NOT NULL
);
CREATE INDEX autotrade_runs_user_ts ON autotrade_runs (user_id, id DESC);

CREATE TABLE user_prefs (
  user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  theme   TEXT,
  palette TEXT
);
"""


def upgrade():
    op.execute(SCHEMA)
    for t in USER_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY {t}_owner ON {t}
            USING (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint)
            WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::bigint)""")
    # The app role reads and writes rows only. It can add audit entries but never change or delete them.
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'theta_app') THEN
        GRANT USAGE ON SCHEMA public TO theta_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON users, accounts, positions, orders,
              autotrade_settings, autotrade_runs, user_prefs TO theta_app;
        GRANT SELECT, INSERT ON audit_log TO theta_app;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO theta_app;
      END IF;
    END $$;""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS user_prefs, autotrade_runs, autotrade_settings, orders, positions, "
               "accounts, audit_log, users CASCADE")
