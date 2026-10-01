# Phase 1: Real Broker Integration — Zerodha (Kite Connect)

## Context

Theta Desk is currently 100% virtual/paper trading (per `CLAUDE.md` and `SECURITY.md`, which explicitly states "no broker connection and no real money" as out of scope). The user wants to start sending real signals from this app to a real broker account and execute real-money trades, reconciling real fills/positions/margin back into the UI — implemented one broker at a time, with only one broker connectable per user at once.

This plan covers **Phase 1 only**: end-to-end integration with **Zerodha (Kite Connect)**, manual-confirm-only order placement (no autonomous real-money auto-trade yet — auto-trade stays virtual), gated to **admins only** for the initial soft launch. Later phases repeat the same adapter pattern for Upstox, Angel One, etc. (already previewed as "Coming soon" on the existing `/broker` page from a prior change).

This is a fundamental scope change for the app's threat model (real financial risk + custody of broker credentials), so `SECURITY.md` must be updated alongside the code.

## Key resolved design decisions

1. **One operator-level Kite Connect app, many per-user logins.** The Theta Desk operator registers a single Kite Connect app (`KITE_API_KEY`/`KITE_API_SECRET`, delivered like DB/Redis passwords via `settings.secret()`). Each user logs into **their own** Zerodha account through that shared app's OAuth redirect, producing their own per-user `access_token`. Only the per-user `access_token` (and Zerodha's own `public_token`/`broker_user_id`) needs row-level encryption — not `api_key`/`api_secret`.
2. **Options-selling only, so every leg is SELL, limit orders by default.** This matches the existing virtual engine (short legs only) — no new "order type" decision needed, `order_type` defaults to `LIMIT` for every leg, matching `virtual.py`'s existing limit-order-only model.
3. **Pre-flight balance/margin check before sending anything to the broker.** Before placing any leg, call `broker_get_margins` (real Zerodha funds) and compare against the strategy's total required margin — reject the whole order upfront if insufficient, exactly mirroring `virtual.py`'s `_margin_impact`/`_insufficient` pattern but against real broker margin instead of the simulated SPAN calc.
4. **Partial-leg-failure handling**: since every leg is a real-money SELL order with no atomic multi-leg API in Kite Connect, if a leg fails after an earlier leg already placed successfully, **stop immediately — do not place further legs, and do not attempt auto square-off**. Surface a clear "Leg N failed; leg(s) already placed are live in your Zerodha account — manage manually" error. No automatic rollback (a rollback order is itself a new risky real-money trade).
5. **Admin-only for initial soft launch.** `broker_connect_url`/`broker_exchange_token` are gated to `ctx.user["role"] == "admin"` at first; lift once proven stable with a handful of real trades.
   *Update (issues #46, #9):* superseded by the role-feature gate. Connecting, previewing and placing real orders need the `live_trading` feature (`REQUIRES` in `server.py`); only the owner has it until the owner switches it on for a role. The two connect methods now live in `USER_METHODS`.
6. **Single-broker-per-user wording**: *"You're already connected to another broker. Disconnect it first to connect this one."*

## Data model

New migration `migrations/versions/0004_broker_connections.py` (chained after `0003_limit_orders`), following the exact conventions in `migrations/versions/0001_initial.py` / `0003_limit_orders.py`:

**`broker_connections`** — one row per user's current/past broker connection:
- `id BIGSERIAL PRIMARY KEY`
- `user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE`
- `broker TEXT NOT NULL CHECK (broker IN ('zerodha'))` — extensible; future migrations add more values
- `status TEXT NOT NULL CHECK (status IN ('active','disconnected','expired')) DEFAULT 'active'`
- `broker_user_id TEXT` — Zerodha's own user id, plaintext (support/audit display only, not secret)
- `access_token_enc BYTEA NOT NULL`, `public_token_enc BYTEA` — Fernet ciphertext
- `connected_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `token_expires_at TIMESTAMPTZ NOT NULL`, `disconnected_at TIMESTAMPTZ`, `last_synced_at TIMESTAMPTZ`

```sql
CREATE UNIQUE INDEX broker_connections_one_active ON broker_connections (user_id) WHERE status = 'active';
```
This is the DB-level single-broker-per-user guarantee (mirrors `positions_one_open`'s partial-unique-index pattern). Apply the standard RLS block (`ENABLE`/`FORCE ROW LEVEL SECURITY` + `<t>_owner` policy on `user_id = NULLIF(current_setting('app.user_id', true), '')::bigint`) and the guarded `theta_app` grants block, exactly as in `0003_limit_orders.py:44-56`.

**`broker_orders`** — real order/fill bookkeeping, mirrors `orders`/`positions` shape:
- `id BIGSERIAL PRIMARY KEY`, `user_id`, `broker TEXT`, `kite_order_id TEXT`, `symbol`, `expiry`, `strike`, `side`, `qty`, `limit_price`, `leg_index INT`, `status TEXT CHECK (status IN ('pending','open','complete','rejected','cancelled'))`, timestamps. Same RLS/grants pattern.

## Encryption

New `engine/broker_crypto.py`:
- Lazily builds `cryptography.fernet.Fernet` from `settings.secret("BROKER_ENC_KEY")` (new `BROKER_ENC_KEY_FILE` env var, delivered exactly like `DB_PASSWORD_FILE` today via `engine/settings.py:secret()`), cached module-level like `db.py`'s engine singleton.
- `encrypt(plaintext: str) -> bytes` / `decrypt(ciphertext: bytes) -> str`.
- Add key generation to `scripts/make_secrets.py` (self-hosted) and document the Coolify env var in `deploy/COOLIFY.md`.
- Never log plaintext or ciphertext tokens anywhere (add explicit note to `CONTRIBUTING.md`).
- Key rotation: out of scope for phase 1; documented as a known gap.

## Broker adapter abstraction

New package `engine/brokers/`, designed so future brokers (phase 2+) only add one file:
- `engine/brokers/base.py` — interface: `login_url()`, `exchange_request_token(request_token)`, `place_order(session, symbol, exchange, side, qty, order_type, product, price)`, `get_order_status(session, order_id)`, `cancel_order(session, order_id)`, `get_positions(session)`, `get_margins(session)`.
- `engine/brokers/zerodha.py` — implements the interface via the official `pykiteconnect` SDK (`kiteconnect` PyPI package), keyed by operator `KITE_API_KEY`/`KITE_API_SECRET` from `settings.secret()`. Wraps Kite SDK exceptions into `ValueError`/`TimeoutError` per `server.py`'s error-handling convention (raised errors reach the client; anything else is logged with a ref id).
- `engine/brokers/registry.py` — `{ "zerodha": ZerodhaAdapter() }`, used by the RPC layer instead of hardcoding.
- Add `pykiteconnect`/`cryptography` to backend dependencies.

## RPC methods (`server.py`, `USER_METHODS` table, `broker_*` naming to mirror `va_*`)

- `broker_connect_url(user_id)` — **admin-only** (checked same way `ADMIN_METHODS` are gated, or an explicit role check inside the handler since this is a `USER_METHODS`-shaped call); generates a one-time CSRF `state`, stores it server-side keyed to `user_id` (~10min TTL), and returns `{url, state}`. The frontend stashes `state` in `sessionStorage` before redirecting to Kite, since Kite's own redirect never echoes custom query params back.
- `broker_exchange_token(user_id, request_token: str, state: str)` — admin-only; requires the caller to echo back the `state` from `broker_connect_url` (read from `sessionStorage` by the callback page, not from the URL) and verifies it against the stored value for that `user_id`, one-time use, rejecting on mismatch/expiry — this closes a login-CSRF hole where an attacker could otherwise get their own `request_token` accepted into an admin's account by luring the admin's browser to the callback URL. Then pre-checks no active connection exists (raises the friendly single-broker error before calling Kite), exchanges for `access_token` via Kite's checksum flow, encrypts, inserts into `broker_connections` inside `db.tx(user_id)`, enforces the unique-active-connection constraint (catch + friendly error), `audit(action="broker_connected", ...)`.
- `broker_status(user_id)` — returns `{broker, status, connected_at, token_expires_at, broker_user_id}`, never secrets.
- `broker_disconnect(user_id)` — sets `status='disconnected'`, calls Kite's `invalidate_access_token()` best-effort (verify this call still exists in the current `pykiteconnect` API at implementation time), clears `broker_snap:{user_id}` Redis key, `audit(action="broker_disconnected", ...)`.
- `broker_get_positions(user_id)` / `broker_get_margins(user_id)` — read from the worker-populated `broker_snap:{user_id}` Redis cache (never a live Kite call from the API process, to respect Kite's GET rate limit).
- `broker_preview_order(user_id, symbol, expiry, legs)` — prices legs from the existing live NSE quote source (`data_fetch.py`), checks total required margin against real `broker_get_margins` data (resolved decision #3 above), does **not** call Kite; returns a preview payload plus a one-time `confirm_token` (`secrets.token_urlsafe(24)`, stored in Redis `broker_confirm:{token}` with the exact order params, ~60s TTL).
- `broker_place_order(user_id, confirm_token: str)` — the only method that calls Kite. Validates the token (one-time use, belongs to `user_id`), re-checks connection is `active`/not expired, places every leg as a `SELL`+`LIMIT` order sequentially via the adapter; on any leg failure after the first success, **stops immediately** (resolved decision #4), writes a `broker_orders` row per leg placed, `audit(action="broker_order_placed"/"broker_order_failed", ...)` per leg.

`rpc_guard.py` needs no special-casing for these — accurate type annotations (`str`, `str | None`) are enough for its signature-based validation.

## Worker integration

In `engine/worker.py`'s `main()`, alongside `virtual.start_monitor()`/`autotrade.start_scheduler(...)`, add `brokers.start_poller()` (new `engine/brokers/poller.py`):
- Runs inside the existing single-leader `cache.Lock("worker", ...)` — no new lock needed.
- For each `broker_connections.status='active'` row with `token_expires_at > now()`: fetches positions/margins/open-order-status via the adapter, writes to `broker_snap:{user_id}` (mirrors `snap:positions:{user_id}` shape/TTL), updates `broker_orders.status` and `broker_connections.last_synced_at`.
- For rows where `token_expires_at <= now()`: flips `status` to `'expired'` (no Kite call possible/needed) so `broker_status` reports it and the UI prompts reconnect.
- Poll every 30–60s per active connection; this is read-only reconciliation only — it must never place orders (the only order-placing path is the RPC-triggered `broker_place_order`).

## Frontend

- `frontend/src/pages/Broker.jsx` (currently static "Coming soon" grid from the prior phase) — make the Zerodha `BrokerCard` interactive for admins only: Connect → `broker_connect_url` → Kite login → redirect-handler reads `request_token` from the query string → `broker_exchange_token`. Other cards stay disabled/"Coming soon."
- `frontend/src/components/BrokerCard.jsx` — add connected/expired/disconnected states, a "Reconnect" CTA when expired, and the resolved single-broker-error message on a blocked connect attempt.
- New `frontend/src/pages/BrokerAccount.jsx` mirroring `VirtualAccount.jsx`'s stat-tile/orders-table patterns, but sourced from `broker_status`/`broker_get_positions`/`broker_get_margins` — a "Real account" view distinct from the virtual one.
- New `frontend/src/components/RealOrderConfirmDialog.jsx` — visually distinct (red/amber) from the existing virtual confirm dialog, restates every leg's estimated price/qty/margin, requires an explicit confirm click, no "don't ask again."
- Reuse the existing options-leg-picker UI already used for virtual `va_place_order` — only the destination (virtual vs. real account) and the confirm dialog are new.

## Security updates

- `SECURITY.md`: replace the "no broker connection and no real money" out-of-scope line with the new in-scope description (Zerodha only, admin-gated, manual-confirm-only, encrypted-at-rest access tokens via Fernet/`BROKER_ENC_KEY`), and document the token-revocation limitation.
- `CONTRIBUTING.md`: add the broker-adapter convention and "broker order placement must never be retried automatically without a fresh user confirmation."
- New audit events via existing `audit()`: `broker_connected`, `broker_disconnected`, `broker_order_placed`, `broker_order_failed`.
- Never log `access_token`/`public_token`/raw Kite response bodies — log a ref id only, same discipline `server.py` already applies to unexpected errors.

## Testing plan

- Develop/test against Kite Connect's sandbox environment before any real-money call.
- `tests/test_broker_connections.py` — partial unique index enforcement, RLS isolation between users, `broker_crypto` encrypt/decrypt round-trip.
- `tests/test_broker_rpc.py` — all `broker_*` RPCs against a `FakeBrokerAdapter` stub (mirrors `tests/support.py`'s existing NSE-data stub pattern) injected via the registry, including: single-broker-conflict error path, confirm-token one-time-use/expiry, margin-insufficient rejection, and the stop-on-first-leg-failure behavior.
- `frontend/tests/broker.test.jsx` — `BrokerCard` connected/expired/disconnected rendering, `RealOrderConfirmDialog` required-click behavior.
- Manual pre-go-live checklist (not automated): one real sandbox login end-to-end; one real-money trade of the smallest possible size, confirming it matches in Kite's own console, `broker_orders`/`broker_snap` reflect it correctly, and disconnect stops the poller from hitting Kite for that user.

## Rollout / ops

- New env vars: `KITE_API_KEY`, `KITE_API_SECRET_FILE`, `BROKER_ENC_KEY_FILE`, `KITE_REDIRECT_URL` (must exactly match the Kite Connect developer console registration, analogous to how `PUBLIC_URL` must match the Origin check today). Document in `deploy/COOLIFY.md`, add to `scripts/make_secrets.py` for self-hosted.
- Migration `0004_broker_connections.py` runs via the existing `migrate` service before `api`/`worker` start — purely additive, no special ordering.
- Admin-only gating (decision #5) is the initial feature flag; no separate flag infrastructure needed since it's a role check.

## Verification

1. `make test` (backend) passes including the two new `test_broker_*.py` files, run against throwaway Postgres/Redis containers per the existing `tests/run.py` convention.
2. `npm --prefix frontend test` passes including `broker.test.jsx`.
3. `npm --prefix frontend run build && npm --prefix frontend run lint` clean.
4. Manual: run the full connect → preview → confirm → place → poller-reconciles cycle against Kite's sandbox with a fake admin account before touching real money.
5. Only after sandbox verification: one minimum-size real trade, manually cross-checked against Zerodha's own console, before considering phase 1 done.

## Deferred to later phases (not phase 1)

- Any second broker (Upstox, Angel One, etc.) — same adapter pattern, new file in `engine/brokers/`.
- Autonomous real-money auto-trade (today's `autotrade.py` stays virtual-only).
- Encryption key rotation tooling.
- Wider (non-admin) rollout, once phase 1 is proven stable.

## Status update (2026-09-27)

Shipped as planned above, plus a few things this plan didn't anticipate:

- **`broker_get_margins`/`broker_snap` gained `span`, `exposure`, `collateral_liquid_used` and
  `collateral_equity_used`** (Kite's `utilised.span`/`utilised.exposure`/`utilised.liquid_collateral`/
  `utilised.stock_collateral`), not just cash/collateral/used totals.
- **`broker_preview_order`'s margin check is no longer cash-only.** It gates on Kite's own
  `margins().net` (cash + pay-in + collateral − utilised), the figure Kite's RMS checks orders
  against. An earlier version rebuilt this from `available.collateral` minus
  `utilised.liquid_collateral`/`stock_collateral` with a 50% cap; that read collateral as zero and
  blocked orders that had enough margin (issue #40), so it was replaced.
- **Broker-side stop loss (issue #43).** Entries stay plain SELL LIMIT orders. Each poller pass
  (`engine.broker.sync_stop_alerts`) learns fills from `order_history`, and once a filled leg is
  `SL_GRACE_DAYS` (15) old it installs one Kite **ATO ("Alert Triggers Order") alert**: when the
  leg's LTP reaches the stop (the fill price, i.e. the premium collected) Kite itself places a BUY
  LIMIT (`BROKER_SL_LIMIT_BUFFER_PCT` above the stop, NRML) that closes it. No order placed earlier
  is ever edited. Migration `0005` adds the fill and alert columns to `broker_orders`. The poller
  follows the alert (`triggered`/`disabled`/`deleted`) and deletes it if the leg was already closed
  at the broker, so it can't open a long; a leg already closed on day 15 is `skipped`. A failed
  install is retried at most hourly (`BROKER_SL_RETRY_SECONDS`). This is the one broker write the
  worker makes: it installs/removes that alert, never a regular order. New RPC
  `broker_stop_alerts` feeds the "Stop losses at your broker" table on the Real account page.
  Adapters declare `supports_stop_alerts` (Zerodha: true); for a broker without a broker-held
  trigger order the leg is marked `skipped` ("Not available at <broker>: manage the stop
  yourself") rather than retried. Needs the user's Kite session to be active that day (tokens expire daily), so the alert goes in
  on the first day on/after day 15 that the user has logged in.
- **New RPC `broker_account_summary(user_id)`** (`USER_METHODS`), not in the original plan. It's
  the single unified shape for every place that shows margin figures for real trading: the real
  account page, the `/broker` connected banner, and the order ticket's real-order helper line.
  When there's no active connection, it returns the *virtual* account's own numbers as a clearly
  flagged approximation (`source: "approx"` vs `"broker"`) instead of an empty/blank state. It also
  returns `connectable: string[]` — which brokers *this* user may connect right now (phase 1:
  `["zerodha"]` for admins, `[]` otherwise) — the backend-owned source of truth the frontend reads
  instead of each component re-deriving `role === 'admin' && broker === 'zerodha'` locally.
- **`_active_connection`/`status`/`_require_active` share one query** (`_latest_connection_row`):
  since a connection row is only ever inserted fresh and only one row per user can be
  `status='active'`, the active row (when one exists) is always the newest row, so there's no need
  for two different query shapes.
- **Frontend**: `frontend/src/pages/BrokerAccount.jsx` mirrors `VirtualAccount.jsx`'s
  statement/equity-bar/ledger layout (via the shared `components/EquityBar.jsx` and
  `components/StatCard.jsx`) rather than a bespoke stat grid. `components/BrokerOnboarding.jsx`
  (the post-login popup, predates this phase) also reads `connectable` the same way.
- **Test file names differ from this plan's original naming**: the actual files are
  `tests/test_broker.py` (not `test_broker_connections.py`/`test_broker_rpc.py`) and
  `frontend/tests/broker-page.test.jsx` / `broker-card-states.test.jsx` / `broker-account.test.jsx`
  (not a single `broker.test.jsx`).
