# Database Blocking Locks — Integration Test Plan

## Purpose

Validate that the `database-blocking-locks` experiment causes the intended fault (row-level lock contention surfaced by the engine-specific blocked-waiter metric), respects every documented safety guarantee, and cleans up after itself, across all three supported engines and both Synthetic_Mode and Real_Mode.

These tests are run in a **non-production AWS account** against **disposable RDS instances**. Real_Mode tests in particular cause real application-side impact — never run them against shared test databases without explicit owner sign-off.

---

## Phase 0 — One-time setup

### 0.1 AWS account artefacts

Provision once and reuse across all phases:

- A VPC with one private subnet that can reach RDS endpoints over the database ports.
- The IAM roles and instance profile from the README's "Create Required Experiment Resources" section: `DatabaseBlockingLocks-FIS-Role`, `DatabaseBlockingLocks-SSM-Automation-Role`, `SSM-Managed-Instance-Profile`.
- The deployed FIS template (tag `Name=database-blocking-locks`) and the SSM automation document (`DatabaseBlockingLocks-Automation`).

### 0.2 Per-engine RDS instances

Create three small RDS instances (one per engine). Use the smallest viable class (`db.t3.medium` or `db.t4g.medium`) on a dedicated test VPC. Note each instance's endpoint, port, and security group ID.

| Engine | Suggested target | Suggested port | Default DB name |
|---|---|---|---|
| PostgreSQL | RDS PostgreSQL 15 single-AZ | 5432 | `postgres` |
| MySQL | RDS MySQL 8 single-AZ | 3306 | `mysql` |
| SQL Server | RDS SQL Server 2022 SE single-AZ | 1433 | `master` |

### 0.3 Per-engine database users

Create a dedicated `fis_runner` database user per engine with the minimum privileges from the README's Real_Mode Prerequisites section. Store each password in Secrets Manager and capture the secret ARN.

### 0.4 Per-engine application fixture tables

In an `appdb` (PostgreSQL/MySQL) or schema (`dbo`, SQL Server) on each instance, create four fixture tables:

```sql
-- Fixture A: single-column PK, 100 rows (PostgreSQL example; adapt per engine)
CREATE TABLE app_orders (id INT PRIMARY KEY, customer_id INT, amount NUMERIC(10,2), notes TEXT);
INSERT INTO app_orders SELECT n, n*7, n*1.25, 'order-' || n FROM generate_series(1, 100) AS n;

-- Fixture B: composite PK, 100 rows
CREATE TABLE app_order_items (order_id INT, line_no INT, sku VARCHAR(20), qty INT, PRIMARY KEY (order_id, line_no));
-- seed 100 rows...

-- Fixture C: no primary key, 100 rows
CREATE TABLE app_no_pk (a INT, b INT);
-- seed 100 rows...

-- Fixture D: empty table with PK
CREATE TABLE app_empty (id INT PRIMARY KEY, payload TEXT);
```

Take a `before` snapshot of A and B per engine (`SELECT * FROM <table> ORDER BY <pk>` written to a file). You will diff this against an `after` snapshot at the end of every Real_Mode test.

### 0.5 Observability scaffolding

- A CloudWatch alarm per engine on the engine-specific blocked-waiter signal documented in the README ("Where to look for the blocked-waiter signal per engine"):
  - **Aurora MySQL / RDS MySQL**: `BlockedTransactions`.
  - **RDS SQL Server**: Performance Insights `db.General Statistics.Processes blocked`.
  - **PostgreSQL**: a custom metric filter on Database Insights or a metric derived from `pg_stat_activity` lock-wait rows.
- Threshold: alarm at `waiters > 3` for ≥1 datapoint of 1 minute. This is the alarm we will validate as a stop condition in Phase 5.

---

## Phase 1 — Synthetic_Mode happy path (per engine)

Goal: confirm the unmodified shipped template works on all three engines, the synthetic table is created/dropped, the blocked-waiter ramp is visible, and the experiment cleans up.

### 1.1 PostgreSQL

Update the FIS template's `documentParameters` to:

```json
{"DatabaseEngine":"postgres","DatabaseEndpoint":"<pg-endpoint>","DatabasePort":"5432","DatabaseName":"postgres","DatabaseUser":"fis_runner","DatabasePasswordSecretArn":"<pg-secret-arn>","WaiterCount":"10","ExperimentDuration":"PT5M","RampTime":"PT2M","RampSteps":"5","VpcId":"<vpc>","SubnetId":"<subnet>","DatabaseSecurityGroupId":"<pg-sg>","InstanceType":"t3.small","TargetTableName":"fis_blocking_locks_target"}
```

Start the experiment from the FIS console. Pass criteria:

