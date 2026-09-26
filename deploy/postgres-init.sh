#!/bin/sh
# Runs once, when the data volume is first created. The image's superuser (theta_owner) owns the
# schema and is used only by the migrate service; the app connects as theta_app, which can read
# and write rows but can't change tables, bypass row-level security or delete audit entries.
set -eu
APP_PW="$(cat /run/secrets/db_app_password)"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE theta_app LOGIN PASSWORD '${APP_PW}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
REVOKE ALL ON DATABASE ${POSTGRES_DB} FROM PUBLIC;
GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO theta_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
