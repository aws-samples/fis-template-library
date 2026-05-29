-- =============================================================================
-- database-blocking-locks integration test fixtures: PostgreSQL
-- =============================================================================
-- Run as the RDS master user against the cluster's default `postgres` database.
--
--   psql --host=<pg-endpoint> --port=5432 --username=<master-user> \
--        --dbname=postgres --file=postgres-setup.sql
--
-- Replace the literal 'CHANGE_ME' below with the password you want for the
-- fis_runner user, and store the same value in a Secrets Manager secret.
-- =============================================================================

-- Top-level: create the appdb database and the fis_runner role.
-- These statements run in the `postgres` database.

DROP DATABASE IF EXISTS appdb;
CREATE DATABASE appdb;

DROP ROLE IF EXISTS fis_runner;
CREATE ROLE fis_runner WITH LOGIN PASSWORD 'CHANGE_ME';

-- Allow fis_runner to connect to appdb. Schema-level and table-level grants
-- happen below once we are inside appdb.
GRANT CONNECT ON DATABASE appdb TO fis_runner;

-- Switch into appdb to create the fixture tables.
\c appdb

-- Make sure fis_runner can see and use the public schema (PostgreSQL 15+
-- removed the default PUBLIC create-on-public grant; SELECT on public is still
-- there, but USAGE is required for accessing objects).
GRANT USAGE ON SCHEMA public TO fis_runner;

-- Fixture A: single-column primary key, 100 rows. Used by Phase 1 and 2.1.
CREATE TABLE app_orders (
    id          INTEGER        PRIMARY KEY,
    customer_id INTEGER        NOT NULL,
    amount      NUMERIC(10, 2) NOT NULL,
    notes       TEXT
);
INSERT INTO app_orders (id, customer_id, amount, notes)
SELECT n, n * 7, n * 1.25, 'order-' || n
FROM generate_series(1, 100) AS n;

-- Fixture B: composite primary key (order_id, line_no), 100 rows. Used by 2.2.
-- 20 orders * 5 line items each, primary-key ordinal must be (order_id, line_no)
-- so the harness's introspection returns them in that order.
CREATE TABLE app_order_items (
    order_id INTEGER     NOT NULL,
    line_no  INTEGER     NOT NULL,
    sku      VARCHAR(20) NOT NULL,
    qty      INTEGER     NOT NULL,
    PRIMARY KEY (order_id, line_no)
);
INSERT INTO app_order_items (order_id, line_no, sku, qty)
SELECT o, l, 'SKU-' || (o * 10 + l), (l * 2)
FROM generate_series(1, 20) AS o,
     generate_series(1, 5)  AS l;

-- Fixture C: no primary key, 100 rows. Used by Phase 3c (exit 23).
CREATE TABLE app_no_pk (
    a INTEGER NOT NULL,
    b INTEGER NOT NULL
);
INSERT INTO app_no_pk (a, b)
SELECT n, n * 3 FROM generate_series(1, 100) AS n;

-- Fixture D: empty table with primary key. Used by Phase 3b (exit 21).
CREATE TABLE app_empty (
    id      INTEGER PRIMARY KEY,
    payload TEXT
);

-- Grant fis_runner SELECT on every fixture table.
GRANT SELECT ON app_orders, app_order_items, app_no_pk, app_empty TO fis_runner;

-- PostgreSQL grants SELECT on information_schema views to PUBLIC by default,
-- and the views are row-filtered to objects the user can see. So fis_runner
-- can already read information_schema.table_constraints and
-- information_schema.key_column_usage for the fixture tables; no explicit
-- grant is needed here.

-- Quick sanity check (counts and PK column ordinals). Cosmetic but useful when
-- running the script interactively.
SELECT 'app_orders'      AS fixture, COUNT(*) AS rows FROM app_orders
UNION ALL
SELECT 'app_order_items',           COUNT(*)         FROM app_order_items
UNION ALL
SELECT 'app_no_pk',                 COUNT(*)         FROM app_no_pk
UNION ALL
SELECT 'app_empty',                 COUNT(*)         FROM app_empty;
