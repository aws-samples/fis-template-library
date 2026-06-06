-- =============================================================================
-- database-blocking-locks integration test fixtures: MySQL/InnoDB
-- =============================================================================
-- Run as the RDS master user against the cluster.
--
--   mysql --host=<mysql-endpoint> --port=3306 --user=<master-user> \
--         --password < mysql-setup.sql
--
-- Replace the literal 'CHANGE_ME' below with the password you want for the
-- fis_runner user, and store the same value in a Secrets Manager secret.
-- =============================================================================

DROP DATABASE IF EXISTS appdb;
CREATE DATABASE appdb CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

-- '%' lets fis_runner connect from any host. The harness connects from the
-- ephemeral load-generator EC2's private IP, which lives on the test VPC.
DROP USER IF EXISTS 'fis_runner'@'%';
CREATE USER 'fis_runner'@'%' IDENTIFIED BY 'CHANGE_ME';

USE appdb;

-- Fixture A: single-column primary key, 100 rows. Used by Phase 1 and 2.1.
CREATE TABLE app_orders (
    id          INT            NOT NULL,
    customer_id INT            NOT NULL,
    amount      DECIMAL(10, 2) NOT NULL,
    notes       TEXT,
    PRIMARY KEY (id)
) ENGINE = InnoDB;

-- MySQL has no generate_series; use a recursive CTE (MySQL 8+).
INSERT INTO app_orders (id, customer_id, amount, notes)
WITH RECURSIVE seq (n) AS (
    SELECT 1
    UNION ALL
    SELECT n + 1 FROM seq WHERE n < 100
)
SELECT n, n * 7, n * 1.25, CONCAT('order-', n) FROM seq;

-- Fixture B: composite primary key, 100 rows. Used by 2.2.
CREATE TABLE app_order_items (
    order_id INT          NOT NULL,
    line_no  INT          NOT NULL,
    sku      VARCHAR(20)  NOT NULL,
    qty      INT          NOT NULL,
    PRIMARY KEY (order_id, line_no)
) ENGINE = InnoDB;

INSERT INTO app_order_items (order_id, line_no, sku, qty)
WITH RECURSIVE orders (o) AS (
    SELECT 1 UNION ALL SELECT o + 1 FROM orders WHERE o < 20
),
order_lines (l) AS (
    SELECT 1 UNION ALL SELECT l + 1 FROM order_lines WHERE l < 5
)
SELECT o, l, CONCAT('SKU-', (o * 10 + l)), (l * 2)
FROM orders, order_lines;

-- Fixture C: no primary key, 100 rows. Used by Phase 3c (exit 23).
CREATE TABLE app_no_pk (
    a INT NOT NULL,
    b INT NOT NULL
) ENGINE = InnoDB;

INSERT INTO app_no_pk (a, b)
WITH RECURSIVE seq (n) AS (
    SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < 100
)
SELECT n, n * 3 FROM seq;

-- Fixture D: empty table with primary key. Used by Phase 3b (exit 21).
CREATE TABLE app_empty (
    id      INT  NOT NULL,
    payload TEXT,
    PRIMARY KEY (id)
) ENGINE = InnoDB;

-- Grant fis_runner SELECT on every fixture table.
GRANT SELECT ON appdb.app_orders        TO 'fis_runner'@'%';
GRANT SELECT ON appdb.app_order_items   TO 'fis_runner'@'%';
GRANT SELECT ON appdb.app_no_pk         TO 'fis_runner'@'%';
GRANT SELECT ON appdb.app_empty         TO 'fis_runner'@'%';

-- MySQL automatically allows every authenticated user to read
-- information_schema.table_constraints and information_schema.key_column_usage,
-- but the rows are filtered to objects the user has at least one privilege on.
-- The SELECT grants above are sufficient for primary-key introspection.
FLUSH PRIVILEGES;

-- Quick sanity check.
SELECT 'app_orders'      AS fixture, COUNT(*) AS row_count FROM app_orders
UNION ALL
SELECT 'app_order_items',            COUNT(*)             FROM app_order_items
UNION ALL
SELECT 'app_no_pk',                  COUNT(*)             FROM app_no_pk
UNION ALL
SELECT 'app_empty',                  COUNT(*)             FROM app_empty;
