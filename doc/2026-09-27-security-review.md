# Security and error-handling review (issue #39), 2026-09-27

Scope: everything listed in #39. That covers the JSON-RPC layer (`server.py`, `rpc_guard.py`), auth and sessions (`engine/auth.py`), the database and RLS (`engine/db.py`, `migrations/`), the real-broker path (`engine/broker.py`, `engine/brokers/`), the virtual account and auto-trade, the frontend RPC client and order tickets, the Caddy, Docker and Coolify config, CI, and dependencies. The review was done from the code. Nothing was sent to production or to Zerodha: tests use a fake broker adapter, and no Docker was available on the review machine.

## Threat model

| Asset | Who might go after it | What they'd want |
|---|---|---|
| Real broker access (Zerodha tokens, order placement) | outside attacker, a signed-in non-admin, a bug | place, duplicate or hide real-money orders |
| User accounts and sessions | outside attacker | take over an account, especially the admin's |
| Per-user trading data | another signed-in user | read or change someone else's positions |
| Secrets (DB/Redis passwords, `BROKER_ENC_KEY`, Kite secret, `COOLIFY_TOKEN`) | anyone who can read logs, the repo or CI | pivot to the DB, decrypt tokens, redeploy |
| Availability of the one server IP towards NSE | abusive client | get the IP blocked by NSE |

Attack surface: one `POST /rpc` endpoint (5 permission tables), `GET /healthz`, static files served by Caddy, the Kite OAuth redirect (a frontend route that posts `request_token` back through `/rpc`), and the worker's outbound calls. CI is triggered by pushes and PRs on a private repo.

## Findings

Severity is about impact on this deployment. Items marked **Fixed** are fixed in this PR, each with a regression test.

| # | Severity | Finding | Where | Status |
|---|---|---|---|---|
| 1 | **High** | A real-order confirm token was read and then deleted in two separate steps, so two concurrent `broker_place_order` calls with the same token (a double click, a client retry) could both get the payload and send every leg to Zerodha twice. The OAuth `state` had the same pattern. | `engine/broker.py` `place_order`, `exchange_token` | **Fixed**: `cache.pop_json` (Redis `GETDEL`) redeems once. Test: `test_broker.py` two racing confirms. |
| 2 | **High** | If Zerodha didn't answer while a leg was being placed (timeout, dropped connection, Kite `NetworkException`/`DataException`), the order might have been placed anyway. Instead, a timeout escaped to `server.py`, and a Kite network/data error was recorded as "rejected / No legs were placed". Either way the user was invited to try again, which could double a live order. | `engine/broker.py`, `engine/brokers/zerodha.py` | **Fixed**: the adapter re-raises ambiguous Kite errors. `place_order` records the leg as `pending` ("no clear answer"), audits `broker_order_unknown`, stops, and tells the user to check the Zerodha order book first. Test: `test_broker.py` unknown leg. |
| 3 | Medium | Login limits checked the counter first and counted only failures afterwards. Parallel requests all passed the check, so a burst could try many more than 5 passwords per email+IP (up to the request slots, per window). | `engine/auth.py` `login` | **Fixed**: each attempt is counted before the password is verified. A correct password gives it back. Test: `test_security.py` 12 parallel guesses. |
| 4 | Medium | SQLAlchemy puts bound values into exception messages, and `server.py` logs full tracebacks, so a DB error could write password hashes or encrypted broker tokens to the container logs. | `engine/db.py` | **Fixed**: `hide_parameters=True`. Test: `test_security.py` DB error text. |
| 5 | Low | String params had no length cap beyond the 64 KB body limit. Long values reached argon2, Redis keys and `compare_digest`. A non-ASCII `state` made `compare_digest` raise, which returned a generic 500. | `rpc_guard.py`, `engine/broker.py` | **Fixed**: 1000-char cap in `validate`. The state is compared as bytes. Test: `test_security.py` oversized string. |
| 6 | Medium | Python dependencies are floor-pinned only (`>=`), so each image build can pull different versions. The base images and actions are pinned, but the pip set is not reproducible. | `requirements.txt` | **Fixed** in #63: `requirements.in` lists the direct deps, and `requirements.txt` is the hashed lock (`make lock`), installed with `--require-hashes`. |
| 7 | Low | `kiteconnect` 5.2.2 (the latest) pins `autobahn==19.11.2`, which has 2 advisories (PYSEC-2020-25, CVE-2026-77528). autobahn is only used by KiteTicker (websockets), which this app never imports. | dependency | Accepted. Revisit when kiteconnect releases a new version. |
| 8 | Low | The real-order ticket sends typed limit prices, but `broker.preview_order` always uses the current bid. The confirm dialog shows the price actually used, so nothing is hidden, but a typed price is silently ignored. | `engine/broker.py`, `OrderModal.jsx` | Open, product decision: honour the typed limit, or disable the field for real orders. |
| 9 | Low | `COOLIFY_TOKEN` is a repo secret that PR workflows can read. It's fine while only trusted collaborators can push, but the token can redeploy every app on the Coolify host. | `.github/workflows/ci.yml` | Open: move deploy secrets into a GitHub Environment limited to `main`, and give the token only the permissions deploys need. |
| 10 | Low | Actions are pinned by tag (`@v4`), not by commit SHA. | CI | **Fixed** in #66: every action is pinned to a commit SHA, and Dependabot keeps the pins current. |
| 11 | Info | The `user_sess:{id}` Redis sets never expire, so ended sessions' hashes pile up until the next "end all sessions". This is a slow memory leak, not a security risk. | `engine/auth.py` | Open, housekeeping. |

