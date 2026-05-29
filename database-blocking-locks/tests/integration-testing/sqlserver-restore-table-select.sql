-- =============================================================================
-- Phase 3d teardown: restore fis_runner's SELECT on dbo.app_orders.
-- =============================================================================
-- Run as the RDS master user against the instance.
--
--   sqlcmd -S <sqlserver-endpoint>,1433 -U <master-user> -P '<master-password>' \
--          -C -i sqlserver-restore-table-select.sql
-- =============================================================================

USE appdb;
GO

REVOKE DENY SELECT ON dbo.app_orders TO fis_runner;  -- removes the prior DENY
GRANT SELECT  ON dbo.app_orders TO fis_runner;       -- re-asserts the GRANT
GO
