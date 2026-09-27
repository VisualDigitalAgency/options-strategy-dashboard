# Contributing

This is a private, proprietary project (see [LICENSE](LICENSE)). These notes are for collaborators the owner has invited.

## Set up

Follow [README → Run locally](README.md#run-locally): Postgres and Redis dev containers, `pip install --require-hashes -r requirements.txt` (to add or upgrade a package, edit `requirements.in` and run `make lock`), `alembic upgrade head`, then run the API, the worker and the Vite dev server. You need Python 3.12, Node 22 and Docker.

## Workflow

1. Branch from `main` (`fix/…`, `feat/…`). Don't push straight to `main`: every push to `main` deploys to production once CI passes.
2. Keep changes focused. One pull request per fix or feature.
3. Before pushing, run the same checks CI runs:
   ```bash
   npm --prefix frontend run lint
   npm --prefix frontend test
   npm --prefix frontend run build
   make test
   ```
4. Open a pull request. CI runs the lint, UI tests, build, backend integration tests and Docker image builds. All must pass before merging.
5. Merging to `main` deploys through Coolify. Deploys are held during market hours (weekdays 09:00–15:35 IST) and go out at 15:45 IST. See [deploy/COOLIFY.md](deploy/COOLIFY.md).

Commit messages: an imperative summary line under about 72 characters ("Fix duplicate exit orders"), then a body that says why, if it isn't obvious.

## Conventions

These trip people up. [CLAUDE.md](CLAUDE.md) has the full architecture notes.

**RPC methods (`server.py`)**
- Register each method in exactly one table: `PUBLIC_METHODS`, `ACCOUNT_METHODS`, `METHODS`, `USER_METHODS` or `ADMIN_METHODS`. The table decides who may call it and how arguments are passed.
- `rpc_guard.validate` checks params against the handler's signature, so type-annotate every parameter accurately.
- Parameters named `user_id`, or starting with `_`, can never come from a client.
- Wrappers must use `functools.wraps`, as `_then_refresh` does.
- A `symbol` param is checked against the Nifty 50. For a method that must also work for stocks that have left the index, add it to `ANY_SYMBOL` and check the user holds the stock (see `virtual.price_levels`).

**Errors**
- Raise `ValueError` (or `TimeoutError`) with a message written for the user.
- Anything else is logged with a reference id, and the client only sees a generic message. Don't catch broad exceptions just to hide them.

**Database**
- Every schema change is an Alembic migration.
- A new user-owned table needs a row-level security policy on `app.user_id`, plus grants to `theta_app` (only if that role exists). Copy an existing migration.
- Read and write per-user data through `db.tx(user_id)`.

**Trading code (`engine/virtual.py`)**
- Anything that books a trade or changes margin runs under `_lock` plus the account row lock (`_lock_account`).
- Re-check state inside the lock. Two tabs, two API processes and the worker can all act at once.

**Background work**
- Scheduled work belongs in the worker (`engine/worker.py`), never in the API process.

**Real broker code (`engine/broker.py`, `engine/brokers/`)**
- A second broker adds one file implementing `engine/brokers/base.py`'s `BrokerAdapter` plus one line in `engine/brokers/registry.py` — no changes to the RPC or DB layers.
- Broker order placement must never be retried automatically without a fresh user confirmation (`broker_preview_order`'s one-time `confirm_token`). A failed leg stops the whole order; never auto square-off a leg that already placed.
- Never log or return a broker access/public token, api secret, or a raw broker API response body that might embed one — log a reference id the way `server.py` already does for unexpected errors.
- Anything that reads or writes `broker_connections`/`broker_orders` goes through `engine/broker.py`; the worker's `engine/brokers/poller.py` is read-only reconciliation and must never place, modify or cancel an order.

**Market data**
- NSE's API is unofficial and rate-limits hard. Go through the existing caches and `cache.Throttle`, and don't add per-request NSE calls.

**Frontend**
- No inline scripts, because the CSP forbids them.
- Pages must work down to 320 px wide.
- Pollers must stop when their component unmounts.

**Coolify deployment**
- Never bind-mount repo files in `docker-compose.coolify.yml`; bake them into an image instead.

**Configuration**
- Screening thresholds belong in `engine/config.py`, not in logic.

## Tests

- **Backend** (`tests/test_*.py`):
  - Plain scripts that print `PASS`/`FAIL` lines and exit non-zero on failure.
  - They run against a real Postgres and Redis. `tests/run.py` gives each file its own fresh database.
  - Stub market data with `tests/support.py`; tests must not call NSE or Yahoo. Real-data checks go behind `LIVE_DATA=1`.
  - For a bug fix, add a test that fails on the old code and passes on the new.
  - Run one file with `python tests/run.py test_name.py`.
- **Frontend** (`frontend/tests/*.test.jsx`):
  - Bundled with rolldown and run in happy-dom by `npm test`.
  - Stub `fetch` to fake the RPC server, as the existing tests do.

## Security and data

- Never commit secrets, `.env`, anything in `secrets/`, database dumps, or real users' data (including emails). Use `you@example.com` in docs and examples.
- Report vulnerabilities privately, as described in [SECURITY.md](SECURITY.md).

## Licence of contributions

By contributing, you agree that your contribution becomes the property of the copyright holder, as set out in [LICENSE](LICENSE).
