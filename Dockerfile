# One Dockerfile, two images:
#   --target app  Python API + worker (same image, different command)
#   --target web  Caddy serving the built React app and proxying /rpc to the API
# Base images are pinned by digest so a rebuild never pulls something different.

# ---------- frontend build ----------
FROM node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- Python app (api + worker + migrate) ----------
FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9 AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp TZ=Asia/Kolkata
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY server.py rpc_guard.py alembic.ini ./
COPY engine/ engine/
COPY migrations/ migrations/
COPY scripts/ scripts/
# Non-root. engine/cache (SPAN files, last screen) is a volume shared by api and worker.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin theta \
 && mkdir -p engine/cache engine/data && chown theta:theta engine/cache engine/data
USER theta
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "--threads", "4", "--timeout", "120", \
     "--access-logfile", "-", "server:app"]

# ---------- web ----------
FROM caddy:2-alpine@sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b AS web
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend /src/dist /srv

# ---------- web behind Coolify's Traefik ----------
# The config is baked in, not bind-mounted: Coolify keeps only the compose file on the host, so a
# relative mount of a repo file turns into an empty directory.
FROM web AS web-coolify
COPY deploy/Caddyfile.coolify /etc/caddy/Caddyfile
