# Integration testing — fixture SQL scripts

This folder contains the test plan and the SQL fixtures needed to run it against real RDS instances.

## Files

- [`INTEGRATION-TEST-PLAN.md`](INTEGRATION-TEST-PLAN.md) — the full operator test plan (Phase 0 through 7).
- `postgres-setup.sql` / `postgres-teardown.sql` — provision and clean up the PostgreSQL fixture database.
- `mysql-setup.sql` / `mysql-teardown.sql` — same for MySQL/InnoDB.
- `sqlserver-setup.sql` / `sqlserver-teardown.sql` — same for RDS SQL Server.
- `<engine>-revoke-table-select.sql` / `<engine>-restore-table-select.sql` — used in Phase 3d to validate the exit-24 (permission-denied) failure path.

## What the fixtures create

Each setup script creates the same logical schema on its target engine:

| Object | Purpose |
|---|---|
| `appdb` (PostgreSQL/MySQL) or `dbo` schema in the existing master DB (SQL Server) | Container for the fixture tables. The shipped FIS template's `DatabaseName` should point here. |
| User/login `fis_runner` | The database identity the harness connects as. Granted `SELECT` on every fixture table and on the engine-appropriate metadata views. |
| `app_orders` (Fixture A) | Single-column primary key, 100 rows. Used in Phase 1 (Synthetic_Mode happy path), Phase 2.1 (Real_Mode single PK), and the SQL Server-specific Phase 4 scenarios. |
| `app_order_items` (Fixture B) | Composite primary key (`order_id`, `line_no`), 100 rows. Used in Phase 2.2 (Real_Mode composite PK). |
| `app_no_pk` (Fixture C) | No primary key, 100 rows. Used in Phase 3c (exit 23). |
| `app_empty` (Fixture D) | Has a primary key but zero rows. Used in Phase 3b (exit 21). |

The setup is intentionally identical across engines so that the same Phase-2 expectations (PK column names, locked-row identity) hold on PostgreSQL, MySQL, and SQL Server.

## Before you run

1. Provision a small RDS instance per engine (`db.t3.medium` is fine for test traffic) in the test VPC.
2. Capture the master username, password, and endpoint for each instance.
3. Choose a password for the `fis_runner` user. Replace the literal `'CHANGE_ME'` in each setup script with that password before running. Store the same value in a Secrets Manager secret in the same region; the secret ARN is what you'll pass to the experiment as `DatabasePasswordSecretArn`.
4. Confirm your client tooling is installed locally:
   - PostgreSQL: `psql` (PostgreSQL 15+).
   - MySQL: `mysql` client (MariaDB 10.5+ or MySQL 8+).
   - SQL Server: `sqlcmd` (from `mssql-tools18`).

## Running the setup scripts

### PostgreSQL

```bash
# Run as the RDS master user against the cluster's default `postgres` DB.
# The script issues CREATE DATABASE and then \c into appdb to create tables.
psql \
  --host=<pg-endpoint> \
  --port=5432 \
  --username=<master-user> \
  --dbname=postgres \
  --file=postgres-setup.sql
```

The script will prompt for the master password unless you set `PGPASSWORD` in the environment.

### MySQL

```bash
mysql \
  --host=<mysql-endpoint> \
  --port=3306 \
  --user=<master-user> \
  --password \
  < mysql-setup.sql
```

(`--password` without a value prompts interactively.)

### SQL Server

```bash
sqlcmd \
  -S <sqlserver-endpoint>,1433 \
  -U <master-user> \
  -P '<master-password>' \
  -C \
  -i sqlserver-setup.sql
```

The `-C` flag trusts the RDS server certificate (same posture as the harness).

## Snapshotting before Real_Mode tests

Before running any Phase 2 (Real_Mode) experiment, take a deterministic dump of the fixture tables so you can diff against an `after` snapshot at the end of the run. This is the byte-for-byte-equality check called out in the test plan.

PostgreSQL:

```bash
psql --host=<pg-endpoint> --port=5432 --username=fis_runner --dbname=appdb \
  --csv --command='SELECT * FROM app_orders ORDER BY id'  > before-app_orders-postgres.csv
psql --host=<pg-endpoint> --port=5432 --username=fis_runner --dbname=appdb \
  --csv --command='SELECT * FROM app_order_items ORDER BY order_id, line_no' > before-app_order_items-postgres.csv
```

MySQL:

```bash
mysql --host=<mysql-endpoint> --port=3306 --user=fis_runner --password --database=appdb \
  --batch --execute='SELECT * FROM app_orders ORDER BY id' > before-app_orders-mysql.tsv
mysql --host=<mysql-endpoint> --port=3306 --user=fis_runner --password --database=appdb \
  --batch --execute='SELECT * FROM app_order_items ORDER BY order_id, line_no' > before-app_order_items-mysql.tsv
```

SQL Server:

```bash
sqlcmd -S <sqlserver-endpoint>,1433 -U fis_runner -P '<password>' -C -d appdb \
  -Q 'SET NOCOUNT ON; SELECT * FROM dbo.app_orders ORDER BY id' \
  -s ',' -W -h -1 > before-app_orders-sqlserver.csv
sqlcmd -S <sqlserver-endpoint>,1433 -U fis_runner -P '<password>' -C -d appdb \
  -Q 'SET NOCOUNT ON; SELECT * FROM dbo.app_order_items ORDER BY order_id, line_no' \
  -s ',' -W -h -1 > before-app_order_items-sqlserver.csv
```

Repeat the same dump after the experiment and `diff` the two files. The test passes if the diff is empty.

## Phase 3d permission-denied test

The shipped `<engine>-revoke-table-select.sql` revokes `SELECT` on `app_orders` from `fis_runner`. This trips the existence-probe permission-denied path in `_validate_target_table`, which exits 24 with the diagnostic `ERROR: SELECT permission denied on target table <ref> ...`.

This is a slightly different exit-24 path than the introspection-permission-denied path called out in the test plan (which would require revoking `SELECT` on the engine-specific metadata views — harder to do reliably across engines). Both paths exit 24, so either one validates the requirement. Use the table-revoke path here for repeatability; if you specifically need to exercise the introspection path, see the per-engine notes inside the SQL file.

To run:

```bash
# Phase 3d: revoke
psql ... --file=postgres-revoke-table-select.sql       # or mysql / sqlserver

# Run the FIS experiment with TargetTableName=app_orders, ExperimentDuration=PT1M.
# Capture the exit code from the SSM step output. Expect 24.

# Phase 3d cleanup: restore the permission so subsequent tests still work
psql ... --file=postgres-restore-table-select.sql       # or mysql / sqlserver
```

## Tearing down

After all phases complete, run the matching `<engine>-teardown.sql` to drop the fixture tables, the `fis_runner` user, and (for PostgreSQL/MySQL) the `appdb` database itself:

```bash
psql --host=<pg-endpoint> --port=5432 --username=<master-user> --dbname=postgres --file=postgres-teardown.sql
mysql --host=<mysql-endpoint> --port=3306 --user=<master-user> --password < mysql-teardown.sql
sqlcmd -S <sqlserver-endpoint>,1433 -U <master-user> -P '<master-password>' -C -i sqlserver-teardown.sql
```

The teardown scripts are idempotent — re-running them on an already-clean instance is a no-op and does not error.

## Cost considerations

The fixtures themselves are tiny (≤100 rows per table). The cost is dominated by the underlying RDS instance and the load-generator EC2 spawned by each experiment run, both of which are short-lived. Stop or delete the RDS instances when you are done with the test session to avoid ongoing charges.
