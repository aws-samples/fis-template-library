# AWS Fault Injection Service Experiment: Database Blocking Locks

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## What This Experiment Is For

This experiment is best suited to rehearsing **detection and diagnosis** of row-level lock contention: validating that your blocked-waiter alarms fire fast enough, that your DBA team can find the offending session, and that your runbook for "a transaction is holding a row lock too long" works under prod-like conditions. The two modes target different parts of that story. **Synthetic_Mode** locks an experiment-owned row that no application reads or writes, so it produces a clean engine-side signal with effectively zero customer impact — ideal for repeatable detection rehearsal. **Real_Mode** locks the first row of a user-supplied application table, so it potentially produces real customer impact scoped to whatever code paths touch that row — useful when you also need to validate application-side behaviour like connection-pool sizing, retry logic, and upstream timeouts under contention.

What this experiment is **not** well suited to is producing a wide, system-saturating outage. Locking a single row is a narrow fault by construction: even in Real_Mode, the impact is bounded by which code paths query the locked row, and on PostgreSQL/MySQL plain `SELECT` traffic is unaffected by MVCC. If your goal is "validate that the system survives a wide database problem," the [`database-connection-limit-exhaustion`](../database-connection-limit-exhaustion/README.md) experiment is a more direct lever — it saturates `max_connections` and immediately affects every code path that opens a database connection. Use this experiment when your hypothesis is specifically about lock contention; use connection exhaustion when your hypothesis is about wide database degradation.

| Dimension | `database-connection-limit-exhaustion` | `database-blocking-locks` Synthetic_Mode | `database-blocking-locks` Real_Mode |
| --- | --- | --- | --- |
| **System-wide impact** | Yes, by construction | No — synthetic table is application-invisible | Only for paths touching the locked row |
| **Customer-visible signal** | Strong: requests fail at the connection layer | None directly; only via your monitoring | Real, scoped to the affected row |
| **What it actually tests** | Detection, impact, recovery, cascading effects | Detection and recovery of metrics, only | Detection and impact (scoped) and recovery, plus your guardrails |
| **Risk to production** | High (saturates pooled resources) | Effectively zero | Real but predictable; under operator control |
| **Repeatability against unknown environments** | Easy (no schema knowledge needed) | Easy | Requires picking a target table and accepting the impact |

## Example Hypotheses

When the {service1} database is subjected to synthetic row-level blocking locks the operations an alarm should be raised and the DevOps team should be notified within {x} minutes. The teams should be able to detect and respond to the cause within {y} minutes via the engine-specific blocked-waiter metric. Critical user journeys relating to {workload} should continue unaffected.

When the {service1} database is subjected to directed row-level blocking locks the operations an alarm should be raised and the DevOps team should be notified within {x} minutes. The teams should be able to detect and respond to the cause within {y} minutes via the engine-specific blocked-waiter metric. Critical user journeys relating to {workload} should/shouldn't be impacted in {manner of impact}.

#### Engine specific metrics:
* Aurora MySQL / RDS MySQL: `db.Locks.innodb_row_lock_waits.avg` (cumulative count of row-lock waits — climbs while the experiment runs) and `db.Locks.innodb_lock_timeouts.avg` (count of `ERROR 1205` aborts — the "Waiters being killed" signal). Both alarmable via `DB_PERF_INSIGHTS('RDS', '<id>', '<metric>')`. Supplement with application-side `1205 (HY000) Lock wait timeout exceeded` error rate. Aurora MySQL `BlockedTransactions` is bursty under default `innodb_lock_wait_timeout` (50 s) and not the right primary signal — see the MySQL-specific note in the Observability section.
* RDS SQL Server `db.General Statistics.Processes blocked`
* Aurora PostgreSQL and RDS PostgreSQL: the `Lock:Tuple` (and `Lock:transactionid`) wait events on the Performance Insights Database load chart

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
   - You have a user database the master user can create tables in, and you know its name. RDS does not auto-create one for MySQL, and the system schemas (`mysql` on RDS MySQL, `master` on RDS SQL Server) are not suitable targets — RDS revokes DDL on `mysql`, and `master` is reserved for engine metadata. If you don't have an application database, create one once with `CREATE DATABASE fis_test;` and pass its name as `DatabaseName`.
   - You have stored the database password as an AWS Secrets Manager secret and know its ARN. The secret can be either a raw string or a JSON document with a `password` key (the shape used by the RDS-managed master password secret).
   - **Instance class for Performance Insights-based monitoring**: if you intend to alarm via the `DB_PERF_INSIGHTS` metric math function on counters such as `db.Locks.innodb_row_lock_waits.avg` (Aurora MySQL / RDS MySQL) or `db.General Statistics.Processes blocked.avg` (RDS SQL Server), Performance Insights must be enabled on the instance, and Performance Insights does not support burstable classes (`db.t2.*`, `db.t3.*`, `db.t4g.*`). The experiment itself runs on any supported instance class — only the alarm path is constrained. On a burstable class you can still observe the engine's Database Insights graphs and use application-side error rates (for example a CloudWatch Logs metric filter on `Lock wait timeout exceeded`) for alerting; choose a non-burstable class (for example `db.r6g.large` or larger) only if you specifically need `DB_PERF_INSIGHTS`-driven alarms.

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