- The SSM execution reaches the `InjectBlockingLocks` step within ~5 minutes (Phase 1 + 2 of the README).
- CloudWatch Logs for the SSM step contain `Mode: Synthetic_Mode  TargetTableName: fis_blocking_locks_target` and `Created target table fis_blocking_locks_target (will DROP on exit)`.
- Database Insights lock-tree (or `SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'`) shows the waiter count climbing from 0 to 10 in ~5 steps over `RampTime`, then returning to 0 within ~30 seconds of `ExperimentDuration` elapsing.
- `SELECT 1 FROM information_schema.tables WHERE table_name = 'fis_blocking_locks_target'` returns no rows after the experiment completes.
- The EC2 load-generator instance is in `terminated` state, its security group `FIS-DatabaseBlockingLocks-LoadGen-<exec-id>` is deleted, and the database SG no longer has the temporary ingress rule.
- Harness exit code is 0 (visible in the SSM step output).

### 1.2 MySQL

Same as 1.1 with `DatabaseEngine=mysql`, port `3306`, `DatabaseName=mysql`. Verify the blocked-waiter ramp on the Aurora MySQL `BlockedTransactions` metric (or `SELECT COUNT(*) FROM performance_schema.data_lock_waits` for RDS MySQL).

### 1.3 SQL Server

Same as 1.1 with `DatabaseEngine=sqlserver`, port `1433`, `DatabaseName=master`. Verify the ramp on `db.General Statistics.Processes blocked` in Performance Insights.

---

## Phase 2 — Real_Mode happy path (per engine)

Goal: confirm Real_Mode locks the first row of a real table without modifying it, and that the byte-for-byte equality guarantee holds.

### 2.1 Single-column primary key (per engine)

For each engine, run with `TargetTableName=app_orders` (SQL Server: `dbo.app_orders`), `WaiterCount=5`, `ExperimentDuration=PT5M`, `RampTime=PT1M`, `RampSteps=5`.

Pass criteria:

- CloudWatch Logs contain `Mode: Real_Mode  TargetTableName: app_orders` and `Discovered primary key columns: ['id']` and `Lock SQL: SELECT "id" FROM "app_orders" WHERE "id" = %s FOR UPDATE` (or the engine-specific equivalent).
- Blocked-waiter metric ramps from 0 to 5 over `RampTime`, returns to baseline after `ExperimentDuration`.
- A query while the experiment is in progress confirms the locked row is the first PK row:
  - PostgreSQL: `SELECT pid, query, wait_event FROM pg_stat_activity WHERE wait_event_type = 'Lock'` shows 5 sessions waiting on a `SELECT ... FOR UPDATE` of `app_orders` with `id = 1`.
  - MySQL: `SELECT * FROM performance_schema.data_locks WHERE OBJECT_NAME = 'app_orders' AND LOCK_STATUS = 'WAITING'`.
  - SQL Server: `sp_who2` or `sys.dm_tran_locks` filtered to `app_orders`.
- After the experiment: row count of `app_orders` unchanged. Diff `SELECT * FROM app_orders ORDER BY id` against the `before` snapshot — must be empty (zero differences). No `fis_blocking_locks_target` table exists.
- Harness exit code 0.

### 2.2 Composite primary key (per engine)

Same as 2.1 with `TargetTableName=app_order_items`. Additional pass criteria:

- CloudWatch Logs show `Discovered primary key columns: ['order_id', 'line_no']` and a `Lock SQL` that includes both columns in the `WHERE` clause.
- The lock-wait view (per engine) shows the blocked statement's text references both PK columns.

---

## Phase 3 — Real_Mode error-path validation (per engine)

Goal: confirm every Real_Mode failure mode exits with the documented code, emits the documented diagnostic, and leaves the database unmodified. Use `ExperimentDuration=PT1M` for these — the harness exits well before the ramp begins.

For each engine, run four short experiments and capture the harness exit code from the SSM step output:

| # | `TargetTableName` | DB user setup | Expected exit | Verification |
|---|---|---|---|---|
| 3a | `does_not_exist` | unchanged | **20** | Diagnostic names the table, `DatabaseName`, endpoint, engine, and the underlying driver exception (e.g. `psycopg2.errors.UndefinedTable`). |
| 3b | `app_empty` | unchanged | **21** | Diagnostic names the table and engine, and states "contains zero rows". |
| 3c | `app_no_pk` | unchanged | **23** | Diagnostic names the table and engine, and states "no primary key constraint". |
| 3d | `app_orders` | revoke `SELECT` on `information_schema.table_constraints` (or the SQL Server `sys.indexes` etc.) from `fis_runner` for the duration of this run | **24** | Diagnostic names the table, engine, the metadata views the operator must grant SELECT on, and the underlying driver exception. |

After each run:

