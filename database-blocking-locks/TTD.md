Update experiment so it accepts a target database and table name (or whatever is required to actually impact the database for the application) or the experiment won't cause any impact to the steady state; it will just show whether or not you can detect the metric on the temp database created by the experiment - will this need a database specific SQL query too? Will need to ensure a safe way to pass this....


## Real_Mode integration test plan

The Real_Mode flow (`TargetTableName != fis_blocking_locks_target`) introspects the target table's primary key, selects the first row, and locks it with `SELECT ... FOR UPDATE` (PostgreSQL/MySQL) or `SELECT ... WITH (UPDLOCK, HOLDLOCK)` (SQL Server). Because the safety guarantee is that the user-supplied table is read-only for the duration of the experiment, end-to-end validation requires running against a real RDS instance per engine and observing both the engine-specific blocked-waiter metric and the byte-for-byte equality of the target table before and after.

These scenarios are **manual operator tests, not coding tasks**. They are documented here so the validation is repeatable when the feature is exercised against real RDS instances (e.g. before each release that touches the harness, or whenever the per-engine blocked-waiter metric needs to be re-confirmed).

For each scenario below, the operator performs the steps once per engine: PostgreSQL (Aurora PostgreSQL or RDS PostgreSQL), MySQL/InnoDB (Aurora MySQL or RDS MySQL), and SQL Server (RDS SQL Server). All scenarios assume the FIS template, SSM document, and IAM artefacts are deployed and that an EC2 Load_Generator can reach the database endpoint over the configured port.

### Pre-test setup (per engine)

1. Provision (or reuse) a small RDS instance for the engine under test.
2. Create a database user with at minimum:
   - `SELECT` on the target application table.
   - `SELECT` on `information_schema.table_constraints` and `information_schema.key_column_usage` (PostgreSQL/MySQL), or on `sys.indexes`, `sys.index_columns`, and `sys.columns` (SQL Server).
3. Store that user's password in a Secrets Manager secret and capture the secret ARN for `DatabasePasswordSecretArn`.
4. Capture a "before" snapshot of the target table that includes the row count and a deterministic dump of every column value of every row (e.g. `SELECT * FROM <table> ORDER BY <pk_columns>` written to a file).

### Scenario 1 — Happy path (single-column primary key)

Validates Requirements 1.5, 1.6, 4.5, 7.4, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 11.1, 11.2, 11.3.

Setup:

- Pre-create an application table with a single-column primary key and 100 rows.
- Set `TargetTableName` to that table's name (schema-qualified for SQL Server, unqualified for PostgreSQL/MySQL).
- Run the experiment with `WaiterCount=5`, `ExperimentDuration=PT5M`, `RampTime=PT1M`, `RampSteps=5`.

Confirm:

- The engine-specific blocked-waiter metric ramps from 0 to 5 over the `RampTime` and returns to baseline after `ExperimentDuration` elapses.
  - PostgreSQL: `SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'`.
  - MySQL/InnoDB: Aurora `BlockedTransactions` CloudWatch metric or `SELECT COUNT(*) FROM performance_schema.data_lock_waits`.
  - SQL Server: `SELECT cntr_value FROM sys.dm_os_performance_counters WHERE counter_name = 'Processes blocked'`.
- After the experiment completes, the target table row count is unchanged and a deterministic dump of every column value of every row is byte-for-byte identical to the "before" snapshot.
- The synthetic `fis_blocking_locks_target` table is NOT created in the target database.
- The harness exit status is 0.
- CloudWatch Logs for the SSM step include a line of the form `Mode: Real_Mode  TargetTableName: <name>`.

### Scenario 2 — Composite primary key

Validates Requirements 4.5, 11.5 (in addition to the Requirements covered by Scenario 1).

Setup:

- Pre-create an application table whose primary key has two columns and 100 rows.
- Set `TargetTableName` to that table's name.
- Run the experiment with the same ramp parameters as Scenario 1.

Confirm:

