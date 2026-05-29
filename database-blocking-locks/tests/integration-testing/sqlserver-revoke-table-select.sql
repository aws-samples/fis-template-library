-- =============================================================================
-- Phase 3d setup: revoke fis_runner's SELECT on dbo.app_orders so the harness's
-- existence probe trips the permission-denied path and exits 24.
-- =============================================================================
-- Run as the RDS master user against the instance.
--
--   sqlcmd -S <sqlserver-endpoint>,1433 -U <master-user> -P '<master-password>' \
--          -C -i sqlserver-revoke-table-select.sql
--
-- After this runs, a TargetTableName=dbo.app_orders run will exit 24 with:
--   ERROR: SELECT permission denied on target table [dbo].[app_orders] (engine=sqlserver). ...
--
-- Run sqlserver-restore-table-select.sql afterwards to put the permission back.
-- =============================================================================

USE appdb;
GO

DENY SELECT ON dbo.app_orders TO fis_runner;
GO
