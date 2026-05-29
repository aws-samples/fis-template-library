-- =============================================================================
-- Phase 3d teardown: restore fis_runner's SELECT on app_orders.
-- =============================================================================
-- Run as the RDS master user against the cluster.
--
--   mysql --host=<mysql-endpoint> --port=3306 --user=<master-user> \
--         --password < mysql-restore-table-select.sql
-- =============================================================================

GRANT SELECT ON appdb.app_orders TO 'fis_runner'@'%';
FLUSH PRIVILEGES;
