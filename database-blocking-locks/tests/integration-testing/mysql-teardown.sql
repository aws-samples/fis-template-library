-- =============================================================================
-- database-blocking-locks integration test fixtures: MySQL teardown
-- =============================================================================
-- Run as the RDS master user against the cluster.
--
--   mysql --host=<mysql-endpoint> --port=3306 --user=<master-user> \
--         --password < mysql-teardown.sql
--
-- Idempotent: re-running on an already-clean instance is a no-op.
-- =============================================================================

DROP DATABASE IF EXISTS appdb;
DROP USER IF EXISTS 'fis_runner'@'%';
FLUSH PRIVILEGES;
