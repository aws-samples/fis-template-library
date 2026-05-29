-- =============================================================================
-- database-blocking-locks integration test fixtures: PostgreSQL teardown
-- =============================================================================
-- Run as the RDS master user against the cluster's default `postgres` database.
--
--   psql --host=<pg-endpoint> --port=5432 --username=<master-user> \
--        --dbname=postgres --file=postgres-teardown.sql
--
-- Idempotent: re-running on an already-clean instance is a no-op.
-- =============================================================================

-- Force-disconnect any sessions still on appdb (otherwise DROP DATABASE fails).
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'appdb' AND pid <> pg_backend_pid();

DROP DATABASE IF EXISTS appdb;

-- Revoke the database-level CONNECT grant (a no-op if appdb no longer exists,
-- but covers the case where a prior teardown left the role in place).
-- DROP ROLE will fail if any objects still depend on the role; the database
-- drop above takes care of that.
DROP ROLE IF EXISTS fis_runner;
