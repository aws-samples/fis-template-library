-- =============================================================================
-- Phase 3d setup: revoke fis_runner's SELECT on app_orders so the harness's
-- existence probe trips the permission-denied path and exits 24.
-- =============================================================================
-- Run as the RDS master user against appdb.
--
--   psql --host=<pg-endpoint> --port=5432 --username=<master-user> \
--        --dbname=appdb --file=postgres-revoke-table-select.sql
--
-- After this runs, the harness invocation `TargetTableName=app_orders`
-- will exit 24 with the diagnostic:
--   ERROR: SELECT permission denied on target table "app_orders" (engine=postgres). ...
--
-- Run postgres-restore-table-select.sql afterwards to put the permission back.
-- =============================================================================

REVOKE SELECT ON app_orders FROM fis_runner;

-- Optional: to exercise the *introspection* permission-denied path (which
-- emits the diagnostic naming `information_schema.table_constraints,
-- information_schema.key_column_usage`), you can additionally revoke the
-- PUBLIC SELECT on those views and re-grant only to the master user.
-- This is wider-blast-radius (it affects every non-superuser role on the
-- cluster) so it's not done by default. To enable, uncomment:
--
--   REVOKE SELECT ON information_schema.table_constraints FROM PUBLIC;
--   REVOKE SELECT ON information_schema.key_column_usage  FROM PUBLIC;
--
-- ...and remember to re-grant in postgres-restore-table-select.sql.
