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

Live: https://theta.connectbiomedical.com (sign-in required; new users confirm their email and can start at once, unless the owner turns automatic approval off).

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
- **Zerodha Kite API** — Real broker execution (phase 1; roles with *live trading*, owner-only by default)

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
- [Learn](#learn-lessons-and-quizzes)
- [Levels and XP](#levels-and-xp)
- [Roles & features](#roles--features)
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
python -m pip install --require-hashes -r requirements.txt
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
| **Market calendar** (`/calendar`) | NSE trading holidays and Nifty 50 corporate events (results, ex-dividend, splits, bonuses, AGMs, buybacks), grouped by the expiry cycle each falls before, with a summary of what lands before the next expiry and a "Held" tag on stocks you have open positions in. Filter by results & dividends / corporate actions, or search a symbol. Screener rows show the next event and its date on the symbol line when it falls inside that row's expiry cycle: results on 9 Oct badge the Oct row only, not Nov or Dec (the stock page still lists every event up to its expiry). AGMs and plain board meetings are left to the calendar and stock page. Hover or tap the badge for the full list. Results and ex-dividend dates are highlighted as risky. Refreshed once a day by the worker |
| **Portfolio** (`/portfolio`) | Open positions by stock and expiry: live P&L, margin, Greeks, stop-loss mode per leg, payoff, price & pivot chart, exit leg / exit all, open limit orders |
| **Virtual account** (`/virtual`) | Order history, closed trades, auto-trade settings and runs, account reset |
| **Broker** (`/broker`) | Connect a real broker (Zerodha; others are previews). Only roles with *live trading* — everyone else sees the same page as a preview |
| **Real account** (`/broker/account`) | Real (or, until connected, approximate virtual-derived) available margin, cash, collateral, span, exposure and open positions |
| **Admin** (`/admin`, roles with *manage users*) | Approve, reject or disable users, issue temporary passwords, change roles, sign-in activity log with client IPs. The owner also gets **Roles & features** |

Accounts: every page needs a sign-in, except the lessons at `/learn`. New users sign up on `/register` and confirm their email with a 6-digit code. With **Approve new accounts automatically** on (the default, Admin → Roles & features, owner only), that's enough: they're signed in at once with ₹10,00,000 of virtual capital, as the *User* role, and the first screen asks for a public nickname and whether to appear on the leaderboard. With it off, confirmed accounts wait as pending until approved on the Admin page. Duplicate-account flags (same browser or network) still show there either way.

## Learn (lessons and quizzes)

Short lessons for option sellers, from what an option is to managing a short strangle, at `/learn`. Reading is public (no account needed, so lessons can be shared); the quiz at the end of each lesson needs a free account.

- Content is plain files in `content/lessons/`: `NN-slug.md` for the text (headings, lists, **bold** and *italic*, `> ` comparison boxes, and `::visual name` for a diagram from `frontend/src/components/LessonVisuals.jsx`) and `NN-slug.json` for the title, level, summary and quiz. Changes go through pull requests like code.
- Quizzes are marked on the server, and answers never reach the browser. 80% passes. After a failed attempt the quiz locks for 24 hours, and the right answers are shown only on a pass.
- A pass is recorded once per lesson (`lesson_progress`). The learning path's XP ledger (#122) will award lesson XP from it.
- Every lesson carries an "educational, not investment advice" note.

## Levels and XP

Users climb Level 1 (Learner) to Level 10 (Theta Master) by paper-trading with discipline (#120). Engine: `engine/progress.py`; thresholds in `engine/config.py`.

- **Trade log:** every closed virtual leg is copied to `trade_results` when it closes (a strangle is two legs). A virtual-account reset deletes orders and positions but not this log or any XP.
- **XP** (append-only `xp_ledger`, each event scores once):

  | Event | XP |
  |---|---|
  | Short leg closed with its stop-loss on and sold below 0.15 delta | +20 |
  | Short leg closed with the stop-loss off | −30 |
  | Short leg sold at 0.15 delta or more | −20 |
  | Profitable short leg | +5, at most +100 a month |
  | Lesson quiz passed (first time) | +10 |

  Legs opened and closed within 5 minutes score nothing. Delta is saved when a sell fills at once; a limit order that fills later has no saved delta and earns no delta-based XP either way.
- **Unlocks (#123):** a user's features are their role's toggles, plus what their level unlocks (`LEVEL_FEATURES` in `engine/config.py`: option builder at 2, leaderboard at 4, saved strategies and alerts at 5, hedges at 6, each starting to work once that feature ships), then the owner's per-user overrides (Admin → Roles & features → Per-user overrides: Default / Grant / Deny). Levels never grant real trading or admin powers.
- **Level 6 → Beta:** a *User* who reaches Level 6 becomes *Beta* automatically. This happens once and is logged. If the owner moves them back to User, that sticks. Nothing is ever promoted automatically beyond Beta.
- **Levelling up** from level n needs all of: total XP ≥ 100 × n², the minimum days at the level, and the level's gate, measured on legs closed since reaching the level or the last reset, whichever is later. One level at a time, checked nightly and whenever the user opens their progress. Gates for Levels 6+ need data the app doesn't record yet, so they show "Not available yet".
- **My progress page (`/progress`, #126):** level, an XP bar towards the next level, that level's checks with live values (straight from the gate, so the page always matches), days left at the level, and the XP history. A level reached since the browser last saw one puts a dot on the Progress tab and shows a one-time level-up screen.
- **Share cards (#126):** from My progress (or the level-up screen) a user can share their current level or a finished course (every lesson of one level). The card is a frozen snapshot at a random link, `/c/<slug>`, served by the API rather than the single-page app so WhatsApp and X can read its preview tags, with a 1200×630 PNG at `/c/<slug>.png` (Pillow). It shows the nickname, the achievement, "Paper trading · educational", the site's address, and the paper-trading % return only if the user ticks it. It never shows an email or a rupee amount. The page links to sign-up. Links use `PUBLIC_URL`.
- **Invite links (#126):** My progress shows each user's invite link (`/register?ref=<code>`, code made on first use) and how many people confirmed an account through it. A share card's sign-up button carries the sharer's code. The code is kept for the browser session, so it survives a detour to sign-in, and an unknown code is ignored, never blocking a sign-up. Admin → Users shows "Invited by" and "Invited N". It's a metric only for now: nothing is rewarded.

## Roles & features

Four roles, highest first. There is exactly one **Owner** (the database refuses a second), and
nobody can be made Owner; the highest role anyone can be given is Sub-admin.

| Role | Who | Can change roles |
|---|---|---|
| **Owner** | The account `scripts/set_admin.py` manages | Anyone else, to Sub-admin, Beta or User |
| **Sub-admin** | Helpers the owner picks | With *manage roles*: Beta ↔ User only |
| **Beta** | Early-access users | — |
| **User** | Everyone else (the default) | — |

**Feature toggles.** On Admin → *Roles & features* the owner switches each feature on or off per
role (Sub-admin, Beta, User). The owner always has everything, and only the owner sees this tab.
A change applies on that person's next click; their menu updates when they reload.

| Feature | What it unlocks | Starts on for |
|---|---|---|
| manage users | The Admin page: approve, disable, reset passwords, activity log | Sub-admin |
| manage roles | Moving accounts between Beta and User | Sub-admin |
| live trading | Connecting Zerodha and placing real orders (manual confirm only) | nobody but the owner |
| autotrade | Auto-trade on the virtual account (the scheduler skips roles without it) | everyone |
| market calendar | The Market Calendar page | everyone |

Rules no toggle can change: a manager only acts on accounts ranked below their own (a Sub-admin
never touches the Owner or another Sub-admin); only the Owner grants or removes Sub-admin; and
auto-trade never places real orders. Every role change and toggle is in the activity log. The
server enforces all of it (`REQUIRES` in `server.py`, `engine/permissions.py`); the UI only hides
what would be refused.

Upgrading from before roles: the first admin becomes the Owner and any other admins become
Sub-admins, who lose real trading until the owner turns *live trading* on for Sub-admin.

## Rules (edit in `engine/config.py`)

| Rule | Value |
|---|---|
| Universe | Nifty 50, read live from NSE's constituent CSV (falls back to a saved list if unreachable) |
| PCR (OI) | 0.4 – 0.7 |
| Expiry | Every monthly expiry 20–90 days out is screened (at most 4 per stock), one Screener row each, month by month (every stock's nearest cycle first, then the next). A skipped cycle is refetched hourly, actionable and failed ones every run; Refresh refetches all. The Expiry slider opens at 20 days; the strategy enters at 30+ DTE, so auto-trade only opens cycles 30+ days out |
| Strike | Highest-OI OTM strike with \|delta\| < 0.15 (Black-Scholes from NSE IV) that is tradable: OI ≥ 500, bid-ask spread ≤ 10% of mid, and last trade within 15% of the book. An illiquid strike is passed over for the next one by OI |
| Premium | What a sell books: the bid, not the last traded price (which on a thin strike can be hours old). Outside market hours, with no bid/ask, the last trade stands in until the next in-session screen |
| Max Pain | Shown as distance from the strike, used for confirmation only |
| S/R | 6-month daily swings (5-candle fractal), zones ±1.5%, 2+ touches. A strike inside a zone drops that leg |
| Stop loss | None for the first 15 days, then buy back at the original premium collected. It fires when the bid/ask **mid** reaches the stop (the ask alone sits above a fill at the bid); the exit is a limit at the ask |
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
| Unbooked P&L | Each leg marked at the bid/ask mid (after the close: the last in-session mid). "If closed now" beside it buys shorts back at the ask, so the spread is visible, not hidden. A leg whose LTP sits >15% outside the book is flagged as stale |
| Order ticket | Default limit: the bid on a tight book, the mid when the spread is over 3% (it may rest instead of filling). An illiquid strike needs "Place anyway"; auto-trade skips it |
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
| Auto-trade | Optional, per user: once a day at a set time it sells the top-ranked actionable setups (one per stock: its best-scoring expiry cycle 30+ days out) within a per-trade cap and a free-funds reserve. It skips any stock and expiry that already h[...]
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

## Branding (name, logo, favicon)

The app's name and logo are not in the code (issue #133). The owner sets them under **Admin → Features & settings → Branding**: the name (1–40 characters) and a logo (PNG or WebP, up to 1 MB). No other role can change them, whatever features it has. The server re-encodes every upload to PNG and makes the favicon (32 px) and home-screen icon (180 px) from it; SVG and other formats are refused. Until a logo is uploaded, the built-in dial mark and `/favicon.svg` are used. The name shows on every page and tab title, in emails, the default sender, share cards and Zerodha alert names. `APP_NAME` sets the name on a fresh install; the owner's setting overrides it. The domain stays the `PUBLIC_URL`/`DOMAIN` env vars, since a wrong value would lock everyone out. `scripts/check_brand.py` (run in CI) fails if the name is hard-coded anywhere else: read it from `engine/brand.py` or `useBrand()` in `frontend/src/brand.jsx`.

## Known limits

- NSE's option-chain API is unofficial. It can change or block requests without notice (it already moved from `option-chain-equities` to `option-chain-v3`). The server throttles its own NSE calls[...]
- Delta is computed locally with a fixed 6.5% risk-free rate and no dividend adjustment.
- Exposure margin is charged on each leg of a strangle. Some brokers charge it differently, so compare with your broker's margin calculator.
- Probabilities assume a lognormal price at expiry using today's IV. They are model estimates, not guarantees, and they ignore gap risk.
- Market hours are fixed at 09:15–15:30 IST on weekdays. Scheduled screens skip NSE holidays once the worker has fetched the holiday list, but the market clock and SL monitor don't yet. Event badges are informational: auto-trade does not skip stocks with results before expiry.
- Real broker execution (Zerodha) is limited to roles with *live trading* (only the owner until they switch it on for a role), manual-confirm-only for entries (from day 15 a filled real leg gets a Kite alert-triggered buy-back at the premium collected; see the Real account page), and has no encryption-key-rotation tooling yet. Everyone else, and every automated flow, stays on the virtual account[...]
- This is primarily a paper-trading and research tool, not investment advice.

## Contributing, security, licence

- [CONTRIBUTING.md](CONTRIBUTING.md): setup, conventions, tests and the pull request / deploy flow.
- [SECURITY.md](SECURITY.md): how to report a vulnerability privately.
- [LICENSE](LICENSE): proprietary, all rights reserved. Access to this repository does not grant a licence to use, copy or deploy the code.
