# Theta Desk: options selling screener

![Python](https://img.shields.io/badge/Python-3.12-3776ab?logo=python&logoColor=white)
![JavaScript](https://img.shields.io/badge/JavaScript-ES2024-f7df1e?logo=javascript&logoColor=black)
![React](https://img.shields.io/badge/React-19-61dafb?logo=react&logoColor=black)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-dc382d?logo=redis&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-JSON--RPC-000000?logo=flask&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-Latest-646cff?logo=vite&logoColor=white)
![License](https://img.shields.io/badge/License-Proprietary-red)

**Progress:** ![Core Features](https://img.shields.io/badge/Core_Features-Complete-green) ![Virtual Trading](https://img.shields.io/badge/Virtual_Trading-Complete-green) ![Real Broker Integration](https://img.shields.io/badge/Real_Broker_Integration-Alpha-yellow) ![Admin Dashboard](https://img.shields.io/badge/Admin_Dashboard-Complete-green)

Screens every Nifty 50 stock for 30+ DTE option-selling setups and trades them on a virtual (paper) account with live NSE prices. Real broker execution (Zerodha) exists but is soft-launched to admi[...]

Live: https://theta.connectbiomedical.com (sign-in required; new users are approved by the admin).

**Stack:** Python 3.12 / Flask JSON-RPC API, a background worker, PostgreSQL 16, Redis 7, React 19 (Vite) frontend, Caddy in front.

## Tech Stack

### Backend

| Component | Technology | Details |
|-----------|-----------|---------|
| **API Server** | Python 3.12 | Flask JSON-RPC 2.0, gunicorn WSGI |
| **Background Worker** | Python 3.12 | Screen refresher, stop-loss monitor, auto-trade scheduler |
| **Database** | PostgreSQL 16 | Row-level security, Alembic migrations |
| **Cache & Locks** | Redis 7 | Shared caches, throttles, worker leader lock |
| **Web Server** | Caddy | HTTPS, security headers, reverse proxy |

### Frontend

| Component | Technology | Details |
|-----------|-----------|---------|
| **Framework** | React 19 | UI components, state management |
| **Build Tool** | Vite | Fast development server, optimized builds |
| **Styling** | CSS3 | Responsive design (320px–4K) |
| **Charts** | Recharts | Payoff diagrams, price & pivot levels |
| **Linting** | Oxlint | Fast, strict code quality checks |
| **Testing** | happy-dom | UI component tests |

### Market Data & Integrations

- **NSE Option Chain API v3** — Live option premiums, Greeks, open interest
- **NSE SPAN Files** — Real margin requirements per strike & expiry
- **yfinance** — Historical price data, volatility calibration
- **Zerodha Kite API** — Real broker execution (admin-only, phase 1)

### Language Composition

![JavaScript 41.3%](https://img.shields.io/badge/JavaScript-41.3%25-f7df1e?style=flat-square)
![Python 41.3%](https://img.shields.io/badge/Python-41.3%25-3776ab?style=flat-square)
![CSS 15.6%](https://img.shields.io/badge/CSS-15.6%25-563d7c?style=flat-square)
![Shell 0.9%](https://img.shields.io/badge/Shell-0.9%25-4eaa25?style=flat-square)
![Other 0.9%](https://img.shields.io/badge/Other-0.9%25-cccccc?style=flat-square)

## Contents

- [Tech Stack](#tech-stack)
- [Run locally](#run-locally)
- [Tests](#tests)
- [Features](#features)
- [Rules](#rules-edit-in-engineconfigpy) · [Trade metrics](#trade-metrics) · [Strategy lab](#strategy-lab-stock-detail-page) · [Portfolio & virtual account](#portfolio--virtual-account) · [Pri[...]
- [Layout](#layout)
- [Deploy](#deploy)
- [Known limits](#known-limits)
- [Contributing, security, licence](#contributing-security-licence)

## Run locally

Postgres holds accounts and trades; Redis holds shared caches, throttles and locks. Start both once with Docker:

```bash
docker run -d --name theta-pg -e POSTGRES_USER=theta -e POSTGRES_PASSWORD=theta_dev -e POSTGRES_DB=theta -p 127.0.0.1:5433:5432 postgres:16-alpine
docker run -d --name theta-redis -p 127.0.0.1:6380:6379 redis:7-alpine redis-server --requirepass theta_redis_dev --appendonly yes
docker exec -i theta-pg psql -q -U theta -d theta < scripts/dev_db_roles.sql   # creates the theta_app role
```

Then install and migrate:

```bash
python -m pip install -r requirements.txt
python -m alembic upgrade head
python scripts/set_admin.py you@example.com    # asks for the admin password (hidden)
```

Migrations run as the owner role; the app connects as `theta_app`, which has no DDL rights and, through row-level security, sees only the signed-in user's rows. `engine/settings.py` defaults to th[...]

Run three processes, each in its own terminal:

```bash
python server.py            # API on 127.0.0.1:8000: POST /rpc, GET /healthz
python -m engine.worker     # screen refresher, stop-loss / exit monitor, auto-trade scheduler
npm --prefix frontend install && npm --prefix frontend run dev    # http://localhost:5173
```

The API only answers requests. The worker is the only process that runs scheduled work; a second worker waits on standby and takes over within a minute if the first dies. `GET /healthz` reports wh[...]

The first screen takes about a minute (50 option chains plus the NSE SPAN file). After that it refreshes in the background every 10 minutes in market hours and hourly outside them.

## Tests

```bash
npm --prefix frontend run lint
npm --prefix frontend test     # UI tests in happy-dom: frontend/tests/*.test.jsx
make test                      # backend integration tests in throwaway Postgres + Redis containers
```

Backend tests (`tests/test_*.py`) run against a real database and Redis with NSE market data stubbed (`tests/support.py`). `tests/run.py` gives each file a fresh, migrated database. Without Docker[...]

```bash
DB_HOST=localhost OWNER_DB_PASSWORD=... DB_APP_PASSWORD=... REDIS_URL=redis://localhost:6379/0 python tests/run.py [test_pivots.py]
```

`LIVE_DATA=1` adds a check against real yfinance data. Every push and pull request runs all of this in GitHub Actions (see [Deploy](#deploy)).

## Features

| Page | What it does |
|---|---|
| **Screener** (`/`) | Every Nifty 50 stock scored against the rules below. Actionable setups first, with POP, ROI, margin and suggested lots |
| **Stock detail** (`/stock/SYMBOL`) | Payoff chart, S/R zones, open interest by strike, strategy lab, order ticket |
| **Portfolio** (`/portfolio`) | Open positions by stock and expiry: live P&L, margin, Greeks, stop-loss mode per leg, payoff, price & pivot chart, exit leg / exit all, open limit orders |
| **Virtual account** (`/virtual`) | Order history, closed trades, auto-trade settings and runs, account reset |
| **Broker** (`/broker`) | Connect a real broker (Zerodha; others are previews). Admin-only for now — everyone else sees the same page as a preview |
| **Real account** (`/broker/account`) | Real (or, until connected, approximate virtual-derived) available margin, cash, collateral, span, exposure and open positions |
| **Admin** (`/admin`, admin only) | Approve, reject or disable users, issue temporary passwords, sign-in activity log with client IPs |

Accounts: every page needs a sign-in. New users request access on `/register` and start as pending with ₹10,00,000 of virtual capital.

## Rules (edit in `engine/config.py`)

| Rule | Value |
|---|---|
| Universe | Nifty 50, read live from NSE's constituent CSV (falls back to a saved list if unreachable) |
| PCR (OI) | 0.4 – 0.7 |
| Expiry | First expiry with 30+ DTE |
| Strike | Highest-OI OTM strike with \|delta\| < 0.15 (Black-Scholes from NSE IV) |
| Max Pain | Shown as distance from the strike, used for confirmation only |
| S/R | 6-month daily swings (5-candle fractal), zones ±1.5%, 2+ touches. A strike inside a zone drops that leg |
| Stop loss | None for the first 15 days, then buy back at the original premium collected |
| Time exit | Every leg closes once fewer than 7 days remain (stock options settle by physical delivery) |
| Profit exit | The whole group closes once 90% of the premium collected has decayed |
| Sentiment | +1/-1 for price vs 20 & 50 DMA trend, +1/-1 for today's PE vs CE OI change. Score ≥1 Bullish, ≤-1 Bearish, else Neutral. Display only; it doesn't filter trades, but flags single-[...]

## Trade metrics

| Metric | How it's calculated |
|---|---|
| Breakeven | Strangle: PE strike − total credit and CE strike + total credit. Single leg: strike ∓ its premium |
| POP | Probability price at expiry ends between the breakevens (lognormal, NSE IV per side) |
| Max profit probability | Probability price at expiry ends between the short strikes, so all premium is kept |
| Touch probability | About 2× the chance of expiring past the strike: odds price touches it before expiry |
| Lot size | NSE `fo_mktlots.csv`, column for the expiry month |
| SPAN margin | Worst of the 16 SPAN scenarios for the combined short position, from NSE's latest SPAN 4.0 risk file (`nsccl.YYYYMMDD.iN.zip`). Strangles get the real offset between legs |
| Exposure margin | Per short leg: higher of 3.5% of notional or 1.5 × 6-month daily volatility |
| Lots suggested | floor(min(account value × max % per trade, free funds) ÷ margin per lot) |

## Strategy lab (stock detail page)

| Control / figure | How it works |
|---|---|
| Strike sliders | Step through the live NSE strikes on the out-of-the-money side. Warns when a strike breaks the delta < 0.15 rule or sits in an S/R zone |
| Days slider | Values each leg on any day to expiry with Black-Scholes at today's IV, calibrated so day 0 equals the market premium; spot held constant |
| Intrinsic / time value | Intrinsic = how far the option is in the money; time value = premium − intrinsic (all of it for OTM strikes) |
| Risk : reward | Reward = premium collected. Risk = expiry loss after a 2σ move against you (a naked short has no fixed max loss) |
| 1σ / 2σ | Expected move by expiry, spot × e^(±nσ√t) from the legs' IV; shaded on both payoff charts. Each strike shows how many σ it sits from spot |
| Margin | Real SPAN + exposure for the chosen strikes (`calc_margin` RPC) |

## Portfolio & virtual account

Paper trading with live NSE prices, stored per user in Postgres. Starts at ₹10 lakh; reset any time from **Virtual account** with a custom amount (₹10,000 to ₹1,000 crore).

| Feature | Behaviour |
|---|---|
| Orders | Limit orders only, as on a live account. A limit the market already meets fills at once at the bid (sells) or ask (buys). Any other limit waits as an open order and expires at the sess[...]
| Repeat orders | If an earlier order on the same stock and expiry hasn't filled yet, the ticket warns and asks before placing another. The server enforces this too, so a double click or a second[...]
| Margin | SPAN (long and short legs netted) + exposure on short legs, per stock/expiry. Checked again under a lock at booking, so two orders can't both spend the same free funds. Open orders hol[...]
| Positions | Netted per contract; opposite trades reduce or close the position and book realised P&L |
| Stop loss | Per short leg, three modes: **Auto exit** (the whole group closes once a leg's ask reaches the premium collected, from day 15), **Alert only** (flags the leg for you to act), **Off*[...]
| Exits | Exit a leg or the whole group. With the market closed, the exit waits as an open order; pressing Exit again doesn't queue a second one |
| Monitor | The worker checks stop losses, time exits and profit targets every minute in market hours (09:15–15:30 IST), fills open orders once the market reaches them, and settles expired cont[...]
| Auto-trade | Optional, per user: once a day at a set time it sells the top-ranked actionable setups within a per-trade cap and a free-funds reserve. It skips any stock and expiry that already h[...]
| Wallet | The top bar shows free funds, refreshed every 30 s and after every order; set the max margin % per trade there |

## Price & pivot levels

On the Portfolio page, **Price & pivot levels** on a position opens a 6-month daily price chart with classic floor pivots and the position's short strikes. Daily, weekly or monthly pivots come fr[...]

| Level | Formula (H, L, C of the period) |
|---|---|
| P | (H + L + C) / 3 |
| R1 / S1 | 2P − L / 2P − H |
| R2 / S2 | P + (H − L) / P − (H − L) |
| R3 / S3 | H + 2(P − L) / L − 2(H − P) |
| R4 / S4 | 3P + H − 3L / 3P − 3H + L |

## Layout

- `server.py` — JSON-RPC 2.0 endpoint `POST /rpc`, auth, CSRF (Origin) check, error handling; `rpc_guard.py` validates every call's params against the handler's signature
- `engine/` — `data_fetch.py` (NSE option chain v3, lot sizes, yfinance), `span.py` (SPAN risk files), `filters.py` / `risk_rules.py` / `greeks_sr.py` (rules, Black-Scholes, S/R), `batch.py` (b[...]
- `migrations/` — Alembic; every user-owned table has row-level security
- `frontend/` — React (Vite): pages in `src/pages/`, charts in `src/components/` (Recharts). Responsive from 320 px: wide tables become stacked cards below 1024 px
- `tests/`, `frontend/tests/` — backend integration and UI tests
- `deploy/` — Caddy configs, Postgres init, Coolify runbook; `docker-compose.yml` (self-hosted), `docker-compose.coolify.yml`
- `.github/workflows/ci.yml` — CI/CD

## Deploy

**Production (Coolify).** `main` deploys automatically: GitHub Actions runs lint, tests and image builds, then asks Coolify to deploy and smoke-tests the live site. Deploys are held during market[...]

**Self-hosted (Docker Compose).** Six services: `web` (Caddy: HTTPS, security headers, the React build, proxies `/rpc`), `api` (gunicorn), `worker`, `migrate` (runs once per start), `postgres`, `[...]

```bash
python3 scripts/make_secrets.py      # random passwords into ./secrets (git-ignored)
cp .env.example .env                 # set DOMAIN and ADMIN_EMAIL
docker compose up -d --build
docker compose exec api python scripts/set_admin.py you@example.com
```

Point the domain's DNS A record at the server first: Caddy fetches the certificate on start. To try it on a laptop, use `DOMAIN=localhost`, `HTTPS_PORT=8443`, `PUBLIC_URL=https://localhost:8443` [...]

## Known limits

- NSE's option-chain API is unofficial. It can change or block requests without notice (it already moved from `option-chain-equities` to `option-chain-v3`). The server throttles its own NSE calls[...]
- Delta is computed locally with a fixed 6.5% risk-free rate and no dividend adjustment.
- Exposure margin is charged on each leg of a strangle. Some brokers charge it differently, so compare with your broker's margin calculator.
- Probabilities assume a lognormal price at expiry using today's IV. They are model estimates, not guarantees, and they ignore gap risk.
- Market hours are fixed at 09:15–15:30 IST on weekdays; NSE holidays are not in the calendar.
- Real broker execution (Zerodha) is admin-only for now, manual-confirm-only for entries (from day 15 a filled real leg gets a Kite alert-triggered buy-back at the premium collected; see the Real account page), and has no encryption-key-rotation tooling yet. Everyone else, and every automated flow, stays on the virtual account[...]
- This is primarily a paper-trading and research tool, not investment advice.

## Contributing, security, licence

- [CONTRIBUTING.md](CONTRIBUTING.md): setup, conventions, tests and the pull request / deploy flow.
- [SECURITY.md](SECURITY.md): how to report a vulnerability privately.
- [LICENSE](LICENSE): proprietary, all rights reserved. Access to this repository does not grant a licence to use, copy or deploy the code.