- All outcomes from Scenario 1 hold (blocked-waiter ramp, byte-for-byte equality, no synthetic table created).
- The locking SELECT statement carries both primary-key column values. To verify, query the engine-specific lock-wait view during the experiment and confirm the blocked statement's `WHERE` clause references both PK columns:
  - PostgreSQL: `SELECT query FROM pg_stat_activity WHERE wait_event_type = 'Lock'`.
  - MySQL/InnoDB: `SELECT * FROM performance_schema.events_statements_current WHERE thread_id IN (SELECT thread_id FROM performance_schema.data_lock_waits)`.
  - SQL Server: `SELECT text FROM sys.dm_exec_requests r CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) WHERE r.blocking_session_id <> 0`.

### Scenario 3 — Error paths

Validates Requirements 1.5, 7.4, 10.1, 10.2, 10.3, 10.4, 10.5.

Run four short experiments per engine, each pointed at a deliberately-broken target. For each, capture the SSM step exit code and confirm the target database is unmodified after the harness exits (no DDL, no DML, no synthetic table created, no rows inserted/updated/deleted).

| # | Setup | Expected exit code | Expected diagnostic shape |
|---|---|---|---|
| 3a | `TargetTableName` set to a table that does not exist in `DatabaseName` | 20 | Names the table, the engine, and "table does not exist". |
| 3b | `TargetTableName` set to an existing table that contains zero rows | 21 | Names the table, the engine, and "table is empty". |
| 3c | `TargetTableName` set to a table that exists, has rows, but has no primary key constraint | 23 | Names the table, the engine, and "no primary key". |
| 3d | `TargetTableName` set to a valid table, but `DatabaseUser` lacks `SELECT` on the metadata views (`information_schema.table_constraints`/`information_schema.key_column_usage` for PostgreSQL/MySQL; `sys.indexes`/`sys.index_columns`/`sys.columns` for SQL Server) | 24 | Names the table, the engine, the metadata views the operator must grant SELECT on, and the underlying driver exception class. |

Use a short `ExperimentDuration` (e.g. `PT1M`) for these scenarios since the harness is expected to exit before any waiter ramp begins.

### SQL Server-only extras

#### Scenario 4 — Schema-qualified vs unqualified `TargetTableName`

Validates Requirement 2.5.

Run Scenario 1 twice on RDS SQL Server:

- Once with a schema-qualified name, e.g. `TargetTableName = dbo.orders`.
- Once with an unqualified name, e.g. `TargetTableName = orders` (which the harness defaults to the `dbo` schema).

Confirm both runs succeed with identical outcomes (Scenario 1 acceptance criteria) and that the harness CloudWatch Logs reference the same fully-qualified table reference in both cases.

#### Scenario 5 — Plain-`SELECT` workload with RCSI enabled

Validates Requirement 13.5.

Setup:

- Enable `READ_COMMITTED_SNAPSHOT` (RCSI) on the target SQL Server database. Confirm with:

  ```sql
  SELECT name, snapshot_isolation_state_desc, is_read_committed_snapshot_on
  FROM sys.databases
  WHERE name = DB_NAME();
  ```

  `is_read_committed_snapshot_on` should be `1`.
- Pre-create an application table per Scenario 1.

Run the Scenario 1 experiment, and concurrently from a separate session run a plain-`SELECT` workload against the locked row (e.g. a loop of `SELECT * FROM <table> WHERE <pk_clause>` without any locking hint).

Confirm:

- The plain-`SELECT` workload is NOT blocked while the experiment is in progress (RCSI uses row versioning instead of shared locks).
- The blocked-waiter metric still ramps to 5 (write-intent waiters from the harness still block on the Blocker).
- The target table is byte-for-byte identical before and after.

For comparison, repeat the same scenario with RCSI disabled (`is_read_committed_snapshot_on = 0`) and confirm the plain-`SELECT` workload IS blocked, matching the README's documented blast radius for default-isolation SQL Server.

### Cleanup (per scenario, per engine)

- Confirm no rows of the target application table were inserted, updated, or deleted (compare against the "before" snapshot from the pre-test setup).
- Confirm `fis_blocking_locks_target` was not created in the target database.
- Drop any application tables created solely for the test.
- Revert RCSI to the database's prior setting if Scenario 5 was run.