- Confirm `SELECT * FROM app_orders ORDER BY id` matches the `before` snapshot from Phase 0.4.
- Confirm `fis_blocking_locks_target` does NOT exist in the target database.
- Confirm the SSM step status reflects the failure (the load-gen EC2 is still terminated and the security group cleaned up).

### 3e — Optional: row-deleted race (exit 25)

This is hard to reproduce reliably because the validation→lock-acquisition window is sub-second. To force it, run the experiment with the SSM step paused (e.g. via a debugger on the harness in a forked test environment) between `_select_target_row` and `_acquire_blocker_lock`, and from a separate session `DELETE FROM app_orders WHERE id = 1; COMMIT;`. Skip if not testing the harness in a debugger; the path is exercised by unit tests.

---

## Phase 4 — SQL Server-specific scenarios

### 4.1 Schema-qualified vs unqualified `TargetTableName`

Run Phase 2.1 twice on RDS SQL Server: once with `TargetTableName=dbo.app_orders`, once with `TargetTableName=app_orders`. Both must succeed with identical CloudWatch Logs (`Real_Mode target: [dbo].[app_orders] (engine=sqlserver)` in both cases) and identical `before`/`after` table equality.

### 4.2 RCSI off (default) — plain `SELECT` is blocked

Confirm RCSI is off:

```sql
SELECT is_read_committed_snapshot_on FROM sys.databases WHERE name = DB_NAME();
-- expect 0
```

Run Phase 2.1 against SQL Server. Concurrently from a separate session, loop a plain `SELECT * FROM dbo.app_orders WHERE id = 1` (no locking hints). Pass criteria:

- The plain `SELECT` blocks while the experiment is in progress.
- The blocked-waiter metric reflects 6 waiters (5 from the harness + 1 from your loop).
- After the experiment, the plain `SELECT` returns the original row unchanged.

### 4.3 RCSI on — plain `SELECT` is NOT blocked

