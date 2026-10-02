# Theta Desk Architecture

> Quick architectural overview of `VisualDigitalAgency/options-strategy-dashboard`.
>
> Theta Desk screens the Nifty 50 for 30+ DTE option-selling setups, calculates risk and margin, and supports virtual/paper trading with live NSE prices. Real Zerodha execution is isolated behind an adapter and is admin-only, manual-confirm-only, and phase-one functionality.

## At a glance

- **Frontend:** React 19 + Vite, React Router, Recharts, Lucide React, CSS.
- **API:** Python 3.12 + Flask, exposing one JSON-RPC 2.0 endpoint at `POST /rpc`.
- **Worker:** A separate Python process for screening, monitoring, auto-trade scheduling, and broker reconciliation.
- **Persistence:** PostgreSQL 16 using SQLAlchemy Core/plain SQL and Alembic migrations.
- **Shared state:** Redis 7 for sessions, throttling, locks, cached results, worker heartbeat, and coordination between API processes.
- **Market data:** NSE option chains, Nifty 50 constituents, NSE SPAN files, and yfinance history.
- **Deployment:** Docker multi-stage images, Caddy, Docker Compose or Coolify.

## Folder structure

```text
.
├── server.py                         # Flask JSON-RPC API, routing, auth gates, error handling
├── rpc_guard.py                      # RPC parameter/type validation and server-only arguments
├── requirements.txt                  # Python runtime dependencies
├── alembic.ini                       # Alembic configuration; migrations/ is the script location
├── Dockerfile                        # Frontend build, Python app, Caddy web images
├── docker-compose.yml                # Self-hosted six-service deployment
├── docker-compose.coolify.yml        # Coolify deployment variant
├── Makefile                          # Local secrets, compose, migration, test helpers
├── README.md                         # Product features, rules, local setup, tests, deployment
├── CONTRIBUTING.md                   # Development and safety conventions
├── CLAUDE.md                         # Detailed implementation architecture notes
├── SECURITY.md                       # Private vulnerability reporting
├── LICENSE                           # Proprietary license
│
├── engine/                           # Backend domain and application modules
│   ├── __init__.py
│   ├── settings.py                   # DB/Redis URLs and secret-file/environment resolution
│   ├── config.py                     # Screening, risk, market-hours, and trading thresholds
│   ├── db.py                         # SQLAlchemy engine, transactions, RLS user context, DB conversion
│   ├── cache.py                      # Redis client, JSON cache, locks, throttles
│   ├── auth.py                       # Registration, login, sessions, password changes, admin auth flows
│   ├── users.py                      # User/account bootstrap and active-user lookup
│   ├── data_fetch.py                 # NSE/yfinance market-data clients and data normalization
│   ├── filters.py                    # PCR and expiry filtering
│   ├── risk_rules.py                 # Setup selection, sentiment, S/R checks, strategy metrics
│   ├── greeks_sr.py                  # Black-Scholes/Greeks and support/resistance calculations
│   ├── span.py                       # NSE SPAN download, XML parsing, cache, margin scan risk
│   ├── batch.py                      # Batched Nifty 50 screen job, progress state, persisted screen cache
│   ├── pivots.py                     # Daily/weekly/monthly floor pivot calculations
│   ├── virtual.py                    # Paper account, orders, fills, positions, margin, exits, monitoring
│   ├── autotrade.py                  # Per-user auto-trade settings, scoring, locking, and runs
│   ├── pricing.py                    # Fair price, tradability, market hours and NSE trading days
│   ├── rms.py                        # Margin shortfall check, RMS square-off, charges and penalties
│   ├── builder.py                    # Strategy builder chain, previews, and the public reader chain
│   ├── strategies.py                 # Saved builder strategies
│   ├── progress.py                   # Trade log, XP ledger, levels and level gates
│   ├── lessons.py                    # Lessons and server-marked quizzes
│   ├── capital.py                    # Virtual capital task milestones and level grants
│   ├── coins.py                      # Coin rewards and one-way exchange into capital
│   ├── leaderboard.py                # Monthly paper-trading leaderboard
│   ├── cards.py                      # Shareable achievement cards and invite links
│   ├── nifty.py                      # Nifty 50 monthly ranges for the Level 6 gate
│   ├── market_calendar.py            # NSE holidays and corporate events
│   ├── permissions.py                # Roles, feature toggles, level unlocks
│   ├── app_settings.py               # Owner switches: auto-approve, reader pages
│   ├── brand.py                      # Owner-editable app name and logo
│   ├── mail.py                       # Outgoing email (verification codes)
│   ├── broker.py                     # Broker connection lifecycle, OAuth state, order preview/coordination
│   ├── broker_crypto.py              # Encryption/decryption of broker credentials at rest
│   ├── worker.py                     # Worker leader lock, heartbeat, screen refresh, scheduled jobs
│   ├── brokers/                      # Broker adapter boundary
│   │   ├── base.py                   # BrokerAdapter interface and session/order value objects
│   │   ├── registry.py               # Broker name-to-adapter registry; Zerodha is connectable
│   │   ├── zerodha.py                # Kite Connect implementation and error translation
│   │   └── poller.py                 # Read-only broker position/margin reconciliation
│   ├── cache/                         # Runtime cache directory; SPAN files and last screen data
│   └── data/                          # Runtime/local data directory
│
├── migrations/                       # Alembic schema history and database environment
│   ├── env.py                        # Runs migrations using the owner database URL
│   ├── script.py.mako                # Migration template
│   └── versions/                     # Versioned schema changes, grants, and RLS policies
│
├── frontend/                         # React/Vite application
│   ├── package.json                   # Frontend scripts and dependencies
│   ├── package-lock.json              # Locked Node dependency tree
│   ├── vite.config.js                # Vite dev/build configuration and API proxy
│   ├── index.html                    # Browser entry document
│   ├── public/                        # Static assets and CSP-compatible theme initialization
│   │   └── theme-init.js             # Applies saved theme before React paints
│   ├── src/
│   │   ├── main.jsx                  # React bootstrap
│   │   ├── App.jsx                   # Routes and application shell
│   │   ├── rpc.js                    # Same-origin JSON-RPC client and RPC error handling
│   │   ├── auth.jsx                  # Auth context, session refresh, theme/palette preferences
│   │   ├── settings.jsx              # Account budget and auto-trade settings context
│   │   ├── format.js                 # Currency, percentage, number, and date formatting
│   │   ├── brokers.js                # Frontend broker metadata
│   │   ├── pages/                    # Route-level screens
│   │   │   ├── Screen.jsx             # Nifty 50 setup/screener page
│   │   │   ├── StockDetail.jsx        # Stock strategy detail, charts, and order ticket
│   │   │   ├── Portfolio.jsx          # Open positions, exits, repricing, and open orders
│   │   │   ├── VirtualAccount.jsx     # Paper account, history, reset, and auto-trade controls
│   │   │   ├── Broker.jsx             # Broker connection and account summary UI
│   │   │   ├── Admin.jsx              # User approval/status and audit activity UI
│   │   │   └── ...                    # Auth, registration, password, and supporting pages
│   │   ├── components/               # Reusable cards, charts, modals, navigation, order UI
│   │   │   ├── OrderModal.jsx         # Virtual and real-order preview/confirmation flow
│   │   │   ├── AutoTrade.jsx          # Auto-trade settings and run history
│   │   │   ├── BrokerOnboarding.jsx   # Post-login broker onboarding
│   │   │   └── ...
│   │   └── styles/                   # Application CSS and responsive layout rules
│   ├── tests/                        # happy-dom UI tests and test runner
│   └── README.md                     # Vite template documentation
│
├── tests/                            # Backend integration scripts
│   ├── run.py                        # Fresh DB/migration/Redis test harness
│   ├── support.py                    # Market-data stubs and shared test helpers
│   └── test_*.py                     # Database, auth, trading, risk, and API tests
│
├── scripts/                          # Operational and development utilities
│   ├── set_admin.py                  # Set/bootstrap an administrator password
│   ├── make_secrets.py               # Generate self-hosted Docker secrets
│   ├── ensure_app_role.py            # Create/synchronize the application DB role
│   ├── dev_db_roles.sql               # Local development DB role setup
│   └── ci_deploy.sh                  # CI deployment/status helper
│
├── deploy/                           # Deployment assets and runbooks
│   ├── Caddyfile                     # Self-hosted TLS, static files, and API proxy
│   ├── Caddyfile.coolify             # Coolify/Traefik-compatible web configuration
│   ├── postgres-init.sh              # Self-hosted initial DB role setup
│   ├── COOLIFY.md                    # Production deployment and rollback notes
│   └── PREVIEW.md                    # Isolated preview environment runbook
│
├── doc/                              # Feature design and implementation notes
│   └── 2026-09-26-broker-integration-phase1-zerodha.md
│
└── .github/workflows/                # CI/CD automation
    └── ci.yml                        # Lint, UI tests, build, backend tests, images, deployment
```

