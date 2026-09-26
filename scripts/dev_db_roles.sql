-- Local dev only: the app role the API and worker connect as. Run once as the owner, before migrating.
-- In Docker (phase 5) the postgres init script creates it with a password from a secrets file.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'theta_app') THEN
    CREATE ROLE theta_app LOGIN PASSWORD 'theta_app_dev' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
END $$;
