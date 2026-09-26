# Security policy

## Reporting a vulnerability

Please report security problems privately. **Don't open a public issue or pull request** for them.

- Open a draft security advisory in this repository (*Security → Advisories → New draft security advisory*), or
- message the repository owner, [@VisualDigitalAgency](https://github.com/VisualDigitalAgency), on GitHub and ask for a private channel.

Include what you found, how to reproduce it (requests, parameters, the page involved), and what an attacker could do with it. Don't include real users' data, and don't test against the production site (https://theta.connectbiomedical.com) beyond what's needed to confirm the problem. Use a local copy instead (see the README).

We aim to acknowledge a report within 3 working days and to fix confirmed high-severity issues within 14 days. We'll tell you when it's fixed.

## Supported versions

Only `main`, which is what runs in production. There are no released versions.

## Scope

In scope: the API (`server.py`, `rpc_guard.py`, `engine/`), the frontend, the Caddy configs, the Docker and Coolify deployment files, and the CI/CD workflow.

Out of scope: NSE, Yahoo Finance, Zerodha/Kite Connect, Cloudflare and Coolify themselves; volumetric denial of service.

**Real broker connections (phase 1).** The app can now connect a user's own Zerodha account (`engine/broker.py`, `engine/brokers/`) and place real, real-money orders — soft-launched to admin accounts only, manual-confirm-only (no autonomous real-money auto-trade; `engine/autotrade.py` still only trades the virtual account). A Zerodha access token is encrypted at rest (`engine/broker_crypto.py`, Fernet, key from `BROKER_ENC_KEY`/`BROKER_ENC_KEY_FILE`) and only decrypted in-process to call Kite; it is never logged. Disconnecting a broker best-effort invalidates the token at Zerodha's end too, but the primary control is always the local `broker_connections` row — if invalidation at Zerodha fails, the app still refuses to use that connection. Known limitation: encryption key rotation has no tooling yet (see `doc/2026-09-26-broker-integration-phase1-zerodha.md`).

## What's already in place

Knowing this saves you reporting it as missing:

- **Authentication.** Argon2id password hashes. Session tokens are stored only as SHA-256 hashes, in `__Host-` HttpOnly, Secure, SameSite=Lax cookies. Failed sign-ins are limited to 5 per email and IP pair and 30 per IP every 15 minutes.
- **Authorisation.** Every RPC method is in exactly one access table (public, signed in, per-user, admin). `rpc_guard.validate` refuses unknown parameters, wrong types, NaN/Infinity, and any client-sent `user_id`.
- **Data isolation.** The app's Postgres role has no DDL rights and no `BYPASSRLS`. Row-level security on every user-owned table limits each query to the signed-in user.
- **CSRF.** Each `/rpc` call's `Origin` header must exactly match the public origin.
- **Headers.** Strict CSP with no inline scripts, HSTS, `X-Frame-Options: DENY`, `nosniff`, and a same-origin referrer policy.
- **Errors.** Unexpected errors are logged with a reference id. Clients only see a generic message.
- **Network.** Postgres and Redis are not published. Redis needs a password. Containers run as non-root, and the web container's filesystem is read-only.

## Handling secrets

Never commit secrets, `.env` files, `secrets/` contents, database dumps or real user data. Production passwords live in Coolify's environment variables, and the CI deploy token in the GitHub secret `COOLIFY_TOKEN`. If a secret leaks, rotate it first (deploy/COOLIFY.md explains how), then tell the owner.
