# AWS Fault Injection Service Experiment: Database Blocking Locks

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## What This Experiment Is For

This experiment is best suited to rehearsing **detection and diagnosis** of row-level lock contention: validating that your DBA team can find the offending session, and that your runbook for "a transaction is holding a row lock too long" works under prod-like conditions. The two modes target different parts of that story. **Synthetic_Mode** locks an experiment-owned row in a experiment created table that no application reads or writes, so it produces a clean engine-side signal with effectively zero real impact — ideal for repeatable detection rehearsal. **Real_Mode** locks the first row of a user-supplied application table, so it *potentially* produces real impact scoped to whatever code paths touch that row — useful when you also need to validate application-side behaviour like connection-pool sizing, retry logic, and upstream timeouts under contention.

What this experiment is **not** well suited to is producing a wide, system-saturating outage. Locking a single row is a narrow fault by construction: even in Real_Mode, the impact is bounded by which code paths query the locked row, and on PostgreSQL/MySQL plain `SELECT` traffic is unaffected by MVCC (Multi-Version Concurrency Control - prevents readers and writers waiting on each other). If your goal is "validate that the system survives a wide database problem," the [`database-connection-limit-exhaustion`](../database-connection-limit-exhaustion/README.md) experiment is a more direct lever — it saturates `max_connections` and immediately affects every code path that opens a database connection. Use this experiment when your hypothesis is specifically about lock contention; use connection exhaustion when your hypothesis is about wide database degradation.

## Example Hypotheses

When the {service1} database is subjected to synthetic row-level blocking locks an alarm should be raised and the DevOps team should be notified within {x} minutes. The team should be able to respond to the cause within {y} minutes via the engine-specific blocked-waiter metric. Critical user journeys relating to {workload} should continue unaffected.

When the {service1} database is subjected to directed row-level blocking locks an alarm should be raised and the DevOps team should be notified within {x} minutes. The team should be able to respond to the cause within {y} minutes via the engine-specific blocked-waiter metric. Critical user journeys relating to {workload} should/shouldn't be impacted in {manner of impact}.

#### Engine specific CloudWatch metrics:
* Aurora MySQL / RDS MySQL: `db.Locks.innodb_row_lock_waits.avg` (cumulative count of row-lock waits — climbs while the experiment runs) and `db.Locks.innodb_lock_timeouts.avg` (count of `ERROR 1205` aborts — the "Waiters being killed" signal). Both alarmable via `DB_PERF_INSIGHTS('RDS', '<resource_id>', '<metric>')`. Supplement with application-side `1205 (HY000) Lock wait timeout exceeded` error rate. Aurora MySQL `BlockedTransactions` is bursty under default `innodb_lock_wait_timeout` (50 s) and not the right primary signal — see the MySQL-specific note in the Observability section.
* RDS SQL Server: `db.General Statistics.Processes blocked.avg`, alarmable via `DB_PERF_INSIGHTS('RDS', '<resource_id>', 'db.General Statistics.Processes blocked.avg')`.
* Aurora PostgreSQL and RDS PostgreSQL: the `Lock:Tuple` (and `Lock:transactionid`) wait events on the Performance Insights Database Insights / Datasbe load / Slicde by Waits (visible in the Performance Insights UI but not exposed via `DB_PERF_INSIGHTS` in metric math). The CloudWatch-alarmable path is to enable `log_lock_waits=on` in the DB instance parameter group, ship the engine log to CloudWatch Logs, and put a metric filter for the string `still waiting for`.

### What does this enable me to verify?

* Appropriate customer experience metrics and observability of your database are in place (were you able to detect the blocked-waiter signal as it climbed with the Waiter ramp?)
* Alarms are configured correctly on the engine-specific blocked-waiter metric (were the right people notified at the right time and/or automations triggered?)
* Your application gracefully handles transactions that block on contended rows (retries, timeouts, circuit breakers)
* Recovery controls (if any) work as expected
* Your application recovers once the blocks are released