The following additional prerequisites apply **only when running in Real_Mode** (that is, when `TargetTableName` is set to any value other than the default `fis_blocking_locks_target`). Synthetic_Mode runs do not require any of the items in this subsection because the harness creates and owns the synthetic table itself.

1. **Target table exists and is reachable from the database user.** The table named by `TargetTableName` must already exist in the database identified by `DatabaseName` and must be reachable from the connection opened with `DatabaseUser`. The harness does not create the target table in Real_Mode. SQL Server accepts schema-qualified (`dbo.orders`) or unqualified (`orders`, defaulting to `dbo`) names; PostgreSQL and MySQL resolve `TargetTableName` against the connection's current database/schema.
2. **Target table has at least one row.** The harness selects the first row's primary key values (ordered by primary key ascending) and uses those values to acquire a row-level lock. A table with zero rows cannot be targeted; the harness will exit with a non-zero status code if the table is empty at validation time.
3. **Target table has a primary key.** The harness discovers the primary key column(s) via metadata views and uses those columns in the lock-acquisition `WHERE` clause. A table with no primary key constraint cannot be targeted; the harness will exit with a non-zero status code in that case. Composite primary keys (multiple columns) are supported — all columns are used in their defined ordinal position.
4. **The database user has `SELECT` on the target table AND on the engine-appropriate metadata views.** The `DatabaseUser` identified in the experiment parameters must have:
   - `SELECT` on the target table (required to run the existence and non-empty probes and to select the target row's primary key values).
   - `SELECT` on `information_schema.table_constraints` and `information_schema.key_column_usage` for PostgreSQL and MySQL (required for primary-key introspection).
   - `SELECT` on `sys.indexes`, `sys.index_columns`, and `sys.columns` for SQL Server (required for primary-key introspection).

   These are database-side privileges configured on the database user, not AWS IAM permissions; the FIS and SSM IAM policies shipped with this template are unchanged by Real_Mode.

## Parameters

The experiment requires the following parameters:

### Database Configuration
- **DatabaseEngine**: `postgres`, `mysql`, or `sqlserver` (default: `postgres`)
- **DatabaseEndpoint**: Database DNS hostname or endpoint
- **DatabasePort**: Database port (default: 5432 for PostgreSQL, use 3306 for MySQL, 1433 for SQL Server)
- **DatabaseName**: User database the harness connects to. The harness creates the synthetic `fis_blocking_locks_target` table inside this database (Synthetic_Mode) or expects to find the user-supplied target table inside it (Real_Mode), so the database user identified by `DatabaseUser` needs CREATE / INSERT / SELECT / DROP on it. Use one of:
  - Your existing application database, if you have one.
  - A dedicated experiment database (for example `fis_test`), created once with `CREATE DATABASE fis_test;`.
  - **Do not** point this at engine-managed system schemas — `mysql` on RDS MySQL revokes DDL from the master user; `postgres` on RDS PostgreSQL works but is a poor default to encourage; `master` on RDS SQL Server should likewise be avoided in favour of a user database.
- **DatabaseUser**: Database username (default: `postgres`)
- **DatabasePasswordSecretArn**: ARN of Secrets Manager secret containing password
  - **Note** Since we don't know the ARN of your secret ahead of time, the sample SSM automation role ([database-blocking-locks-ssm-automation-role-iam-policy.json](database-blocking-locks-ssm-automation-role-iam-policy.json)) is given read access to all secrets, you should probably scope this down accordingly.

### Target Table
- **TargetTableName**: `String`. Default: `fis_blocking_locks_target`. Selects the table the harness operates against and, by extension, the experiment mode:
  - **Default value (`fis_blocking_locks_target`)**: selects **Synthetic_Mode**. The harness creates the `fis_blocking_locks_target` table on startup (if it does not already exist), seeds a row, locks it, ramps Waiters that issue the same locking `SELECT` against it, and drops the table on clean shutdown if this run created it. No application data is touched.
  - **Any other value**: enables **Real_Mode**. The harness targets the named application table, discovers its primary key via metadata views, selects the first row ordered by primary key, and locks it read-only via `SELECT ... FOR UPDATE` (PostgreSQL/MySQL) or `SELECT ... WITH (UPDLOCK, HOLDLOCK)` (SQL Server). No `INSERT`, `UPDATE`, `DELETE`, or DDL is executed against the named table.
  - **WARNING**: Real_Mode causes **actual application impact**. Any application transaction that contends for the locked row will block for up to `ExperimentDuration`. Only set `TargetTableName` to a non-default value when you have intentionally opted into targeting a real application table and have understood the blast radius for your engine (see the Engine-Specific Blast Radius section).
  - **SQL Server** accepts schema-qualified (`dbo.orders`) or unqualified (`orders`, defaulting to `dbo`) names.

### Synthetic_Mode vs Real_Mode

The experiment runs in one of two modes determined entirely by the value of `TargetTableName`. There is no separate mode flag — Real_Mode is opt-in by setting `TargetTableName` to any value other than the default.

| Aspect | Synthetic_Mode | Real_Mode |
| --- | --- | --- |
| **How to enable** | `TargetTableName=fis_blocking_locks_target` (the default; also applies if the parameter is omitted) | `TargetTableName=<any other value>` |
| **Table targeted** | `fis_blocking_locks_target`, an experiment-owned table that no application reads or writes | The user-supplied application table. PostgreSQL/MySQL: unqualified, scoped to the connection's current database/schema. SQL Server: schema-qualified (`dbo.orders`) or unqualified (`orders`, defaulting to `dbo`). |
| **DDL/DML against the table** | The harness `CREATE TABLE`s the synthetic table on startup if missing, `INSERT`s seed row `id = 1`, and `DROP TABLE`s on clean shutdown if this run created it. | None. The harness issues **no** `CREATE`, `ALTER`, `DROP`, `TRUNCATE`, `INSERT`, `UPDATE`, `DELETE`, or `MERGE` against the named table at any point. |
| **Blocker lock SQL** | PostgreSQL/MySQL: `SELECT id FROM fis_blocking_locks_target WHERE id = 1 FOR UPDATE`. SQL Server: `SELECT id FROM dbo.fis_blocking_locks_target WITH (UPDLOCK, HOLDLOCK) WHERE id = 1`. | PostgreSQL/MySQL: `SELECT <pk_cols> FROM <table> WHERE <pk_clause> FOR UPDATE`. SQL Server: `SELECT <pk_cols> FROM <table> WITH (UPDLOCK, HOLDLOCK) WHERE <pk_clause>`. The `<pk_cols>` and `<pk_clause>` are derived from the table's primary key, discovered at runtime via engine-native metadata views. |
| **Waiter lock SQL** | The same locking `SELECT` statement used by the Blocker, against `id = 1` of `fis_blocking_locks_target`. PostgreSQL/MySQL: `SELECT id FROM fis_blocking_locks_target WHERE id = 1 FOR UPDATE`. SQL Server: `SELECT id FROM dbo.fis_blocking_locks_target WITH (UPDLOCK, HOLDLOCK) WHERE id = 1`. Waiters never `UPDATE`, `INSERT`, or `DELETE`. | The same locking `SELECT` statement used by the Blocker. Waiters never `UPDATE`, `INSERT`, or `DELETE`. |
| **Application impact** | None. No application transaction touches `fis_blocking_locks_target`, so the experiment is invisible to your workload except via the engine-specific blocked-waiter metric. | **Real.** Any application transaction that contends for the locked row blocks for up to `ExperimentDuration`. The exact set of statements that block (writes only, or writes plus plain reads) depends on the engine — see the Engine-Specific Blast Radius section. |
| **Cleanup of the target table** | The harness drops `fis_blocking_locks_target` on clean shutdown if this run created it. A pre-existing matching table is left in place. | The harness performs no DDL or DML against the named table on cleanup. The table contains the same rows with the same column values after the experiment as before. |

The shipped FIS experiment template sets `TargetTableName` to `fis_blocking_locks_target` in `documentParameters`, so an out-of-the-box deploy runs in Synthetic_Mode unchanged.

### Contention Settings
- **WaiterCount**: Total number of Waiter sessions to ramp up against the Blocker-held row (default: 50). Each currently-blocked Waiter contributes approximately 1 to the engine-specific blocked-waiter count.
- **ExperimentDuration**: Total experiment duration in ISO8601 format (default: PT10M = 10 minutes, e.g., PT1H = 1 hour, PT30M = 30 minutes). **This parameter controls how long the Blocker session holds the row lock.**
  - **Note** this is not the same as the FIS Experiment Template Max Duration (default 3 hours for this experiment template) which functions as an overarching timeout.
- **RampTime**: Time to gradually ramp up to `WaiterCount` in ISO8601 format (default: PT1M = 1 minute, e.g., PT30S = 30 seconds, PT2M = 2 minutes, PT0S = immediate)
- **RampSteps**: Number of steps to reach `WaiterCount` (default: 10, e.g., 2=50% then 100%, 10=10% increments)

### Infrastructure
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
  5. Update the **Document parameters** to match your target e.g. `{"DatabaseEngine":"postgres","DatabaseEndpoint":"database-1.cluster-1234abcde.eu-west-1.rds.amazonaws.com","DatabasePort":"5432","DatabaseName":"postgres","DatabaseUser":"postgres","DatabasePasswordSecretArn":"arn:aws:secretsmanager:eu-west-1:123456789012:secret:rds!cluster-xxxx-yyyy-zzzz","WaiterCount":"50","ExperimentDuration":"PT30M","RampTime":"PT10M","RampSteps":"10","VpcId":"vpc-1234567abcd","SubnetId":"subnet-1234-abcdef","DatabaseSecurityGroupId":"sg-1234567abcd","InstanceType":"t3.small"}`
  6. **Note** there is no target defined in the FIS experiment template since this is managed through the SSM Automation document and the Document parameters you just entered, so **do not amend the target section of the template**
  7. Select **Save** and then **Update experiment template**
  8. You can now **Start experiment**

### Example: Real_Mode `documentParameters`

To run the experiment in Real_Mode, set `TargetTableName` to the name of an application table you want to target. The harness will introspect that table's primary key via engine-native metadata views, select the first row ordered by primary key, and acquire a row-level lock against that row using a read-only locking SELECT. Replace the placeholders with values that match your environment, and replace `application_orders` with the name of the application table you intend to target:

```json
{"DatabaseEngine":"postgres","DatabaseEndpoint":"database-1.cluster-1234abcde.eu-west-1.rds.amazonaws.com","DatabasePort":"5432","DatabaseName":"appdb","DatabaseUser":"fis_runner","DatabasePasswordSecretArn":"arn:aws:secretsmanager:eu-west-1:123456789012:secret:fis/db-password-xxxxxx","TargetTableName":"application_orders","WaiterCount":"50","ExperimentDuration":"PT30M","RampTime":"PT10M","RampSteps":"10","VpcId":"vpc-1234567abcd","SubnetId":"subnet-1234-abcdef","DatabaseSecurityGroupId":"sg-1234567abcd","InstanceType":"t3.small"}
```

For SQL Server, `TargetTableName` accepts schema-qualified (`dbo.application_orders`) or unqualified (`application_orders`, defaulting to `dbo`) names. Before setting `TargetTableName` to a non-default value, confirm the target table satisfies the items in the Real_Mode Prerequisites subsection above.

### Real_Mode safety posture

Real_Mode never executes `INSERT`, `UPDATE`, `DELETE`, or DDL (`CREATE`, `ALTER`, `DROP`, `TRUNCATE`, `MERGE`) against the target table. Both the Blocker and every Waiter acquire row locks using read-only locking statements only — `SELECT ... FOR UPDATE` on PostgreSQL and MySQL, or `SELECT ... WITH (UPDLOCK, HOLDLOCK)` on SQL Server — against the row identified by the primary key values selected at pre-flight time. After the experiment completes (whether normally or via early termination), the target table contains exactly the same rows with the same column values as before the experiment started: zero rows are inserted, zero rows are updated, zero rows are deleted, and the table's schema is unchanged. The only effect on the target table is transient row-level lock contention against the selected row for the duration of the experiment; once the Blocker COMMITs and the Waiters unblock, the contention disappears and the table is byte-for-byte equivalent to its pre-experiment state.

### Real_Mode exit codes

When the harness fails during Real_Mode pre-flight or lock acquisition, it exits with one of the following codes and emits a diagnostic on standard error. SSM surfaces the exit code as the `InjectBlockingLocks` step's failure output, so operators can map the step exit code back to a root cause without reading the full CloudWatch Logs stream. Every Real_Mode error path exits **before** any DDL or DML write would be issued against the user-supplied table, so a non-zero exit guarantees the target database is unmodified.

Each diagnostic includes the qualified table reference, the engine, and (where applicable) the underlying driver exception class and message; introspection failures additionally name the engine-appropriate metadata views so operators know which permission to grant.

- **Exit 20 — Target table does not exist.**
  - Trigger: `validate_target_table` issued `SELECT 1 FROM <qualified_table_ref> WHERE 1=0` and the engine reported the relation as missing (PostgreSQL `UndefinedTable`, MySQL `1146 Table ... doesn't exist`, SQL Server `Invalid object name`).
  - Diagnostic: `ERROR: table <qualified_table_ref> missing in db <DatabaseName> on <DatabaseEndpoint>:<DatabasePort> (engine=<DatabaseEngine>): <ExceptionClass>: <message>`
  - Most common cause: misspelled `TargetTableName`, wrong `DatabaseName`, or the target table lives in a schema other than the connection's default schema (PostgreSQL/MySQL) or `dbo` (SQL Server). For SQL Server, prefer the schema-qualified form (`dbo.orders`).

- **Exit 21 — Target table is empty.**
  - Trigger: either the non-empty probe in `validate_target_table` (`SELECT 1 FROM <ref> LIMIT 1` on PostgreSQL/MySQL, `SELECT TOP 1 1 FROM <ref>` on SQL Server) returned no rows, or `select_target_row` returned no row because the table became empty between validation and selection.
  - Diagnostic: `ERROR: table <qualified_table_ref> empty; cannot select row (engine=<DatabaseEngine>).`
  - Most common cause: the target table really is empty, or it was emptied by an application transaction during the brief pre-flight window. Real_Mode requires at least one row at the moment of row selection.

- **Exit 22 — Pre-flight checks exceeded the 10s deadline.**
  - Trigger: the existence probe and the non-empty probe combined took longer than 10 seconds of wall-clock time (Requirement 2.6). The deadline is evaluated once after both probes complete.
  - Diagnostic: `ERROR: pre-flight exceeded 10.0s deadline on <qualified_table_ref> (engine=<DatabaseEngine>); elapsed <seconds>s.`
  - Most common cause: the database is overloaded, the target table is so large that even a `LIMIT 1` probe is slow under contention, or network latency between the load generator and the database is unusually high. The harness fails closed rather than blocking the experiment indefinitely on a slow database.

- **Exit 23 — Target table has no primary key.**
  - Trigger: `introspect_primary_key` ran the engine-specific metadata query and the result set was empty, meaning the table has no `PRIMARY KEY` constraint (PostgreSQL/MySQL) or no index with `is_primary_key = 1` (SQL Server).
  - Diagnostic: `ERROR: table <qualified> has no PK; Real_Mode requires one (engine=<DatabaseEngine>).`
  - Most common cause: the target table was modelled without a primary key. Real_Mode requires a primary key to deterministically identify and lock a single row; tables with only a unique index, only a clustered index without `is_primary_key = 1`, or no key at all are not supported.

- **Exit 24 — Introspection failed / permission denied.**
  - Trigger: any of the metadata or probe queries raised an exception. There are five call sites, each with its own diagnostic shape:
    - Existence probe denied: `ERROR: SELECT denied on <qualified_table_ref> (engine=<DatabaseEngine>): <ExceptionClass>: <message>`
    - Existence probe other failure: `ERROR: existence probe failed for <qualified_table_ref> (engine=<DatabaseEngine>): <ExceptionClass>: <message>`
    - Non-empty probe failed: `ERROR: non-empty probe failed for <qualified_table_ref> (engine=<DatabaseEngine>): <ExceptionClass>: <message>`
    - Primary-key introspection failed: `ERROR: PK introspection failed for <qualified> (engine=<DatabaseEngine>): <ExceptionClass>: <message>. Verify <DatabaseUser> has SELECT on <metadata_views>.`
    - Target-row select failed: `ERROR: target-row select failed for <qualified_table_ref> (engine=<DatabaseEngine>): <ExceptionClass>: <message>`
  - Most common cause: the database user identified by `DatabaseUser` lacks `SELECT` on the target table or on the engine-appropriate metadata views — `information_schema.table_constraints` and `information_schema.key_column_usage` for PostgreSQL and MySQL, or `sys.indexes`, `sys.index_columns`, and `sys.columns` for SQL Server. The introspection-failure diagnostic names the metadata views the harness queried so the DBA knows exactly which `GRANT SELECT` to issue.

- **Exit 25 — Blocker failed to acquire the lock; row deleted between selection and lock acquisition.**
  - Trigger: the Blocker connection executed the locking SELECT (`SELECT <pk_cols> FROM <ref> WHERE <pk_clause> FOR UPDATE` on PostgreSQL/MySQL, or the `WITH (UPDLOCK, HOLDLOCK)` form on SQL Server) and either the driver raised an exception, or the statement returned zero rows. Returning zero rows means the row identified by the primary-key values selected at pre-flight time is no longer present.
  - Diagnostics:
    - Driver exception: `ERROR: blocker lock failed on <qualified_ref> pk=<pk_values> (engine=<DatabaseEngine>): <ExceptionClass>: <message>`
    - Row deleted: `ERROR: blocker lock failed on <qualified_ref> pk=<pk_values>; row deleted before lock acquired (engine=<DatabaseEngine>).`
  - Most common cause: a concurrent application transaction deleted the selected row between pre-flight row selection and Blocker lock acquisition. The harness deliberately does not retry — re-selecting a different row would change the experiment's blast radius silently. Re-running the experiment will pick a different first row if the deletion has been committed.

> **Note on log message brevity.** To stay under the 64 KiB SSM document size limit, the diagnostic strings above were tightened from longer, more descriptive forms. The structure (exit code, table reference, engine, underlying exception class and message) is preserved; only the prose is shorter.

Exit codes outside the 20–25 range are not Real_Mode-specific and retain their original meaning (`1` argv parsing, `2` Secrets Manager retrieval, `3` database connect failure, `4` unsupported `DatabaseEngine`, `5` Synthetic_Mode lock acquisition failure, `6` Synthetic_Mode `ensure_target_table` failure).

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
9. The harness opens a short-lived control connection and, if `fis_blocking_locks_target` does not already exist, creates it with an `id INT PRIMARY KEY` column and a `counter INT` column and seeds row `id = 1`. The harness records whether this run created the table so that cleanup only drops the table if this run created it.
10. The harness opens exactly one Blocker session, begins a transaction, and acquires the row lock using the engine-native idiom:
    - PostgreSQL and MySQL: `SELECT id FROM fis_blocking_locks_target WHERE id = 1 FOR UPDATE`
    - SQL Server: `SELECT id FROM dbo.fis_blocking_locks_target WITH (UPDLOCK, HOLDLOCK) WHERE id = 1`
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
    3. Issues the same engine-native locking `SELECT` the Blocker used: `SELECT id FROM fis_blocking_locks_target WHERE id = 1 FOR UPDATE` on PostgreSQL/MySQL, `SELECT id FROM dbo.fis_blocking_locks_target WITH (UPDLOCK, HOLDLOCK) WHERE id = 1` on SQL Server
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

PostgreSQL uses MVCC (Multi-Version Concurrency Control). While the Blocker holds the row lock on the target row, the following statements against the locked row will block:

- `UPDATE`
- `DELETE`
- `SELECT ... FOR UPDATE`
- `SELECT ... FOR NO KEY UPDATE`, `SELECT ... FOR SHARE`, `SELECT ... FOR KEY SHARE`

Plain `SELECT` statements (without `FOR UPDATE`/`FOR SHARE`) are **not** blocked. PostgreSQL readers see the last-committed version of the row via MVCC and do not need to acquire a row-level lock.

### MySQL/InnoDB (Aurora MySQL and RDS MySQL)

MySQL with the default InnoDB storage engine also uses MVCC. While the Blocker holds the row lock on the target row, the following statements against the locked row will block:

- `UPDATE`
- `DELETE`
- `SELECT ... FOR UPDATE`
- `SELECT ... FOR SHARE` (and the legacy `LOCK IN SHARE MODE`)

Plain `SELECT` statements are **not** blocked. InnoDB readers see a consistent snapshot via MVCC and do not need to acquire a row-level lock.

### SQL Server (RDS SQL Server)

SQL Server's blast radius depends on whether **Read Committed Snapshot Isolation (RCSI)** is enabled on the target database.

**With RCSI off (the default):** SQL Server's default isolation level is `READ COMMITTED` and, with RCSI off, readers acquire shared locks. While the Blocker holds the row lock on the target row, the following statements against the locked row will block:

- `UPDATE`
- `DELETE`
- Plain `SELECT` (because the reader needs a shared lock that is incompatible with the Blocker's update lock)

This is a notably wider blast radius than PostgreSQL or MySQL because plain reads are also blocked.

**With RCSI on:** Plain `SELECT` statements use row versioning instead of shared locks and are **not** blocked. `UPDATE`, `DELETE`, and locking reads (`SELECT ... WITH (UPDLOCK)`, `SELECT ... WITH (XLOCK)`, etc.) still block.

**RCSI is OFF by default on RDS SQL Server.** Enabling RCSI on RDS Multi-AZ deployments may require additional steps because the underlying availability-group configuration imposes constraints on the `ALTER DATABASE ... SET READ_COMMITTED_SNAPSHOT ON` statement (the database must be the only user connection at the time of the change, and Multi-AZ failover groups can complicate that requirement). Consult the RDS SQL Server documentation and coordinate with your DBA before changing isolation settings on a Multi-AZ instance.

**Recommended pre-flight check.** Before running the experiment in Real_Mode against SQL Server, query the target database to confirm whether RCSI is on or off so you understand which of the two blast-radius profiles applies:

```sql
SELECT name, snapshot_isolation_state_desc, is_read_committed_snapshot_on
FROM sys.databases
WHERE name = DB_NAME();
```

`is_read_committed_snapshot_on = 1` indicates RCSI is on (plain `SELECT` not blocked); `is_read_committed_snapshot_on = 0` indicates RCSI is off (plain `SELECT` is blocked).

## Stop Conditions

The experiment template does not have any specific stop conditions defined by default. It will continue to run until:
- All actions complete successfully or one fails
- Manually stopped via FIS console/API
- A custom CloudWatch alarm triggers (if configured)

## Observability and Stop Conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

### Where to look for the blocked-waiter signal per engine

The engine-specific metric that reflects blocked waiters is different for each supported engine. Each Waiter that is currently blocked on the Target_Row contributes approximately 1 to the corresponding count, and the `ExperimentDuration` parameter directly controls how long the Blocker holds the row lock.

- **Aurora MySQL and RDS MySQL**: the right primary signals are two cumulative counters in the `db.Locks.*` namespace. **`db.Locks.innodb_row_lock_waits.avg`** is the count of times any transaction has waited for a row lock; this rises by 1 per blocked Waiter as it enters the wait queue. **`db.Locks.innodb_lock_timeouts.avg`** is the count of `ERROR 1205 (HY000) Lock wait timeout exceeded` aborts — this is the *direct* "Waiters being killed by the engine's `innodb_lock_wait_timeout`" signal and is the most precise expression of the failure mode. View both as **Row lock time** / **Row lock waits** / **Lock timeouts** in Performance Insights → Database Insights, or alarm on either with `DB_PERF_INSIGHTS('RDS', '<resource-id>', '<metric-name>')`. Cross-reference with the **application-side `1205 (HY000) Lock wait timeout exceeded` error rate** — this is the customer-impact signal and the highest-priority alarm. Aurora MySQL `BlockedTransactions` is a point-in-time gauge that is *bursty* under default settings (it rises briefly then falls back as Waiters get aborted) and so will not plateau at `WaiterCount` the way the SQL Server and PostgreSQL signals do; treat it as supplementary rather than primary.
- **RDS SQL Server**: the `db.General Statistics.Processes blocked` counter in Performance Insights.
- **Aurora PostgreSQL and RDS PostgreSQL**: open the **Performance Insights Database load** chart for the writer instance and group by **Waits**. The `Lock:Tuple` wait event will rise to roughly `WaiterCount` while the experiment runs (Waiters blocked on `SELECT ... FOR UPDATE` against the locked row report as `Lock:Tuple`; you may also see `Lock:transactionid` depending on the contention pattern). For alarm-driven detection, set `log_lock_waits = on` in the **DB parameter group** for the writer instance, publish the PostgreSQL log to CloudWatch Logs, and create a CloudWatch Logs metric filter on the substring `still waiting for`. PostgreSQL does not publish a top-level `BlockedTransactions`-style CloudWatch metric, and Performance Insights wait events are not exposed via the `DB_PERF_INSIGHTS` metric math function. After the alarm fires, use **CloudWatch Database Insights (Advanced mode)** lock-tree analysis to identify the blocking session.

#### MySQL-specific note: why the signal is bursty, not flat

On MySQL, `innodb_lock_wait_timeout` (default 50 s) only applies to transactions waiting *to acquire* a lock; it does **not** bound the holder. So the production failure mode is: one transaction holds a row lock indefinitely, application transactions trying to update the row each wait up to 50 s and are aborted with `ERROR 1205`, the application either retries or fails the user request, and a steady stream of new transactions keeps arriving and being aborted. A point-in-time gauge like `BlockedTransactions` therefore stays low even though contention is sustained and customer-visible. The cumulative `Innodb_row_lock_waits` counter and the application-side 1205 error rate both reflect the rate of aborts and are the right operational signals.

#### MySQL-specific parameter sizing

The harness creates each Waiter once and does not replenish it after the engine aborts it at `innodb_lock_wait_timeout` (default 50 s). On MySQL this means the standard "ramp Waiters then watch them sit" model from PostgreSQL and SQL Server doesn't apply: every Waiter you create dies once at ~50 s after its start and is gone. To produce sustained, realistic contention signal across the full `ExperimentDuration` you need to size two parameters together:

- **`RampTime = ExperimentDuration`.** Spread Waiter creation evenly across the experiment so new Waiters are still being created late into the run, rather than ramping all of them in the first few minutes and then having no Waiters left to abort.
- **`WaiterCount` ≈ `ExperimentDuration` / 50 s × target concurrent timeouts.** Each Waiter is alive for at most 50 s, so to maintain *N* concurrent abort-pending Waiters across an `ExperimentDuration`-second run you need roughly `WaiterCount = ExperimentDuration / 50 × N` Waiters in total.

Suggested starting values for typical `ExperimentDuration` choices, targeting roughly 5 concurrent abort-pending Waiters at any moment:

| `ExperimentDuration` | `RampTime` | `WaiterCount` | What you'll see |
| --- | --- | --- | --- |
| `PT5M` (300 s) | `PT5M` | 30 | ~6 timeouts/min sustained |
| `PT10M` (600 s) | `PT10M` | 60 | ~6 timeouts/min sustained |
| `PT30M` (1800 s) | `PT30M` | 180 | ~6 timeouts/min sustained |
| `PT1H` (3600 s) | `PT1H` | 360 | ~6 timeouts/min sustained |

These figures size the harness so that `db.Locks.innodb_lock_timeouts.avg` (and the equivalent application-side 1205 error rate) shows a roughly steady non-zero rate for the whole experiment rather than a single early burst followed by silence. Scale `WaiterCount` proportionally if you want a higher concurrent-abort target. PostgreSQL and SQL Server do not need this adjustment because their Waiters do not get aborted; on those engines the original "small `RampTime`, modest `WaiterCount`" model holds.

Expect the chosen metric to climb in stepped increments matching the Waiter ramp (`WaiterCount / RampSteps` per step), plateau at roughly `WaiterCount` once the ramp is complete, and return to baseline within a short interval after `ExperimentDuration` elapses and the Blocker COMMITs.

## DBA Guardrails and Pre-flight Check

The most common reason the Blocker's lock is released before `ExperimentDuration` elapses is a DBA-configured idle-transaction timeout. Coordinate with your DBAs before running this experiment against any shared database.

- **Aurora PostgreSQL and RDS PostgreSQL**: `idle_in_transaction_session_timeout`, if set to a value shorter than `ExperimentDuration`, will cause the target database to terminate the Blocker's idle transaction early. This rolls back the lock and releases all Waiters before the planned duration elapses. When the harness detects this it emits a diagnostic that names the likely cause (a DBA-configured idle-in-transaction timeout), the `DatabaseEngine`, and the elapsed time at which the termination occurred.
- **Aurora MySQL and RDS MySQL**: `max_execution_time` only applies to individual `SELECT` statements under READ COMMITTED. Under the in-process-sleep approach used by this harness, no long-running statement runs while the lock is held, so `max_execution_time` is **not** expected to affect the Blocker. This is noted for completeness so that operators are not surprised if they see the parameter in their DB parameter group.
- **RDS SQL Server**: has no parameter analogous to `idle_in_transaction_session_timeout`; open transactions are not subject to idle timeouts by default.

### Recommended pre-flight check

Before running the experiment, query the target database's idle-transaction timeout parameter and confirm it is unset, zero, or greater than `ExperimentDuration`:

```sql
-- Aurora PostgreSQL / RDS PostgreSQL
SHOW idle_in_transaction_session_timeout;

-- Aurora MySQL / RDS MySQL (informational only; does not affect this harness)
SHOW VARIABLES LIKE 'max_execution_time';
```

A value of `0` means "no timeout". Any non-zero value less than `ExperimentDuration` (in milliseconds for PostgreSQL) will cause the Blocker's idle transaction to be terminated early.

### Parameter group placement (Aurora PostgreSQL / RDS PostgreSQL)

Several PostgreSQL parameters relevant to this experiment — `idle_in_transaction_session_timeout`, `log_lock_waits`, `deadlock_timeout` — are **DB parameter group** settings (per-instance), not **DB cluster parameter group** settings. They appear on the *instance's* Modify screen, not on the cluster's. If you have built a custom parameter group and don't see these parameters when modifying the cluster, attach the custom DB parameter group to the writer instance (and any reader instances you want covered) instead. `log_lock_waits` is a dynamic parameter and applies without a reboot; `deadlock_timeout` is static and requires an instance reboot to take effect.

## Leftover Table Side Effect

The harness creates a dedicated `fis_blocking_locks_target` table in the target database on startup if it does not already exist, and drops it on clean shutdown. If the harness is terminated in a way that bypasses its cleanup (for example a hard kill of the EC2 instance without graceful shutdown, or a process crash between the Blocker COMMIT and the DROP TABLE), the `fis_blocking_locks_target` table may be left behind in the target database.

To remove a leftover table:

```sql
DROP TABLE fis_blocking_locks_target;
```

(On SQL Server use `DROP TABLE dbo.fis_blocking_locks_target;`.)

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. **Start Small**: Begin with a small `WaiterCount` (for example 10) to confirm the blocked-waiter signal appears on the engine-specific metric you expect, before scaling up.
2. **Use Gradual Ramp-Up**: Set a non-zero `RampTime` and a meaningful `RampSteps` (for example `RampTime=PT5M`, `RampSteps=10`) so that the blocked-waiter metric climbs in visible increments.
3. **Create a CloudWatch Alarm on the Blocked-Waiter Signal**: Build a CloudWatch alarm on the engine-specific signal that reflects blocked waiters (`BlockedTransactions` on Aurora MySQL, `db.General Statistics.Processes blocked` on RDS SQL Server, or — on Aurora PostgreSQL / RDS PostgreSQL — a CloudWatch Logs metric filter on the `still waiting for` substring after enabling `log_lock_waits = on` and publishing the PostgreSQL log to CloudWatch Logs).
4. **Add the Alarm as an FIS Stop Condition**: Attach that alarm as a `stopConditions` entry on the FIS experiment template so the experiment auto-halts if the blocked-waiter count exceeds a threshold that would be unsafe in your environment.
5. **Run the DBA Pre-flight Check**: Confirm that `idle_in_transaction_session_timeout` is unset, zero, or greater than `ExperimentDuration` before running against any shared database.
6. **Monitor Cleanup**: Verify that the EC2 instance is terminated, the ephemeral security group is deleted, and the `fis_blocking_locks_target` table is gone (if this run created it) after the experiment.

## Import Experiment

To import the experiment template into your AWS account, follow the step-by-step instructions in the [fis-template-library-tooling](https://github.com/aws-samples/fis-template-library-tooling) repository, which supports both AWS CLI and AWS CDK based deployment.
