# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Theta Desk: a Nifty 50 options-selling screener (30+ DTE setups) with paper trading on a virtual account. Python/Flask JSON-RPC backend, React (Vite) frontend, PostgreSQL + Redis. Broker execution is not wired; all trading is virtual.

## Commands

Local dev needs the Postgres (port 5433) and Redis (port 6380) dev containers. The `docker run` lines are in README.md. `engine/settings.py` defaults to those containers when no `DB_HOST`/`REDIS_HOST` is set.

```bash
docker exec -i theta-pg psql -q -U theta -d theta < scripts/dev_db_roles.sql   # once: create theta_app role
python -m alembic upgrade head          # migrations (run as owner role)
python server.py                        # API on 127.0.0.1:8000 (POST /rpc, GET /healthz)
python -m engine.worker                 # background worker (separate terminal; required for screens/SL/auto-trade)
python scripts/set_admin.py you@example.com
npm --prefix frontend run dev           # http://localhost:5173, proxies /rpc and /healthz to :8000
npm --prefix frontend run lint          # oxlint
npm --prefix frontend run build
```

There is no test suite.

Docker (self-hosted): `make secrets && make up`, `make migrate`, `make admin EMAIL=...`, `make logs`.

## Architecture

**Processes.** One image (`Dockerfile --target app`) runs three roles:
- `api`: gunicorn `server:app`. It only answers requests and never starts background loops, so any number of API processes is safe.
- `worker` (`engine/worker.py`): the only process that runs scheduled work (screen refresher, SL/time-exit/profit-target monitor, auto-trade scheduler). A Redis leader lock (`lock:worker`) keeps a second worker on standby. The worker exits if it can't renew the lock, so orders never fire twice. `--check` is its health check, and `/healthz` reports worker liveness via `worker:heartbeat`.
- `migrate`: `alembic upgrade head`, run once per start as the owner role.

The `web` target is Caddy serving `frontend/dist` and reverse-proxying `/rpc` and `/healthz` to `api:8000`. Vite's dev proxy mirrors this, so page and API always share one origin.

**RPC layer (`server.py` + `rpc_guard.py`).** Single `POST /rpc` JSON-RPC 2.0 endpoint. Methods are registered in one of five tables, and the table decides auth and how arguments are passed:
- `PUBLIC_METHODS`: no auth; handler gets `ctx`.
- `ACCOUNT_METHODS`: signed in; handler gets `ctx`.
- `METHODS`: signed in; shared market data, called with params only.
- `USER_METHODS`: signed in; the server passes `ctx.user_id` as the first positional argument.
- `ADMIN_METHODS`: admin role; handler gets `ctx`.

`rpc_guard.validate` is the only trust boundary. It introspects the target function's signature: `_`-prefixed params and `user_id` can never be set by a client, and required params and basic annotation types are enforced. Engine functions therefore need accurate type annotations. Wrappers must use `functools.wraps` (see `_then_refresh`) so validate still sees the real signature.

Error handling: raise `ValueError`/`TimeoutError` for errors the user should see. Anything else is logged with a ref id, and the client only gets a generic message.

CSRF protection is an `Origin` header check against `ALLOWED_ORIGINS`. Behind a proxy, `TRUST_PROXY=1` enables a one-hop ProxyFix. Session cookies default to `__Host-` names and require HTTPS.

**Database (`engine/db.py`, `migrations/`).** Two roles:
- Owner (`theta_owner` in Docker, `theta` in dev): used only by migrations.
- `theta_app`: no DDL, `NOBYPASSRLS`. Every user-owned table has row-level security keyed on the `app.user_id` setting. Use `db.tx(user_id)` for per-user access; it sets that setting for the transaction.

Migrations `GRANT` to `theta_app` only if the role already exists. The role must be created first: `deploy/postgres-init.sh` (self-hosted), `scripts/ensure_app_role.py` (Coolify, run by `migrate` before alembic), or `scripts/dev_db_roles.sql` (dev). New tables need their own RLS policy and grants in the migration.

**Redis (`engine/cache.py`).** Holds the shared screen result, quotes, position snapshots, throttles (`cache.Throttle`, which limits how often clients can force NSE calls so the server IP doesn't get blocked), and locks. The API degrades without Redis or a worker, but not without Postgres.

**Engine.**
- `data_fetch.py`: unofficial NSE option-chain v3 API, lot sizes, and yfinance.
- `span.py`: parses NSE SPAN risk files into `engine/cache/`, a volume shared by api and worker.
- `filters.py` / `risk_rules.py` / `greeks_sr.py`: screening rules, Black-Scholes, S/R zones.
- `batch.py`: batched screening.
- `virtual.py`: fills, margin, and the SL monitor.
- `pivots.py`: floor pivots (P, R1–R4, S1–S4) from the last completed day/week/month, for the Portfolio price chart.
- `autotrade.py`, `auth.py`, `users.py`.

Screening thresholds live in `engine/config.py`. README.md documents the trading rules and metric formulas.

**Frontend.** `frontend/src/rpc.js` is the RPC client, and `auth.jsx` holds the session context. Pages are in `src/pages/`. It is responsive down to 320px: wide tables become stacked cards below 1024px. The CSP forbids inline scripts, which is why the theme is set by `public/theme-init.js`.

## Configuration

`engine/settings.py` resolves connections in this order:
1. Explicit `DATABASE_URL` / `MIGRATE_DATABASE_URL` / `REDIS_URL`.
2. Built from `DB_HOST`/`REDIS_HOST` plus passwords. `secret(NAME)` reads the file named by `NAME_FILE` first and falls back to the `NAME` env var.
3. Dev defaults.

## Deployment variants

- `docker-compose.yml` + `deploy/Caddyfile`: self-hosted. Caddy owns 80/443 and TLS. Passwords come from Docker secret files in `./secrets/` (`scripts/make_secrets.py`).
- `docker-compose.coolify.yml` + `deploy/Caddyfile.coolify`: behind Cloudflare → Coolify's Traefik. Caddy serves plain HTTP on `:80` with `auto_https off`. Never bind-mount repo files in this variant: Coolify keeps only the compose file on the host, so such mounts become empty directories. Bake files into an image instead (`Dockerfile --target web-coolify`). Caddy trusts `CF-Connecting-IP` only when Traefik's peer is a Cloudflare range, then sends the visitor IP as the sole `X-Forwarded-For` entry for the API's ProxyFix. Passwords come from Coolify env vars: `DB_OWNER_PASSWORD`, `DB_APP_PASSWORD`, `REDIS_PASSWORD`, plus `DOMAIN`/`PUBLIC_URL` and `ADMIN_EMAIL`. `PUBLIC_URL` must exactly match the public HTTPS origin, or every `/rpc` call gets a 403 from the Origin check.

Self-hosted: Postgres init scripts run only when the `pg_data` volume is first created, so changing the app password later does not update the `theta_app` role. The Coolify variant re-syncs the role password on every deploy.

README's "Portfolio & virtual account" section still mentions SQLite (`virtual.db`). That is outdated: accounts now live in Postgres.
