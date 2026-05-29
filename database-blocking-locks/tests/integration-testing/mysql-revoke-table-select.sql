-- =============================================================================
-- Phase 3d setup: revoke fis_runner's SELECT on app_orders so the harness's
-- existence probe trips the permission-denied path and exits 24.
-- =============================================================================
-- Run as the RDS master user against the cluster.
--
--   mysql --host=<mysql-endpoint> --port=3306 --user=<master-user> \
--         --password < mysql-revoke-table-select.sql
--
-- After this runs, a TargetTableName=app_orders run will exit 24 with:
--   ERROR: SELECT permission denied on target table `app_orders` (engine=mysql). ...
--
-- Run mysql-restore-table-select.sql afterwards to put the permission back.
-- =============================================================================

REVOKE SELECT ON appdb.app_orders FROM 'fis_runner'@'%';
FLUSH PRIVILEGES;
