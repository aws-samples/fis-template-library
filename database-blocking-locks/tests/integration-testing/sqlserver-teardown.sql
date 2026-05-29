-- =============================================================================
-- database-blocking-locks integration test fixtures: RDS SQL Server teardown
-- =============================================================================
-- Run as the RDS master user against the instance.
--
--   sqlcmd -S <sqlserver-endpoint>,1433 -U <master-user> -P '<master-password>' \
--          -C -i sqlserver-teardown.sql
--
-- Idempotent: re-running on an already-clean instance is a no-op.
-- =============================================================================

USE master;
GO

IF DB_ID('appdb') IS NOT NULL
BEGIN
    ALTER DATABASE appdb SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE appdb;
END
GO

IF SUSER_ID('fis_runner') IS NOT NULL
    DROP LOGIN fis_runner;
GO