## Controls checked and found adequate

- **Authorization tables**: `USER_METHODS` get `user_id` from the session only, and `rpc_guard` refuses a client-sent `user_id` or `_`-prefixed parameter. Connecting a broker is admin-only. Once someone is connected, order calls act only on their own connection. The check that no RPC name appears in two tables holds.
- **RLS**: every user table has `FORCE ROW LEVEL SECURITY` with an `app.user_id` policy, and the app role is `NOBYPASSRLS`. Every virtual/broker query also filters on `user_id`. `va_exit_group`/`va_price_levels` (`ANY_SYMBOL`) check ownership themselves.
- **CSRF**: Origin allow-list on `/rpc`. A missing `Origin` is refused, JSON content-type is required, and cookies are `SameSite=Lax`, `HttpOnly`, `__Host-`, `Secure`.
- **Sessions**: 256-bit random tokens, stored only as SHA-256. A new token on every sign-in, 7-day sliding / 30-day cap. Disabling a user, rejecting a sign-up or changing a password ends every session. Status is re-checked on every request.
- **Passwords**: argon2id (64 MB, 3 passes), a common-password list, and a dummy hash for unknown emails so response timing doesn't reveal them. Admin resets issue a one-time password that must be changed.
- **Input validation**: finite numbers only (NaN/Infinity refused), bounded legs, lots, prices, capital and settings, symbols checked against the Nifty 50.
- **Error handling**: expected errors are `ValueError`/`TimeoutError` and are shown to the user. Upstream NSE errors get a fixed message. Anything else is logged with a ref id, and the client gets a generic message. HTTP errors come back as JSON-RPC errors, never HTML. Re-pricing after a trade never turns a committed trade into an error (`_then_refresh`).
- **Real-money safeguards**: only SELL LIMIT orders. Every order needs a preview plus a one-time confirm token (60 s) redeemed by the user who previewed it. Margin is checked against the broker's own `net`. Legs stop at the first failure with no automatic square-off. The worker never places an entry order, and auto-trade is virtual only. Tokens are encrypted at rest, and rotation is supported (#15–#17).
- **Headers and proxy**: strict CSP (no inline script), HSTS, frame-ancestors none, nosniff, Referrer-Policy, Permissions-Policy. The API sets its own headers as well. ProxyFix trusts one hop only. On Coolify, `CF-Connecting-IP` is trusted only from Cloudflare ranges.
- **Containers**: base images pinned by digest, API runs as non-root with a read-only root filesystem, all capabilities dropped, `no-new-privileges`, data network separated.
- **Secrets**: none committed (checked with `git ls-files`). Docker secret files for self-hosted, env vars on Coolify.
- **Frontend**: the RPC error path always gives the user a message. The real-order dialog disables its button while sending, and a retry after an error can't reuse the spent token.

## Scan results

- `pip-audit -r requirements.txt`: 3 advisories, all in the transitive `autobahn` (finding 7).
- `npm audit --omit=dev` (frontend): 0 vulnerabilities.
- Secrets in git: none found.

## Residual risk and follow-up

1. ~~Lock the Python dependencies with hashes (finding 6).~~ Done in #63.
2. Decide on the real-order limit price (finding 8) before the broker rollout (#9/#10).
3. Scope the deploy secrets and token (finding 9).
4. The per-IP limits still rely on Traefik replacing the client-sent `X-Forwarded-For` (documented in `deploy/Caddyfile.coolify`). Re-check this if the proxy chain changes.
5. Real-money auto-trade (#12–#14) will need its own review. Nothing here covers it.
