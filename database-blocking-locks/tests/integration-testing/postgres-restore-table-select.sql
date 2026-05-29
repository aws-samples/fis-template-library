-- =============================================================================
-- Phase 3d teardown: restore fis_runner's SELECT on app_orders.
-- =============================================================================
-- Run as the RDS master user against appdb.
--
--   psql --host=<pg-endpoint> --port=5432 --username=<master-user> \
--        --dbname=appdb --file=postgres-restore-table-select.sql
-- =============================================================================

GRANT SELECT ON app_orders TO fis_runner;

-- If you also revoked SELECT on the information_schema views, re-grant them
-- here. By default this is commented out to mirror postgres-revoke-table-select.sql.
--
--   GRANT SELECT ON information_schema.table_constraints TO PUBLIC;
--   GRANT SELECT ON information_schema.key_column_usage  TO PUBLIC;