## Runtime architecture

### Request path

1. The browser loads the React bundle from Caddy. In development, Vite serves the bundle and proxies `/rpc` and `/healthz` to the API.
2. Frontend pages call `frontend/src/rpc.js`, which sends JSON-RPC requests to the same origin using the HttpOnly session cookie.
3. `server.py` resolves the method from its RPC method tables, applies authentication/role rules, validates parameters through `rpc_guard.validate`, and dispatches to the relevant `engine` module.
4. The API reads/writes PostgreSQL through `db.tx(user_id)`. User-scoped transactions set `app.user_id`, allowing PostgreSQL row-level security to isolate user-owned records.
5. Redis supplies shared sessions, throttles, cached screen data, locks, and worker health state. This allows multiple gunicorn API processes to remain stateless with respect to request handling.

### Screening flow

1. `engine.worker` owns the scheduled screen refresh and acquires the Redis worker leader lock.
2. `engine.batch.ScreenJob` obtains the Nifty 50 universe from `engine.risk_rules.get_universe()` and processes stocks in batches.
3. `engine.data_fetch` retrieves NSE option chains/history and `engine.span` loads the latest NSE SPAN risk file.
4. `engine.filters`, `engine.risk_rules`, `engine.greeks_sr`, and related helpers calculate PCR, expiry eligibility, strikes, sentiment, S/R checks, Greeks, POP, ROI, and margin.
5. Partial results are published to Redis as batches complete; the last complete result is also persisted in `engine/cache`, so API readers can continue serving the previous screen during a refresh.
6. `frontend/src/pages/Screen.jsx` consumes the screen snapshot, while `StockDetail.jsx` requests heavier symbol-specific data when a user opens a stock.