## Description

This experiment tests your application's resilience to database row-level lock contention by:

1. **Dynamically creating** an ephemeral EC2 instance as a load generator
2. **Bootstrapping** the instance with the appropriate database client (PostgreSQL, MySQL, or SQL Server)
3. **Opening one Blocker session** that holds a row-level lock on a dedicated `fis_blocking_locks_target` table for the full `ExperimentDuration`
4. **Ramping in `WaiterCount` Waiter sessions** over `RampTime` across `RampSteps` evenly spaced steps, where each Waiter opens a connection, begins a transaction, and issues the same engine-native row-level locking `SELECT` against the Blocker-held row so that it shows up as a blocked transaction on the database
5. **Cleaning up** by committing the Blocker, joining Waiter threads, dropping the target table if this run created it, terminating the load generator, and removing the ephemeral security-group rules

The experiment is **parameterized by database engine**, making it reusable across engines in RDS:
- Aurora PostgreSQL
- Aurora MySQL
- RDS PostgreSQL
- RDS MySQL
- RDS SQL Server

When you run this experiment you will see the engine-specific blocked-waiter metric for your database climb in stepped increments that track the Waiter ramp, then return to baseline once the Blocker COMMITs.

## Architecture Overview

```
FIS Experiment
    ↓
SSM Automation Document
    ↓
1. Create temporary security group in VPC
    ↓
2. Add egress rule: Load generator → Database port
    ↓
3. Add ingress rule: Database SG ← Load generator SG
    ↓
4. Launch EC2 instance (Amazon Linux 2023) with new SG
    ↓
5. Wait for SSM Agent to be online
    ↓
6. Install database client (psql/mysql/sqlcmd)
    ↓
7. Execute InjectBlockingLocks harness
    ↓
8. Blocker acquires row lock; Waiters ramp in and block
    ↓
9. ExperimentDuration elapses; Blocker COMMITs; Waiters unblock
    ↓
10. Drop target table (if this run created it)
    ↓
11. Terminate EC2 instance
    ↓
12. Remove ingress rule from database SG
    ↓
13. Delete temporary security group
```

## Prerequisites

Before running this experiment, ensure that:

1. **VPC Configuration**:
   - You have a VPC with at least one subnet that can reach your database
   - You know the VPC ID and subnet ID
   - You know the security group ID attached to your database

2. **Database Configuration**:
   - Supported database is running (Aurora PostgreSQL, Aurora MySQL, RDS PostgreSQL, RDS MySQL, or RDS SQL Server)
   - You know the database endpoint, username, and port
   - **You have a user-created database the harness can create tables in, and you know its name.** Synthetic_Mode creates the `fis_blocking_locks_target` table on startup and drops it on shutdown, so the database identified by `DatabaseName` must allow `CREATE TABLE` / `INSERT` / `UPDATE` / `DROP TABLE` from the user identified by `DatabaseUser`. The default system databases shipped with each engine are **not** suitable targets.
   - You have stored the database password as an AWS Secrets Manager secret and know its ARN. The secret can be either a raw string or a JSON document with a `password` key (the shape used by the RDS-managed master password secret).
   - **Instance class for Performance Insights-based monitoring**: if you intend to alarm via the `DB_PERF_INSIGHTS` metric math function on counters such as `db.Locks.innodb_row_lock_waits.avg` (Aurora MySQL / RDS MySQL) or `db.General Statistics.Processes blocked.avg` (RDS SQL Server), Performance Insights must be enabled on the instance, and Performance Insights does not support burstable classes (`db.t2.*`, `db.t3.*`, `db.t4g.*`). The experiment itself runs on any supported instance class — only the alarm path is constrained. On a burstable class you can still observe the engine's Database Insights graphs and use application-side error rates (for example a CloudWatch Logs metric filter on `Lock wait timeout exceeded`) for alerting.

