# Preview environment (internal testing before production)

A second, fully isolated Coolify application on the same server as production, running a feature
branch instead of `main` — its own Postgres, its own Redis, its own domain — so a branch can be
tested live internally before it's merged. Nothing in `docker-compose.coolify.yml`, the
`Dockerfile`, or the app code needs to change for this: every domain/password/broker value is
already an environment variable, and Coolify namespaces volumes per application UUID, so a second
application using the same compose file is automatically isolated from production.

This is a one-time manual setup (like `deploy/COOLIFY.md`'s own steps) — not something CI
provisions on its own, since it touches a shared production server.

## One-time setup

1. **Coolify**: *New Resource* → *Application* → same GitHub repo
   (`git@github.com:VisualDigitalAgency/options-strategy-dashboard.git`) → **Docker Compose** build
   pack → compose file `/docker-compose.coolify.yml` → branch `feat/broker-connect-preview` (or
   whichever branch you want previewed — this is per-application, so repointing it later to a
   different branch is just an edit, not a rebuild of everything else). Note the new application's
   **UUID** (shown in its URL, same as `uygwpa9ukr3zdoufohiyvnfc` is theta-desk's).

2. **DNS**: add a record for a preview subdomain, e.g. `theta-preview.connectbiomedical.com`,
   Cloudflare-proxied (orange cloud) like every other `*.connectbiomedical.com` record, pointed at
   the same server (`129.154.45.57`).

3. **Environment Variables** (theta-desk-preview → Environment Variables) — set fresh, **distinct**
   values, never copied from production:
   - `DB_OWNER_PASSWORD`, `DB_APP_PASSWORD`, `REDIS_PASSWORD` — random values
     (`python -c "import secrets; print(secrets.token_hex(24))"`), own isolated database and cache.
   - `DOMAIN=theta-preview.connectbiomedical.com`, `PUBLIC_URL=https://theta-preview.connectbiomedical.com`.
   - `ADMIN_EMAIL` — whoever should be the first preview admin.
   - **Leave `KITE_API_KEY`, `KITE_API_SECRET`, `KITE_REDIRECT_URL` and `BROKER_ENC_KEY` unset.**
     `docker-compose.coolify.yml` defaults all four to empty, so the real-broker feature is simply
     inert here — the "Connect" button will error cleanly instead of doing anything real. This
     means preview testing never needs a second Kite Connect app/redirect-URL registration. If you
     deliberately want to test real Zerodha flows against preview one day, that needs its own Kite
     Connect app (Kite only allows one redirect URL per app key) — don't reuse production's.

4. **Assign the domain**: Configuration → the `web` service → Domains →
   `https://theta-preview.connectbiomedical.com`. Leave api/worker/migrate/postgres/redis blank,
   same as production's setup.

5. **Deploy once from the Coolify UI directly** (don't wait for CI yet), then create the first
   preview admin:
   ```bash
   ssh -i ~/.ssh/oci_instance_key_rsa ubuntu@129.154.45.57
   sudo docker exec -it $(sudo docker ps -qf name=api-<preview-uuid>) python scripts/set_admin.py you@example.com
   ```

6. **A deploy token for CI**: reuse the existing `COOLIFY_TOKEN` repository secret (same Coolify
   instance, same token scope covers any application) — no new token needed.

7. **GitHub secrets**: add the two preview-specific values
   (`gh secret set COOLIFY_PREVIEW_APP_UUID`, `gh secret set COOLIFY_PREVIEW_PUBLIC_URL`, or
   GitHub → Settings → Secrets and variables → Actions). Once both exist, `.github/workflows/ci.yml`'s
   `deploy-preview` job deploys automatically on every push to the branch named in its `if:`
   condition, while that branch's PR is open.

## What CI does (`deploy-preview` job in `.github/workflows/ci.yml`)

Same `scripts/ci_deploy.sh` the production `deploy` job uses, pointed at the preview
`COOLIFY_APP_UUID`/`PUBLIC_URL` instead — queues a Coolify deployment, waits for it to finish, then
runs the same smoke tests (`/healthz`, home page, cross-origin `/rpc` refused, same-origin `/rpc`
answers, `GET /rpc` 405, CSP header) against the preview URL.

Unlike production, there's **no market-hours hold** — preview never touches real trading (no Kite
credentials, see step 3), so there's nothing to protect by delaying a restart. It also has its own
`concurrency` group, so it can never block or be blocked by a production deploy.

Until the two secrets in step 7 exist, `deploy-preview` fails immediately with a clear message
naming the missing secret — it doesn't affect the `frontend`/`backend`/`images`/`deploy` jobs at all.

## To preview a different branch later

Either repoint the same Coolify application's branch (Configuration → General → Branch) and update
`deploy-preview`'s `if:` condition in `ci.yml` to match, or create another Coolify application the
same way for a second, concurrent preview — each is fully isolated, so there's no limit but cost
and DNS records.

## Verify

- `sudo docker ps --filter name=<preview-uuid>`: six containers, `migrate` exited 0, the rest healthy.
- `curl -s https://theta-preview.connectbiomedical.com/healthz` → `{"postgres":true,"redis":true,"worker":true}`.
- Sign in, confirm the broker pages show the "Connect" button disabled/inert (no Kite credentials).
- GitHub Actions: `deploy-preview` green on a push to the previewed branch's PR.
