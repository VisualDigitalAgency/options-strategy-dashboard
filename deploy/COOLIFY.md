# Deploying on Coolify

Server: `ubuntu@129.154.45.57` (OCI, aarch64), Coolify 4.3.23, Traefik v3.6, Let's Encrypt HTTP-01.
Every `*.connectbiomedical.com` app sits behind Cloudflare (orange cloud) → Traefik → the app.
Theta Desk is Coolify application `uygwpa9ukr3zdoufohiyvnfc` ("theta-desk"), Docker Compose build
pack, compose file `/docker-compose.coolify.yml`, branch `main`.

## What went wrong on the first deploy (2026-09-26)

| # | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | `api` unhealthy, `/healthz` 503; api and worker log `password authentication failed for user "theta_app"` | Postgres logged `psql: error: /docker-entrypoint-initdb.d/10-roles.sql: Permission denied`, so the `theta_app` role was never created | Role is now created and its password synced by `scripts/ensure_app_role.py` in `migrate` |
| 2 | That "Permission denied" | Coolify copies only the compose file to `/data/coolify/applications/<uuid>/`. The relative bind mount `./deploy/postgres-init.coolify.sql` pointed at a missing path, and Docker created an empty **directory** there. The same happened to `./deploy/Caddyfile.coolify` | No bind mounts of repo files. The Caddyfile is baked into `Dockerfile --target web-coolify` |
| 3 | `migrate` exited 0, but the app would still have had no rights | Migrations `GRANT` to `theta_app` only if the role exists. It didn't exist when they ran, and alembic is already at `0003`, so they won't run again | Recreate the (empty) database volume so the migrations run after the role exists |
| 4 | `web` stuck in `Created`; the domain returns 503 | It waits for `api` to be healthy (#1). Also, no domain is assigned to `web` (`docker_compose_domains` is empty, no Traefik labels), so Traefik has no route | Assign the domain to the `web` service in the Coolify UI |
| 5 | All five deployments marked `failed` | Follows from #1–#4 | — |
| 6 | Latent: every visitor would share one IP | Cloudflare → Traefik → Caddy → api. Caddy forwarded Traefik's container IP, so the per-IP limits (30 failed sign-ins / 15 min, 5 sign-ups / hour) would have locked everyone out together, and the audit log would show one IP | `Caddyfile.coolify` trusts `CF-Connecting-IP` only when Traefik's peer is a Cloudflare range, and sends the visitor IP to the API |

## Deploy steps

1. **Push** the fixes to `main` (Coolify builds from `git@github.com:VisualDigitalAgency/options-strategy-dashboard.git`).
2. **Rotate the database passwords** in Coolify → theta-desk → Environment Variables, because the owner password was exposed during debugging. Set `DB_OWNER_PASSWORD` and `DB_APP_PASSWORD` to new values (`python -c "import secrets; print(secrets.token_hex(24))"`). Keep `REDIS_PASSWORD`, `DOMAIN=theta.connectbiomedical.com`, `PUBLIC_URL=https://theta.connectbiomedical.com` and `ADMIN_EMAIL`. Each variable appears twice (preview and production); set the production one.
3. **Assign the domain**: Coolify → theta-desk → Configuration → the `web` service → Domains: `https://theta.connectbiomedical.com`. Leave the others (api, worker, migrate, postgres, redis) blank.
4. **Reset the database volume.** It holds no users (checked: `users` = 0), so nothing is lost:
   ```bash
   ssh -i ~/.ssh/oci_instance_key_rsa ubuntu@129.154.45.57
   sudo docker ps -aq --filter name=uygwpa9ukr3zdoufohiyvnfc | xargs -r sudo docker rm -f
   sudo docker volume rm uygwpa9ukr3zdoufohiyvnfc_pg-data
   sudo rm -rf /data/coolify/applications/uygwpa9ukr3zdoufohiyvnfc/deploy   # the stray empty dirs
   ```
   Postgres must start on a fresh volume anyway, because the new `DB_OWNER_PASSWORD` only applies at `initdb`.
5. **Deploy** from Coolify. Expected order: postgres, redis healthy → migrate prints `theta_app role created` and exits 0 → api healthy → worker healthy → web healthy.
6. **Create the admin**, then **verify** (next section):
   ```bash
   sudo docker exec -it $(sudo docker ps -qf name=api-uygwpa9ukr3zdoufohiyvnfc) python scripts/set_admin.py you@example.com
   ```
7. **Cloudflare**: SSL/TLS mode **Full (strict)**. With Traefik's Let's Encrypt certificate at the origin, that works and stops Cloudflare accepting a downgraded origin.

## Verify

- `sudo docker ps --filter name=uygwpa9ukr3zdoufohiyvnfc`: six containers, `migrate` is `Exited (0)`, the rest `healthy`.
- `curl -s https://theta.connectbiomedical.com/healthz` → `{"postgres":true,"redis":true,"worker":true}`.
- Sign in, then open `/admin` → activity log: the `login` row must show **your** public IP, not a `10.x`/`172.x` or Cloudflare address.
- `curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Origin: https://evil.example' -H 'Content-Type: application/json' -d '{}' https://theta.connectbiomedical.com/rpc` → `403`.
- Response headers on `/` include `Strict-Transport-Security`, `Content-Security-Policy` and `X-Frame-Options: DENY`.
- The worker log shows `worker lock acquired` and, in market hours, screen refreshes. The first screen takes about a minute.

## CI/CD (GitHub Actions)

`.github/workflows/ci.yml` runs on every push and pull request:

| Job | What it checks |
|---|---|
| Frontend | `npm run lint`, `npm test` (happy-dom UI tests), `npm run build` |
| Backend | `python tests/run.py`: integration tests against real Postgres 16 + Redis 7, fresh database per file |
| Docker images | builds the `app` and `web-coolify` targets (not pushed; Coolify builds its own) |
| Deploy | `main` only, after all three pass: `scripts/ci_deploy.sh` asks Coolify's API to deploy, waits for `finished`, then smoke-tests `/healthz`, `/`, the Origin check, `GET /rpc` and the CSP header |

**Market hours.** Weekdays 09:00–15:35 IST the deploy job holds (tested, not shipped), because a restart pauses the SL monitor for up to a minute. A scheduled run at 15:45 IST deploys `main` if Coolify isn't already running it. *Actions → CI/CD → Run workflow* with "Deploy even if the market is open" overrides the hold.

**One-time setup:**
1. Coolify → *Keys & Tokens* → *API tokens* → create a token with the **deploy** and **read** abilities.
2. Save it as a repository secret named `COOLIFY_TOKEN`: `gh secret set COOLIFY_TOKEN` (paste it when asked), or GitHub → Settings → Secrets and variables → Actions.
3. Save the server's IP as a second secret, `ORIGIN_IP`: `gh secret set ORIGIN_IP`. Cloudflare shows GitHub's runners a bot challenge ("Just a moment..."), so the deploy connects straight to the origin with the real hostnames (TLS still verified). If you later firewall the origin to Cloudflare's IP ranges only, allow GitHub's runners too or switch this to a Cloudflare WAF skip rule.
4. Optional: GitHub → Settings → Environments → `production` → add yourself as a required reviewer if you want to approve each deploy.

Don't also turn on Coolify's own auto-deploy webhook, or every push deploys twice, and without the tests or the market-hours hold.

**Preview environment.** A separate, isolated Coolify application (own DB/Redis/domain, a feature branch instead of `main`) for testing live before merging — see `deploy/PREVIEW.md`.

A failed deploy leaves the previous containers running only if the build failed; if new containers start but the smoke test fails, roll back as below.

## Rollback

The Coolify UI can redeploy a previous commit. The database is only created by migrations, so rolling back past a migration needs `alembic downgrade` run in `migrate` first.

## Real broker connection (phase 1: Zerodha)

See `doc/2026-09-26-broker-integration-phase1-zerodha.md` for the full design. Coolify env vars to add (theta-desk → Environment Variables):

- `BROKER_ENC_KEY` — a Fernet key (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`), used to encrypt every user's Zerodha access token at rest. To rotate it, see `scripts/rotate_broker_key.py` (run with the new key as `BROKER_ENC_KEY` and the old one as `BROKER_ENC_KEY_PREVIOUS`); changing it without that makes existing connections unreadable (users just reconnect).
- `KITE_API_KEY` / `KITE_API_SECRET` — from the one Kite Connect app registered at developers.kite.trade for this deployment. Every user connects their own Zerodha account through it; these two are operator-level, not per-user.
- `KITE_REDIRECT_URL` — must exactly match the redirect URL registered for the Kite Connect app, e.g. `https://theta.connectbiomedical.com/broker/zerodha/callback`.

Phase 1 is soft-launched to admin accounts only (`ctx.user["role"] == "admin"` gates `broker_connect_url`/`broker_exchange_token`), so these vars can be set without exposing real-money trading to every user.

## Known residual risks

- Coolify injects every UI variable into every service (`env_file: .env`), so `DB_OWNER_PASSWORD` is readable inside api, worker and web. The app only uses it in `migrate`. The code can't remove this; it goes away only if you keep the owner password out of Coolify and run migrations by hand.
- The origin (129.154.45.57:443) is reachable without Cloudflare. The IP handling is spoof-proof either way, but restricting 80/443 to Cloudflare ranges in the OCI security list would also hide the origin from scans. Let's Encrypt HTTP-01 still works through Cloudflare. Doing this affects every app on the host.
- `GET /healthz` is public and says whether Postgres, Redis and the worker are up. It exposes no data.