### Create Required Experiment Resources

1. **Experiment template**:
   - Import the FIS experiment template (`database-blocking-locks-template.json`) into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).

2. **IAM Roles**: Create the following IAM roles in your account using the sample policies provided:
   - FIS execution role (`DatabaseBlockingLocks-FIS-Role`) with permissions to start SSM automation
   - SSM automation role (`DatabaseBlockingLocks-SSM-Automation-Role`) with permissions to launch EC2 instances, execute commands, read the database password from Secrets Manager, and manage the ephemeral security group
   - EC2 instance profile (`SSM-Managed-Instance-Profile`) with the `AmazonSSMManagedInstanceCore` managed policy attached

3. **SSM Document**:
   - Deploy the SSM automation document (`database-blocking-locks-automation.yaml`) to your account

### Real_Mode Prerequisites

The following additional prerequisites apply **only when running in Real_Mode** (Real_Mode is enabled, when `TargetTableName` is set to **any value other than the default** `fis_blocking_locks_target`). Synthetic_Mode runs do not require any of the items in this subsection because the harness creates and owns the synthetic table itself.

1. Target table exists and is reachable from the database user.
2. Target table has at least one row.
3. Target table has a primary key.
4. The database user has `SELECT` on the target table AND on the engine-appropriate metadata views. The `DatabaseUser` identified in the experiment parameters must have:
   - `SELECT` on the target table (required to run the existence and non-empty probes and to select the target row's primary key values).
   - `SELECT` on `information_schema.table_constraints` and `information_schema.key_column_usage` for PostgreSQL and MySQL (required for primary-key introspection).
   - `SELECT` on `sys.indexes`, `sys.index_columns`, and `sys.columns` for SQL Server (required for primary-key introspection).

   These are database-side privileges configured on the database user, not AWS IAM permissions; the FIS and SSM IAM policies shipped with this template are unchanged by Real_Mode.

## Parameters

The experiment requires the following parameters:

### Database Configuration
- **DatabaseEngine**: `postgres`, `mysql`, or `sqlserver` (default: `postgres`)
- **DatabaseEndpoint**: Database DNS hostname or endpoint
- **DatabasePort**: Database port (default: 5432 for PostgreSQL, 3306 for MySQL, 1433 for SQL Server)
- **DatabaseName**: User-created database the harness connects to. The harness creates the synthetic `fis_blocking_locks_target` table inside this database (Synthetic_Mode) or expects to find the user-supplied target table inside it (Real_Mode), so the database user identified by `DatabaseUser` needs CREATE / INSERT / UPDATE / SELECT / DROP on it.
- **DatabaseUser**: Database username (default: `postgres`)
- **DatabasePasswordSecretArn**: ARN of Secrets Manager secret containing password
  - **Note** Since we don't know the ARN of your secret ahead of time, the sample SSM automation role ([database-blocking-locks-ssm-automation-role-iam-policy.json](database-blocking-locks-ssm-automation-role-iam-policy.json)) is given read access to all secrets, you should probably scope this down accordingly.
- **TargetTableName**: `String`. Default: `fis_blocking_locks_target`. Selects the table the harness operates against and, by extension, the experiment mode:
  - **WARNING**: Real_Mode causes **actual application impact**. Any application transaction that contends for the locked row will block for up to `ExperimentDuration`. Only set `TargetTableName` to a non-default value when you have intentionally opted into targeting a real application table and have understood the blast radius for your engine (see the Engine-Specific Blast Radius section).
  - **SQL Server** accepts schema-qualified (`dbo.orders`) or unqualified (`orders`, defaulting to `dbo`) names.
- **WaiterCount**: Total number of Waiter sessions to ramp up against the Blocker-held row (default: 50). Each currently-blocked Waiter contributes approximately 1 to the engine-specific blocked-waiter count.
- **ExperimentDuration**: Total experiment duration in ISO8601 format (default: PT10M = 10 minutes, e.g., PT1H = 1 hour, PT30M = 30 minutes). **This parameter controls how long the Blocker session holds the row lock.**
  - **Note** this is not the same as the FIS Experiment Template Max Duration (default 3 hours for this experiment template) which functions as an overarching timeout.
- **RampTime**: Time to gradually ramp up to `WaiterCount` in ISO8601 format (default: PT1M = 1 minute, e.g., PT30S = 30 seconds, PT2M = 2 minutes, PT0S = immediate)
- **RampSteps**: Number of steps to reach `WaiterCount` (default: 10, e.g., 2=50% then 100%, 10=10% increments)
- **VpcId**: VPC ID where the load generator will be launched (used to create security group)
- **SubnetId**: Subnet ID where the load generator will be launched
- **DatabaseSecurityGroupId**: Security group ID of the target database (automation will add temporary ingress rule)
- **InstanceType**: EC2 instance type for the load generator (default: `t3.small` - consider larger for very high Waiter counts or sustained experiments)

## Executing the Experiment
- Once the FIS Experiment template is deployed in your account, you will need to **update the experiment template** by editing it in the console or via the API to set appropriate parameters for your desired database target and environment
- To update via the console:
  1. Open the FIS Console
  2. Select the experiment template tagged `Name: database-blocking-locks`
  3. Select **Actions / Update Experiment Template**
  4. Select the **InjectBlockingLocks** Action
  5. Update the **Document parameters** to match your target. Synthetic_Mode example (the safe default — `TargetTableName` is left at `fis_blocking_locks_target`, the harness creates and drops its own table): `{"DatabaseEngine":"postgres","DatabaseEndpoint":"database-1.cluster-1234abcde.eu-west-1.rds.amazonaws.com","DatabasePort":"5432","DatabaseName":"fis_test","DatabaseUser":"postgres","DatabasePasswordSecretArn":"arn:aws:secretsmanager:eu-west-1:123456789012:secret:rds!cluster-xxxx-yyyy-zzzz","WaiterCount":"50","ExperimentDuration":"PT30M","RampTime":"PT10M","RampSteps":"10","VpcId":"vpc-1234567abcd","SubnetId":"subnet-1234-abcdef","DatabaseSecurityGroupId":"sg-1234567abcd","InstanceType":"t3.small","TargetTableName":"fis_blocking_locks_target"}` — note that `DatabaseName` points at a **user-created** database (here `fis_test`); see the Database Configuration prerequisite for why the engine-shipped system databases (`mysql`, `master`) are not appropriate. For a Real_Mode example see "Example: Real_Mode `documentParameters`" below.
  6. **Note** there is no target defined in the FIS experiment template since this is managed through the SSM Automation document and the Document parameters you just entered, so **do not amend the target section of the template**
  7. Select **Save** and then **Update experiment template**
  8. You can now **Start experiment**

### Example: Real_Mode `documentParameters`

To run the experiment in Real_Mode, set `TargetTableName` to the name of an application table you want to target. The harness will introspect that table's primary key, select the first row ordered by primary key, and acquire a row-level lock against that row using a read-only locking SELECT. Replace `application_orders` with the name of the application table you intend to target:

```json
{"DatabaseEngine":"postgres","DatabaseEndpoint":"database-1.cluster-1234abcde.eu-west-1.rds.amazonaws.com","DatabasePort":"5432","DatabaseName":"appdb","DatabaseUser":"fis_runner","DatabasePasswordSecretArn":"arn:aws:secretsmanager:eu-west-1:123456789012:secret:fis/db-password-xxxxxx","TargetTableName":"application_orders","WaiterCount":"50","ExperimentDuration":"PT30M","RampTime":"PT10M","RampSteps":"10","VpcId":"vpc-1234567abcd","SubnetId":"subnet-1234-abcdef","DatabaseSecurityGroupId":"sg-1234567abcd","InstanceType":"t3.small"}
```

For SQL Server, `TargetTableName` accepts schema-qualified (`dbo.application_orders`) or unqualified (`application_orders`, defaulting to `dbo`) names. Before setting `TargetTableName` to a non-default value, confirm the target table satisfies the items in the Real_Mode Prerequisites subsection above and review the Engine-Specific Blast Radius section.

### Real_Mode safety posture

Real_Mode never executes `INSERT`, `UPDATE`, `DELETE`, or DDL (`CREATE`, `ALTER`, `DROP`, `TRUNCATE`, `MERGE`) against the target table. Both the Blocker and every Waiter acquire row locks using read-only locking statements only — `SELECT ... FOR UPDATE` on PostgreSQL and MySQL, or `SELECT ... WITH (UPDLOCK, HOLDLOCK)` on SQL Server — against the row identified by the primary key values selected at pre-flight time. After the experiment completes (whether normally or via early termination), the target table contains exactly the same rows with the same column values as before the experiment started: zero rows are inserted, zero rows are updated, zero rows are deleted, and the table's schema is unchanged. The only effect on the target table is transient row-level lock contention against the selected row for the duration of the experiment; once the Blocker COMMITs and the Waiters unblock, the contention disappears and the table is byte-for-byte equivalent to its pre-experiment state.

## How It Works

### Phase 1: Infrastructure Creation (2-3 minutes)
1. Creates a temporary security group in your VPC with name `FIS-DatabaseBlockingLocks-LoadGen-<execution-id>`
2. Adds egress rule allowing traffic from the load generator to the database port
3. Adds ingress rule to the database security group allowing traffic from the load generator
4. Launches an EC2 instance in your specified subnet with the new security group
5. Instance and security group are tagged with `FIS-Experiment=DatabaseBlockingLocks`, `AutoCleanup=true`, and `ManagedBy=FIS-SSM-Automation`
6. Waits for SSM Agent to report online status

### Phase 2: Bootstrap (1-2 minutes)
7. Installs the appropriate database client and Python driver based on the `DatabaseEngine` parameter:
   - `postgres`: PostgreSQL 15 client and `psycopg2-binary`
   - `mysql`: MariaDB client (MySQL-compatible) and `mysql-connector-python`
   - `sqlserver`: Microsoft ODBC Driver 18 for SQL Server, `mssql-tools18`, and `pyodbc`

### Phase 3: Blocker Acquires Row Lock
8. The harness retrieves the database password from Secrets Manager (the secret can be a raw string or a JSON document with a `password` key).
9. The harness opens a short-lived control connection. The behaviour from this point depends on the value of `TargetTableName`:
   - **Synthetic_Mode** (`TargetTableName == fis_blocking_locks_target`, the default): if the table does not already exist, the harness creates it with an `id INT PRIMARY KEY` column and a `counter INT` column and seeds row `id = 1`. The harness records whether this run created the table so cleanup only drops the table if this run created it.
   - **Real_Mode** (any other value): the harness validates that the user-supplied table exists and is non-empty, introspects its primary key via engine-native metadata views (`information_schema.table_constraints` + `information_schema.key_column_usage` for PostgreSQL/MySQL, or `sys.indexes` + `sys.index_columns` + `sys.columns` for SQL Server), and selects the primary-key values of the first row ordered by primary key ascending. The harness performs no DDL or DML writes against the user-supplied table.
10. The harness opens exactly one Blocker session, begins a transaction, and acquires the row lock using the engine-native idiom:
    - PostgreSQL and MySQL: `SELECT <pk_cols> FROM <table> WHERE <pk_clause> FOR UPDATE`
    - SQL Server: `SELECT <pk_cols> FROM <qualified_table> WITH (UPDLOCK, HOLDLOCK) WHERE <pk_clause>`

    In Synthetic_Mode `<pk_cols>` is `id`, `<table>` is `fis_blocking_locks_target` (or `dbo.fis_blocking_locks_target`), and `<pk_clause>` is `id = 1`. In Real_Mode `<pk_cols>`, `<table>`, and `<pk_clause>` are derived from the target table's primary key discovered at pre-flight time, with the primary-key values bound as driver parameters.
11. The Blocker holds its transaction open for `ExperimentDuration` using a Python **in-process sleep**, not a database-side sleep function such as `pg_sleep`, `SLEEP`, or `WAITFOR DELAY`. This keeps the lock-hold period from being subject to database statement-level timeouts, and lets cancellation take effect immediately when the EC2 instance is terminated.

### Phase 4: Waiter Ramp (Duration: RampTime)
12. While the Blocker is holding the row lock, the harness computes the Waiter ramp schedule:
    - `effective_ramp_steps = min(RampSteps, WaiterCount)`
    - If `RampTime` is greater than `ExperimentDuration`, `RampTime` is clamped to `ExperimentDuration` and the adjustment is logged.
    - If `RampTime` is `PT0S`, all `WaiterCount` Waiters are started immediately in a single step.
    - Otherwise `WaiterCount` is spread evenly across `effective_ramp_steps`, with any remainder added to the final step so the total number of Waiters started equals `WaiterCount`.
13. For each step, the harness spawns the step's share of Waiter threads. Each Waiter:
    1. Opens a new database connection
    2. Begins an explicit transaction
    3. Issues the same engine-native locking `SELECT` the Blocker used (see Phase 3 step 10), bound to the same primary-key values
    4. Blocks on the Blocker's row lock
14. Example: `WaiterCount=50`, `RampTime=PT1M`, `RampSteps=10` produces 10 steps of 5 Waiters each, roughly 6 seconds apart, so the engine-specific blocked-waiter metric climbs in ten 5-unit increments.

### Phase 5: Cleanup
15. When `ExperimentDuration` elapses, the Blocker COMMITs and closes its connection.
16. Every Waiter's blocked locking `SELECT` returns, the Waiter COMMITs, and the Waiter closes its connection.
17. The harness joins all Waiter threads.
18. If this run created the `fis_blocking_locks_target` table, the harness drops it. If a pre-existing matching table was reused, the harness leaves it in place.
19. The automation terminates the EC2 instance, waits for termination to complete, revokes the ingress rule from the database security group, and deletes the ephemeral security group.

## Engine-Specific Blast Radius

The set of application statements that block on the locked row depends on the database engine and, for SQL Server, on the configured isolation level. This section is most relevant when running in Real_Mode against an application table, where any application transaction that contends for the locked row will block for up to `ExperimentDuration`. Synthetic_Mode operates against an experiment-owned table that no application reads or writes, so the engine-specific blast radius described here is invisible to your workload.

### PostgreSQL (Aurora PostgreSQL and RDS PostgreSQL)

PostgreSQL uses MVCC. While the Blocker holds the row lock the following statements against the locked row block:

- `UPDATE`, `DELETE`
- `SELECT ... FOR UPDATE`, `SELECT ... FOR NO KEY UPDATE`, `SELECT ... FOR SHARE`, `SELECT ... FOR KEY SHARE`

Plain `SELECT` statements (without `FOR UPDATE`/`FOR SHARE`) are **not** blocked.

### MySQL/InnoDB (Aurora MySQL and RDS MySQL)

MySQL with the default InnoDB engine also uses MVCC. While the Blocker holds the row lock the following statements against the locked row block:

- `UPDATE`, `DELETE`
- `SELECT ... FOR UPDATE`, `SELECT ... FOR SHARE` (and the legacy `LOCK IN SHARE MODE`)

Plain `SELECT` statements are **not** blocked.

### SQL Server (RDS SQL Server)

SQL Server's blast radius depends on whether **Read Committed Snapshot Isolation (RCSI)** is enabled.

- **RCSI off (default)**: plain `SELECT`, `UPDATE`, and `DELETE` against the locked row all block, because readers acquire shared locks that conflict with the Blocker's exclusive lock. This is a wider blast radius than PostgreSQL or MySQL.
- **RCSI on**: plain `SELECT` is **not** blocked (uses row versioning). `UPDATE`, `DELETE`, and locking reads (`SELECT ... WITH (UPDLOCK)`, etc.) still block.

RCSI is OFF by default on RDS SQL Server. Enabling it on Multi-AZ deployments may require additional steps because of availability-group constraints.

Check the current RCSI setting before running Real_Mode against SQL Server:

```sql
SELECT name, snapshot_isolation_state_desc, is_read_committed_snapshot_on
FROM sys.databases
WHERE name = DB_NAME();
```

`is_read_committed_snapshot_on = 1` means RCSI is on (plain `SELECT` not blocked); `0` means it is off (plain `SELECT` is blocked).

## Stop Conditions

The experiment template does not have any specific stop conditions defined by default. It will continue to run until:
- All actions complete successfully or one fails
- Manually stopped via FIS console/API
- A custom CloudWatch alarm triggers (if configured)

## Observability and Stop Conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

#### MySQL-specific note: why the signal is bursty, not flat

On MySQL, `innodb_lock_wait_timeout` (default 50 s) only applies to transactions waiting *to acquire* a lock; it does **not** bound the holder. So the production failure mode is: one transaction holds a row lock indefinitely, application transactions trying to update the row each wait up to 50 s and are aborted with `ERROR 1205`, the application either retries or fails the user request, and a steady stream of new transactions keeps arriving and being aborted. A point-in-time gauge like `BlockedTransactions` therefore stays low even though contention is sustained and customer-visible. The cumulative `Innodb_row_lock_waits` counter and the application-side 1205 error rate both reflect the rate of aborts and are the right operational signals.

#### MySQL-specific parameter sizing

The harness creates each Waiter once and does not replenish it after the engine aborts it at `innodb_lock_wait_timeout` (default 50 s). On MySQL this means the standard "ramp Waiters then watch them sit" model from PostgreSQL and SQL Server doesn't apply: every Waiter you create dies once at ~50 s after its start and is gone. To produce sustained, realistic contention signal across the full `ExperimentDuration` you need to size two parameters together:

- **`RampTime = ExperimentDuration`.** Spread Waiter creation evenly across the experiment so new Waiters are still being created late into the run, rather than ramping all of them in the first few minutes and then having no Waiters left to abort.
- **`WaiterCount` and `RampSteps` chosen so each step still contains enough Waiters to register on the metric.** A useful rule of thumb is `WaiterCount / RampSteps ≥ 5` and `RampSteps × 50s ≈ ExperimentDuration` so the per-step Waiter cohort starts, waits ~50 s, is aborted with `ERROR 1205`, and the next cohort arrives shortly after — keeping the cumulative `db.Locks.innodb_row_lock_waits.avg` and `db.Locks.innodb_lock_timeouts.avg` counters climbing for the entire experiment. For example: `ExperimentDuration=PT10M`, `RampTime=PT10M`, `RampSteps=12`, `WaiterCount=120` produces 12 cohorts of 10 Waiters spaced ~50 s apart.

## DBA Guardrails and Pre-flight Check

The most common reason the Blocker's lock is released before `ExperimentDuration` elapses is a DBA-configured idle-transaction timeout which is a useful guardrail against the conditions being generated in this experiment.

- **Aurora PostgreSQL and RDS PostgreSQL**: `idle_in_transaction_session_timeout`, if set to a value shorter than `ExperimentDuration`, will cause the target database to terminate the Blocker's idle transaction early. This rolls back the lock and releases all Waiters before the planned duration elapses.
- **Aurora MySQL and RDS MySQL**: `max_execution_time` only applies to individual `SELECT` statements under READ COMMITTED. Under the in-process-sleep approach used by this harness, no long-running statement runs while the lock is held, so `max_execution_time` is **not** expected to affect the Blocker. This is noted for completeness so that operators are not surprised if they see the parameter in their DB parameter group.
- **RDS SQL Server**: has no parameter analogous to `idle_in_transaction_session_timeout`; open transactions are not subject to idle timeouts by default.

## Leftover Table Side Effect

In **Synthetic_Mode** the harness creates a dedicated `fis_blocking_locks_target` table in the target database on startup if it does not already exist, and drops it on clean shutdown. If the harness is terminated in a way that bypasses its cleanup (for example a hard kill of the SSM created EC2 instance (load generator) without graceful shutdown, or a process crash between the Blocker COMMIT and the DROP TABLE), the `fis_blocking_locks_target` table may be left behind in the target database.

To remove a leftover table:

```sql
DROP TABLE fis_blocking_locks_target;
```

(On SQL Server use `DROP TABLE dbo.fis_blocking_locks_target;`.)

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. **Start Small**: Begin with a small `WaiterCount` (for example 10) to confirm the blocked-waiter signal appears on the engine-specific metric you expect, before scaling up.
2. **Use Gradual Ramp-Up**: Set a non-zero `RampTime` and a meaningful `RampSteps` (for example `RampTime=PT5M`, `RampSteps=10`) so that the blocked-waiter metric climbs in visible increments.
3. **Create a CloudWatch Alarm on the Blocked-Waiter Signal**: Build a CloudWatch alarm on the engine-specific signal documented in the "Engine specific CloudWatch metrics" section near the top of this README — `db.Locks.innodb_row_lock_waits.avg` and/or `db.Locks.innodb_lock_timeouts.avg` on Aurora MySQL / RDS MySQL (alarmable via `DB_PERF_INSIGHTS`); `db.General Statistics.Processes blocked.avg` on RDS SQL Server (also `DB_PERF_INSIGHTS`); or, on Aurora PostgreSQL / RDS PostgreSQL, a CloudWatch Logs metric filter on the `still waiting for` substring after enabling `log_lock_waits = on` and publishing the PostgreSQL log to CloudWatch Logs. **Do not alarm on Aurora MySQL `BlockedTransactions`** — under default `innodb_lock_wait_timeout` it is a bursty point-in-time gauge that will not plateau (see the "MySQL-specific note" below).
4. **Add the Alarm as an FIS Stop Condition**: Attach that alarm as a `stopConditions` entry on the FIS experiment template so the experiment auto-halts if the blocked-waiter count exceeds a threshold that would be unsafe in your environment.
5. **Run the DBA Pre-flight Check**: Before running against any shared database, confirm the engine's idle-transaction timeout is unset, zero, or greater than `ExperimentDuration`:

   ```sql
   -- Aurora PostgreSQL / RDS PostgreSQL
   SHOW idle_in_transaction_session_timeout;

   -- Aurora MySQL / RDS MySQL (informational; does not affect this harness)
   SHOW VARIABLES LIKE 'max_execution_time';
   ```

   For PostgreSQL, a value of `0` means "no timeout"; any non-zero value less than `ExperimentDuration` (in milliseconds) will cause the Blocker's idle transaction to be terminated early. RDS SQL Server has no equivalent setting. See the "DBA Guardrails and Pre-flight Check" section above for the full per-engine details.
6. **Monitor Cleanup**: Verify that the EC2 instance is terminated, the ephemeral security group is deleted, and the `fis_blocking_locks_target` table is gone (if this run created it) after the experiment.

## Import Experiment

To import the experiment template into your AWS account, follow the step-by-step instructions in the [fis-template-library-tooling](https://github.com/aws-samples/fis-template-library-tooling) repository, which supports both AWS CLI and AWS CDK based deployment.
