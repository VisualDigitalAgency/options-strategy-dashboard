#!/bin/sh
# Coolify variant of postgres-init.sh: reads the app role's password from the plain
# DB_APP_PASSWORD env var (Coolify-managed) instead of a Docker secrets file.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE theta_app LOGIN PASSWORD '${DB_APP_PASSWORD}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
REVOKE ALL ON DATABASE ${POSTGRES_DB} FROM PUBLIC;
GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO theta_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