`ALTER DATABASE <db> SET READ_COMMITTED_SNAPSHOT ON` (note the README's caveat about Multi-AZ instances). Re-run 4.2. Pass criteria:

- The plain `SELECT` does NOT block — readings continue at full throughput.
- The blocked-waiter metric reflects exactly 5 waiters (only the harness's locking SELECTs block).
- Restore RCSI to its prior setting after the test.

---

## Phase 5 — Safety control validation

### 5.1 IMDSv2 enforcement on the load-gen EC2

While Phase 1.1 is in progress, SSM-Session-Manager into the load-gen instance and run:

```bash
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-id   # should succeed
curl -s -i http://169.254.169.254/latest/meta-data/instance-id                                      # should return 401
```

Pass criteria: token-less IMDSv1 calls return HTTP 401, confirming the `MetadataOptions: HttpTokens: required` config in the SSM YAML is in effect.

### 5.2 PostgreSQL idle-in-transaction timeout interaction

On the PostgreSQL test instance, set `idle_in_transaction_session_timeout='30000'` (30s) at the parameter-group level for the test database. Run Phase 2.1 with `ExperimentDuration=PT5M`. Pass criteria:

- After ~30 seconds, the harness emits a CloudWatch Logs line of the form `Blocker transaction terminated by server after 30 seconds (engine=postgres). Likely cause: DBA-configured idle-in-transaction timeout.`
- The harness still exits with code 0 (this is documented as expected, not a failure).
- All Waiter threads unblock cleanly.
- Reset the parameter to `0` after the test.

### 5.3 Manual experiment cancellation

Start a Phase 1.1 experiment with `ExperimentDuration=PT30M`. After the ramp completes (~3 minutes in), manually `Stop experiment` from the FIS console. Pass criteria:

- The SSM execution transitions to `Cancelled` within ~2 minutes.
- The load-gen EC2 is terminated.
- The temporary security group is deleted.
- The database SG no longer has the temporary ingress rule.
- The synthetic table is dropped (the cleanup `_drop_table` runs on the way out).
- No orphan ENIs (`aws ec2 describe-network-interfaces --filters Name=status,Values=available` returns nothing tagged `FIS-Experiment=DatabaseBlockingLocks`).

### 5.4 Stop-condition trigger

Edit the FIS template to add the Phase 0.5 alarm as a stop condition. Run Phase 1.1 with `WaiterCount=20`, `RampTime=PT1M`, `RampSteps=10`. The alarm fires at >3 waiters, which the ramp will exceed within ~30 seconds. Pass criteria:

- The experiment auto-stops within ~1 minute of the alarm transitioning to `ALARM`.
- All cleanup steps from 5.3 succeed.

### 5.5 `maxDuration` ceiling

Edit the FIS template to set `maxDuration: PT3M` and run with `ExperimentDuration=PT10M`. Pass criteria:

- The experiment terminates at ~3 minutes regardless of `ExperimentDuration`.
- All cleanup steps succeed.

### 5.6 Wrong-credentials and wrong-endpoint paths

Run Phase 1.1 three times, each with a different deliberately-broken parameter:

| Variant | Broken parameter | Expected harness exit |
|---|---|---|
| 5.6a | `DatabasePasswordSecretArn` set to a non-existent ARN | 2 (Secrets Manager retrieval failed) |
| 5.6b | `DatabaseEndpoint` set to a non-resolvable hostname | 3 (DB connect failed) |
| 5.6c | `DatabaseEngine` set to `oracle` | 4 (unsupported engine) |

For each, confirm the exit code in the SSM step output, confirm CloudWatch Logs contain a clear diagnostic that names the broken parameter, and confirm cleanup still runs (EC2 terminated, SG deleted, no orphan ingress rule).

---

## Phase 6 — Observability validation

### 6.1 Metric shape

Across Phase 1.1, 1.2, 1.3, capture the engine-specific blocked-waiter metric at 1-minute resolution. Pass criteria:

- The metric value at the end of each ramp step is approximately `step_index * (WaiterCount / RampSteps)`.
- The plateau at `WaiterCount` is sustained for `(ExperimentDuration - RampTime)`.
- The metric returns to baseline (≤1) within 60 seconds of `ExperimentDuration` elapsing.

### 6.2 Required log lines

Across all Phase 1 and Phase 2 runs, confirm CloudWatch Logs for the `InjectBlockingLocks` step contain (in order):

- `=== Database Blocking Locks Harness ===`
- `Engine: <engine>`
- `Mode: Synthetic_Mode|Real_Mode  TargetTableName: <name>`
- (Real_Mode only) `Real_Mode target: <quoted_ref> (engine=<engine>)`, `Discovered primary key columns: [...]`, `Lock SQL: ...`
- `Ramp schedule (wait_before_s, waiters_to_start): [...]`
- `Blocker acquired row lock on ... at t=0s; holding for <N>s`
- one `Ramp step <i>/<n>: started <k> waiter(s), total=<m>/<N>` per ramp step
- `Blocker committed; row lock ... released after <N>s`
- `All waiter threads joined cleanly`

### 6.3 Alarm-driven stop condition

Already covered in Phase 5.4.

---

## Phase 7 — Cleanup / regression

After every prior phase:

- Confirm no EC2 instances remain tagged `FIS-Experiment=DatabaseBlockingLocks` and `AutoCleanup=true`.
- Confirm no security groups remain matching `FIS-DatabaseBlockingLocks-LoadGen-*`.
- Confirm the database security group has no leftover ingress rules referencing deleted load-gen SGs.
- Confirm `fis_blocking_locks_target` does not exist in any of the three target databases.
- Run a final Phase 1.1 (Synthetic_Mode happy path) on PostgreSQL as a regression smoke test to confirm a fresh end-to-end run still passes after all the negative-path tests.

Drop fixture tables (`app_orders`, `app_order_items`, `app_no_pk`, `app_empty`) and revert any parameter-group changes (RCSI on SQL Server, `idle_in_transaction_session_timeout` on PostgreSQL).

---

## Reporting matrix

Capture pass/fail per cell and link to the SSM execution ID and FIS experiment ARN:

| Phase | PostgreSQL | MySQL | SQL Server |
|---|---|---|---|
| 1 Synthetic happy | | | |
| 2.1 Real single PK | | | |
| 2.2 Real composite PK | | | |
| 3a–3d Error paths | | | |
| 4.1 Schema-qualified | n/a | n/a | |
| 4.2 RCSI off | n/a | n/a | |
| 4.3 RCSI on | n/a | n/a | |
| 5.1 IMDSv2 | | | |
| 5.2 IIT timeout | | n/a | n/a |
| 5.3 Manual cancel | | | |
| 5.4 Stop condition | | | |
| 5.5 maxDuration | | | |
| 5.6a–c Bad params | | | |
| 6 Observability | | | |
| 7 Cleanup | | | |

Notes you'll want to capture per row: SSM execution ID, harness exit code, before-snapshot diff size (Real_Mode only), peak blocked-waiter metric value, ramp-shape match.

---

## Time and cost rough estimate

- Per-engine pre-test setup: ~30 minutes once.
- Synthetic happy path per engine: ~10 minutes (5 minute experiment + 5 minute pre/post).
- Real_Mode happy paths per engine: ~30 minutes (×2 scenarios + diffs).
- Error paths per engine: ~20 minutes.
- SQL Server extras: ~30 minutes.
- Phase 5 safety controls: ~60 minutes.
- Phase 6 observability and Phase 7 cleanup: ~30 minutes.

Total: roughly half a day to a full day of operator time per engine if executed serially, plus the underlying RDS instance time. Run engines in parallel from separate FIS templates if you want to compress wall-clock time.