### Trading flow

- **Virtual orders:** The frontend previews with `va_preview_order`, then submits `va_place_order`. `engine.virtual` re-checks positions, funds, limits, and margin while holding the account/trading locks before booking or opening an order.
- **Monitoring:** The worker checks open orders, stop-loss modes, time exits, profit targets, and expiry settlement during market hours. It also runs per-user auto-trade through `engine.autotrade`.
- **Real broker:** `engine.broker` owns connection and order orchestration. `engine.brokers.base.BrokerAdapter` defines the boundary, `zerodha.py` implements Kite Connect, and `registry.py` selects the adapter. Real order placement requires a fresh explicit confirmation token; `brokers/poller.py` only reconciles read-only positions and margins.

## Data and security boundaries

- **PostgreSQL:** Accounts, users, trades, positions, pending orders, audit records, broker connections, and auto-trade settings. Migrations run with the owner role; the application uses the restricted `theta_app` role.
- **Redis:** Session tokens are stored by hash, not plaintext. It also holds rate limits, locks, screen snapshots, broker OAuth state, and heartbeat data.
- **Broker secrets:** Zerodha credentials are read from environment/secret configuration; access and public tokens are encrypted through `broker_crypto.py` before persistence and are never returned to the frontend.
- **Network edge:** Caddy provides HTTPS/security headers and proxies only `/rpc` and health traffic to the API. The deployment uses isolated Postgres/Redis networks and runs application containers as a non-root user with read-only filesystems where configured.
- **Origin/CSRF protection:** The API validates the request origin configuration, and broker OAuth uses a short-lived, one-time state tied to the admin user.

