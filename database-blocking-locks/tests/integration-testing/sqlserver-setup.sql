-- =============================================================================
-- database-blocking-locks integration test fixtures: RDS SQL Server
-- =============================================================================
-- Run as the RDS master user against the instance.
--
--   sqlcmd -S <sqlserver-endpoint>,1433 -U <master-user> -P '<master-password>' \
--          -C -i sqlserver-setup.sql
--
-- Replace the literal 'CHANGE_ME' below with the password you want for the
-- fis_runner login, and store the same value in a Secrets Manager secret.
--
-- The fixture lives in a database called `appdb` so the experiment's
-- DatabaseName parameter is the same as for PostgreSQL/MySQL. Tables are
-- created in the default `dbo` schema.
-- =============================================================================

USE master;
GO

-- Drop any previous test database. RDS SQL Server doesn't allow KILL on the
-- master user's connections to a database, so we set SINGLE_USER first to
-- evict any other sessions before dropping.
IF DB_ID('appdb') IS NOT NULL
BEGIN
    ALTER DATABASE appdb SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE appdb;
END
GO

-- Drop any previous fis_runner login.
IF SUSER_ID('fis_runner') IS NOT NULL
    DROP LOGIN fis_runner;
GO

CREATE LOGIN fis_runner WITH PASSWORD = 'CHANGE_ME', CHECK_POLICY = OFF;
GO

CREATE DATABASE appdb;
GO

USE appdb;
GO

-- Map the server-level login to a database-level user inside appdb.
CREATE USER fis_runner FOR LOGIN fis_runner;
GO

-- Fixture A: single-column primary key, 100 rows. Used by Phase 1 and 2.1.
CREATE TABLE dbo.app_orders (
    id          INT            NOT NULL PRIMARY KEY,
    customer_id INT            NOT NULL,
    amount      DECIMAL(10, 2) NOT NULL,
    notes       NVARCHAR(MAX)
);
GO

-- SQL Server has no generate_series; use a recursive CTE (SQL Server 2008+).
WITH seq (n) AS (
    SELECT 1
    UNION ALL
    SELECT n + 1 FROM seq WHERE n < 100
)
INSERT INTO dbo.app_orders (id, customer_id, amount, notes)
SELECT n, n * 7, n * 1.25, CONCAT('order-', n)
FROM seq
OPTION (MAXRECURSION 200);
GO

-- Fixture B: composite primary key, 100 rows. Used by 2.2.
CREATE TABLE dbo.app_order_items (
    order_id INT          NOT NULL,
    line_no  INT          NOT NULL,
    sku      NVARCHAR(20) NOT NULL,
    qty      INT          NOT NULL,
    CONSTRAINT pk_app_order_items PRIMARY KEY (order_id, line_no)
);
GO

WITH orders (o) AS (
    SELECT 1 UNION ALL SELECT o + 1 FROM orders WHERE o < 20
),
lines (l) AS (
    SELECT 1 UNION ALL SELECT l + 1 FROM lines WHERE l < 5
)
INSERT INTO dbo.app_order_items (order_id, line_no, sku, qty)
SELECT o, l, CONCAT('SKU-', (o * 10 + l)), (l * 2)
FROM orders, lines
OPTION (MAXRECURSION 200);
GO

-- Fixture C: no primary key, 100 rows. Used by Phase 3c (exit 23).
CREATE TABLE dbo.app_no_pk (
    a INT NOT NULL,
    b INT NOT NULL
);
GO

WITH seq (n) AS (
    SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < 100
)
INSERT INTO dbo.app_no_pk (a, b)
SELECT n, n * 3 FROM seq
OPTION (MAXRECURSION 200);
GO

-- Fixture D: empty table with primary key. Used by Phase 3b (exit 21).
CREATE TABLE dbo.app_empty (
    id      INT NOT NULL PRIMARY KEY,
    payload NVARCHAR(MAX)
);
GO

-- Grant fis_runner SELECT on every fixture table.
GRANT SELECT ON dbo.app_orders      TO fis_runner;
GRANT SELECT ON dbo.app_order_items TO fis_runner;
GRANT SELECT ON dbo.app_no_pk       TO fis_runner;
GRANT SELECT ON dbo.app_empty       TO fis_runner;
GO

-- SQL Server's catalog views (sys.indexes, sys.index_columns, sys.columns) use
-- "metadata visibility": a user can see metadata for objects they have at
-- least one permission on. The SELECT grants above are sufficient for
-- primary-key introspection through OBJECT_ID(...).

-- Quick sanity check.
SELECT 'app_orders'      AS fixture, COUNT(*) AS rows FROM dbo.app_orders
UNION ALL
SELECT 'app_order_items',            COUNT(*)        FROM dbo.app_order_items
UNION ALL
SELECT 'app_no_pk',                  COUNT(*)        FROM dbo.app_no_pk
UNION ALL
SELECT 'app_empty',                  COUNT(*)        FROM dbo.app_empty;
GO
