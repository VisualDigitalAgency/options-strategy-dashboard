-- Coolify variant of postgres-init.sh: a .sql file needs no executable bit (Postgres's
-- entrypoint runs *.sql files through `psql -f`, unlike *.sh which it must exec or source),
-- which sidesteps bind-mount permission-bit issues across Coolify's build pipeline.
\getenv app_pw DB_APP_PASSWORD
CREATE ROLE theta_app LOGIN PASSWORD :'app_pw' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
REVOKE ALL ON DATABASE theta FROM PUBLIC;
GRANT CONNECT ON DATABASE theta TO theta_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