## Deployment topology

### Self-hosted Compose

```text
Browser
  │ HTTPS
  ▼
web (Caddy + React static build)
  ├── /rpc, /healthz ──► api (gunicorn, server:app)
  └────────────────────► static frontend assets
                         │
                         ├── PostgreSQL 16
                         └── Redis 7

worker (engine.worker) ──► PostgreSQL + Redis + NSE/yfinance
migrate (Alembic owner role) ──► PostgreSQL, once per startup
```

Only `web` publishes host ports. The `api` and `worker` roles use the same `Dockerfile --target app` image with different commands. A second worker waits on the Redis leader lock and takes over if the active worker stops renewing it.

### Coolify

Cloudflare/Traefik terminates the public route before the `web` service. `docker-compose.coolify.yml` uses Coolify environment variables instead of Docker secret files, and the Caddy configuration is baked into the `web-coolify` image rather than bind-mounted. Production deploys are driven by `.github/workflows/ci.yml`; an isolated preview deployment has its own database, Redis, domain, and no broker credentials.

## Local commands

```bash
# Start development dependencies
docker run -d --name theta-pg -e POSTGRES_USER=theta -e POSTGRES_PASSWORD=theta_dev -e POSTGRES_DB=theta -p 127.0.0.1:5433:5432 postgres:16-alpine
docker run -d --name theta-redis -p 127.0.0.1:6380:6379 redis:7-alpine redis-server --requirepass theta_redis_dev --appendonly yes
docker exec -i theta-pg psql -q -U theta -d theta < scripts/dev_db_roles.sql

# Install, migrate, and configure
python -m pip install -r requirements.txt
python -m alembic upgrade head
python scripts/set_admin.py you@example.com

# Run the three local processes
python server.py
python -m engine.worker
npm --prefix frontend install && npm --prefix frontend run dev
```

Run checks with:

```bash
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
make test
```

Backend tests use real Postgres and Redis with external market data stubbed. `tests/run.py` creates a fresh migrated database per test file; set `DB_HOST`, `OWNER_DB_PASSWORD`, `DB_APP_PASSWORD`, and `REDIS_URL` when running outside the provided Docker setup.

## Architectural conventions

- Scheduled work belongs in `engine/worker.py`, never in the API process.
- Every RPC method belongs to exactly one method table in `server.py`; type annotations are part of parameter validation.
- User-owned DB reads/writes use `db.tx(user_id)` and corresponding RLS policies.
- Trading and margin mutations re-check state under locks because API processes, browser tabs, and the worker can act concurrently.
- NSE calls go through existing fetch/cache/throttle paths; do not add per-request exchange calls.
- A new broker should implement `BrokerAdapter` and register one adapter without changing the RPC or database layers.
- Frontend polling stops on component unmount, and the CSP-compatible theme initialization must remain free of inline scripts.

## Source of truth

For implementation details and operational constraints, see:

- [README.md](README.md) — product behavior, rules, metrics, local setup, and deployment.
- [CLAUDE.md](CLAUDE.md) — RPC tables, process responsibilities, security boundaries, and deployment notes.
- [CONTRIBUTING.md](CONTRIBUTING.md) — conventions for DB, trading, background work, brokers, frontend, and tests.
- [deploy/COOLIFY.md](deploy/COOLIFY.md) and [deploy/PREVIEW.md](deploy/PREVIEW.md) — deployment runbooks.
- [doc/2026-09-26-broker-integration-phase1-zerodha.md](doc/2026-09-26-broker-integration-phase1-zerodha.md) — broker integration design.
