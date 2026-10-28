# AWS Fault Injection Service Experiment: Database Slow Query

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

When a query against the {service1} database runs far longer than the expected {expected}ms, monitoring should detect it and notify the DevOps team within {y} minutes, naming the offending statement well enough to act on it. Users of {workload} should be able to complete the {service1} user journey within the SLA of 2 seconds, and other critical user journeys relating to {workload}; {service2} and {service3} should continue unaffected. The steady state of {n} transactions per second should be maintained.

When several long-running queries run concurrently, the DevOps team should be able to identify them from the alarm and supporting telemetry alone - statement text, session, duration, and originating application - without needing to reproduce the problem. Once the long-running queries end, monitoring should return to its steady state and any alarm should clear within {z} minutes without manual intervention.

### What does this enable me to verify?

This experiment exists to **test your detection, not your database**. It produces queries of a known, controlled duration so you can confirm:

* A long-running query is actually detected, and how long detection takes from the query starting
* Your alarm threshold is set where you think it is - a query held for `QueryDuration` either trips it or it does not
* The alert carries enough information to act on: statement text, duration, session, and application
* The query is visible where you expect it - Performance Insights top SQL, the slow query log, the engine's session view, or a custom CloudWatch metric
* Whether your "slow query" detection is really duration-based or merely CPU-based. Compare the `realistic` and `sleep` patterns: both run for exactly `QueryDuration`, but only `realistic` examines rows and registers load. **If `realistic` alerts and `sleep` does not, your detection is measuring work, not duration** - and a genuinely blocked or waiting query will go unnoticed
* Whether a server-side statement timeout is already protecting you (and whether that is the limit you intended)

## Description

This experiment runs deliberately long queries against your database by:

1. **Dynamically creating** an ephemeral EC2 instance as a query driver
2. **Bootstrapping** it with the appropriate database client (PostgreSQL, MySQL, SQL Server, or Oracle)
3. **Reporting any server-side statement limit** up front, since that is the most common reason a slow-query experiment fails to produce slow queries
4. **Issuing `ConcurrentQueries` long-running queries**, each on its own connection, repeatedly until `ExperimentDuration` elapses. Every statement is stamped with a unique marker comment so it can be picked out of logs, Performance Insights, and session views
5. **Observing the database's own session view** on a background connection, recording the longest query duration and peak concurrency *as monitoring would see it* - not just as the client measures it
6. **Verifying** that at least `MinLongQueriesObserved` queries actually reached `LongQueryThresholdSeconds`, and failing the experiment if not
7. **Terminating any lingering sessions** belonging to this execution, then terminating the query driver

**Nothing is written to your database.** No tables are created, no rows inserted, no data modified, and no locks taken beyond what a read-only `COUNT(*)` needs. The `sleep` pattern is close to zero-cost on the server; `realistic` adds one scan per query. The only sustained consumption is one connection per concurrent query. This makes it one of the safer experiments in this library, but it is still a real fault against a real database.

Supported engines:
- RDS PostgreSQL and Aurora PostgreSQL - uses `pg_sleep()`
- RDS Oracle - uses `DBMS_PIPE.RECEIVE_MESSAGE()` inside a single SQL statement where permitted, falling back to `DBMS_SESSION.SLEEP()` in a PL/SQL block
- RDS MySQL and Aurora MySQL - **experimental**, not yet validated end-to-end
- RDS SQL Server - **experimental**, not yet validated end-to-end

### Choosing a query pattern

| | `realistic` (default) | `sleep` | `cpu` |
|---|---|---|---|
| Shape | Real read-only scan, then sleeps for the remainder | Pure wait, examines no rows | Sustained CPU-bound work for the whole duration |
| Duration | Exact - equals `QueryDuration` | Exact - equals `QueryDuration` | About `QueryDuration`, by runtime calibration (measured 98-99.9%) |
| Rows examined | Real | None | Real |
| Server cost | One scan, then an idle connection | Negligible; one idle connection | Real CPU, roughly one core per concurrent query, for the full duration |
| Visible to | Slow query logs, Performance Insights, session views, duration-based alarms | Session views and duration-based alarms only | All of the above **plus** CPU alarms and Performance Insights load |
| Best for | **Most runs** - looks like a real slow query to every monitoring surface | Isolating whether detection is genuinely duration-based | A query that is both long **and** genuinely expensive |

**Use `realistic` unless you have a reason not to.** It scans real rows and has a real plan, so it reaches the monitoring surfaces that filter out trivial statements - while the sleep component pins the duration to exactly `QueryDuration`, which is what makes the result a clean test of your threshold. It is still read-only: the scan is a `COUNT(*)` and nothing is modified.

`sleep` remains useful as a deliberate contrast. Run `realistic` first to confirm detection works at all, then run `sleep`: if `realistic` fires an alarm and `sleep` does not, your detection depends on the query doing work, and a genuinely blocked or waiting query will be missed.

> **`cpu` consumes real CPU on your database.** With `ConcurrentQueries` set to 3 you are pinning roughly three cores for the duration. Size `CpuWorkUnits` and `ConcurrentQueries` against the instance class, and do not run it against anything serving production traffic.

## Architecture Overview

```
FIS Experiment
    ↓
SSM Automation Document
    ↓
1. Create temporary security group in VPC
    ↓
2. Revoke the security group's default allow-all egress rule, then add egress
   rules: query driver → Database port, and query driver → HTTPS (443) for
   SSM, Secrets Manager, and package repositories
    ↓
3. Add ingress rule: Database SG ← query driver SG (database SG must be
   tagged FIS-Ready=True)
    ↓
4. Launch EC2 instance (Amazon Linux 2023) with new SG
    ↓
5. Wait for SSM Agent to be online
    ↓
6. Install database client (psql/mysql/sqlcmd/sqlplus)
    ↓
7. Report any server-side statement timeout, then issue ConcurrentQueries
   long-running queries back to back until ExperimentDuration elapses, while
   a background observer samples the engine's session view
    ↓
8. Verify at least MinLongQueriesObserved queries reached
   LongQueryThresholdSeconds; fail the automation if not
    ↓
9. Terminate any sessions still running under this execution's marker
    ↓
10. Terminate EC2 instance
    ↓
11. Revoke ingress rule from database SG (idempotent - runs even if the query
    driver failed to launch)
    ↓
12. Delete temporary security group
```

## Prerequisites

Before running this experiment, ensure that:

1. **VPC Configuration**:
   - You have a VPC with at least one subnet that can reach your database
   - You know the VPC ID and subnet ID
   - You know the security group ID attached to your database
   - The subnet's route table and any VPC endpoints/NAT provide the query driver with outbound HTTPS (443) connectivity to:
     - Amazon SSM and SSM Messages endpoints (required for the SSM Agent and Run Command)
     - AWS Secrets Manager (to retrieve the database password)
     - Amazon Linux package repositories (`dnf`) and PyPI (for `pip3` installs)
     - `packages.microsoft.com` (SQL Server engine only - mssql-tools repo)
     - `download.oracle.com` (Oracle engine only - Instant Client RPMs)
   - **VPC interface endpoints alone are not sufficient** - the client installs need an internet route via IGW or NAT
   - The temporary security group's egress is restricted to the database port and HTTPS (443) only

2. **Database Configuration**:
   - Supported database is running (PostgreSQL and Oracle are the validated paths; MySQL and SQL Server are experimental - see Description above)
   - You know the database endpoint, username, and password, and the password is in Secrets Manager
   - The database security group (`DatabaseSecurityGroupId`) is tagged `FIS-Ready=True` - the SSM automation role's IAM policy only permits ingress changes on security groups carrying this tag
   - `ConcurrentQueries` connections are available within the connection limit, with headroom for the observer and cleanup connections (two more)

3. **Permissions for the observation and cleanup steps** — these are what make the experiment report what monitoring would see, and clean up after itself:
   - **Session view read access** for `DatabaseUser`: `pg_stat_activity` (PostgreSQL - a non-superuser sees only its own queries' text unless granted `pg_read_all_stats`, which is enough here since the experiment reads its own sessions), `information_schema.PROCESSLIST` (MySQL - needs `PROCESS`), `sys.dm_exec_requests`/`sys.dm_exec_sessions` (SQL Server - needs `VIEW SERVER STATE`), `v$session` (Oracle - needs `SELECT_CATALOG_ROLE` or equivalent)
   - **Session termination**: `pg_terminate_backend` (PostgreSQL - owner of the session, or `pg_signal_backend`), `PROCESS`+`SUPER`/`CONNECTION_ADMIN` for `KILL` (MySQL), `ALTER ANY CONNECTION` or `KILL` on own sessions (SQL Server), `rdsadmin.rdsadmin_util.kill` (RDS Oracle)
   - If session-view access is missing the experiment still runs and still injects the fault; it just reports `SessionViewSamples: 0` and tells you it could not assess server-side visibility

4. **Monitoring you intend to test is already in place.** This experiment is pointless against a database with no long-running-query detection — set that up first, then use this to prove it works.

### Create Required Experiment Resources

1. **Experiment template**:
   - Import the FIS experiment template (`database-slow-query-experiment-template.json`) into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).

2. **IAM Roles**: Create the following IAM roles in your account using the sample policies provided:
   - FIS execution role (`DatabaseSlowQuery-FIS-Role`) with permissions to start SSM automation (`database-slow-query-fis-role-iam-policy.json`)
   - SSM automation role (`DatabaseSlowQuery-SSM-Automation-Role`) with permissions to launch EC2 instances and execute commands (`database-slow-query-ssm-automation-role-iam-policy.json`)
   - EC2 instance role (`SSM-Managed-Instance-Profile-Role`, attached via instance profile `SSM-Managed-Instance-Profile`) with the `AmazonSSMManagedInstanceCore` managed policy **and** `database-slow-query-ec2-instance-role-iam-policy.json`
     - **Important**: the query driver retrieves the database password via `boto3.get_secret_value()` inside the `AWS-RunShellScript` command, which runs under this EC2 instance role - not the SSM automation role. Secrets Manager (and KMS, if the secret uses a customer-managed key) permissions belong here, scoped to your specific secret ARN
   - **Note**: this template hardcodes the role/document names above. Create the roles with these exact names, or update `database-slow-query-automation.yaml` and `database-slow-query-experiment-template.json` consistently if you rename them.

3. **SSM Document**:
   - Deploy the SSM automation document (`database-slow-query-automation.yaml`) to your account, naming it `DatabaseSlowQuery-Automation`

## Parameters

### Database Configuration
- **DatabaseEngine**: `postgres`, `mysql`, `sqlserver`, or `oracle` (default: `postgres`)
- **DatabaseEndpoint**: Database DNS hostname or endpoint
- **DatabasePort**: Database port (default: 5432; use 3306 for MySQL, 1433 for SQL Server, 1521 for Oracle)
- **DatabaseName**: Database name, or service name for Oracle
- **DatabaseUser**: Database username (default: `postgres`)
- **DatabasePasswordSecretArn**: ARN of Secrets Manager secret containing the password

### Query Settings
- **QueryPattern**: `realistic`, `sleep`, or `cpu` (default: `realistic`) - see "Choosing a query pattern" above
- **TargetTableName**: Optional table for `realistic` to scan, as `table` or `schema.table` (default: empty). The query is read-only - a `COUNT(*)` - and never modifies it. Pick a table large enough that the scan is meaningful. Leave empty to use a synthetic row source that needs no existing table. Only a plain or schema-qualified identifier is accepted, and it is only ever used as the source of a `COUNT(*)`
- **ScanRowCount**: Rows generated by the synthetic row source when `TargetTableName` is empty (default: 500000). Sized to clear thresholds such as MySQL's `min_examined_row_limit` and to register as real work. Ignored when `TargetTableName` is set, or for other patterns
- **QueryDuration**: How long each individual query runs, ISO8601 (default: **PT15M**). **This is the number your monitoring has to notice, and the main dial to turn.** Pick it to match the scenario you care about:

  | Value | Scenario it represents |
  |---|---|
  | PT1M - PT5M | Quick threshold check - does the alarm fire at all, and how fast |
  | **PT15M** (default) | A genuinely problematic long-running query; long enough to be unambiguously wrong |
  | PT30M and above | Escalation and on-call response - does anyone actually act on it |

  Exact for `realistic` and `sleep` (for `realistic` the scan adds a second or two on top). For `cpu` it is reached by runtime calibration - measured within 2% on both validated engines.
- **ExperimentDuration**: Total time to keep issuing queries, ISO8601 (default: PT15M). Each worker issues queries back to back, so roughly `ExperimentDuration / QueryDuration` queries per worker. **At the defaults the two are equal, so each worker runs exactly one 15-minute query.** Raise it to repeat the query - useful for checking whether a second occurrence alarms as well as the first, or whether the alarm was acknowledged away. A worker never starts a query that cannot finish before the experiment ends, so the run does not overshoot
- **ConcurrentQueries**: Number of simultaneous long-running queries, each on its own connection (default: 3). Each holds a connection for the whole of `QueryDuration`, so at the 15-minute default that is three connections occupied for a quarter of an hour - check it against your connection limit
- **CpuWorkUnits**: Size of one CPU burn unit for `QueryPattern=cpu` (default: 100000). The experiment times a burn at startup and repeats it enough times to fill `QueryDuration`, so this controls **granularity, not duration** - aim for a unit taking roughly half a second to a second. Grown automatically if too small. On SQL Server the burn is not repeated, so this value alone sets the duration. Ignored for `realistic` and `sleep`. See "How the cpu pattern reaches an exact duration" below

### Detection Verification
- **LongQueryThresholdSeconds**: The threshold your monitoring uses to define a long-running query (default: 60). The experiment reports how many queries exceeded it, and the longest duration actually visible in the session view, so you can compare against whether your alarm fired
- **MinLongQueriesObserved**: Minimum number of queries that must reach the threshold for the run to count as a successful fault injection (default: 1). Below this, `ExecuteSlowQueries` fails and the automation exits non-zero - most often because a server-side statement timeout is shorter than `QueryDuration`

### Infrastructure
- **SubnetId**: Subnet where the query driver will be launched
- **VpcId**: VPC ID (used to create the temporary security group)
- **DatabaseSecurityGroupId**: Security group of the target database, must be tagged `FIS-Ready=True`
- **InstanceType**: EC2 instance type for the query driver (default: t3.small - the work happens on the database, not here)

## Executing the Experiment
- Once the FIS Experiment template is deployed in your account, you will need to **update the experiment template** by editing it in the console or via the API to set appropriate parameters for your desired database target and environment
- To update via the console:
  1. Open the FIS Console
  2. Select the experiment template "Database-slow-query"
  3. Select **Actions / Update Experiment Template**
  4. Select the **ExecuteSlowQueries** Action
  5. Update the **Document parameters** to match your target e.g. {"DatabaseEngine": "postgres", "DatabaseEndpoint": "database-1.cluster-1234abcde.eu-west-1.rds.amazonaws.com", "DatabasePort": "5432", "DatabaseName": "postgres", "DatabaseUser": "postgres", "DatabasePasswordSecretArn": "arn:aws:secretsmanager:eu-west-1:123456789012:secret:rds!cluster-xxxx", "QueryPattern": "realistic", "QueryDuration": "PT15M", "ExperimentDuration": "PT15M", "ConcurrentQueries": "3", "LongQueryThresholdSeconds": "60", "MinLongQueriesObserved": "1", "CpuWorkUnits": "2000000", "TargetTableName": "", "ScanRowCount": "500000", "SubnetId": "subnet-1234-abcdef", "VpcId": "vpc-1234567abcd", "DatabaseSecurityGroupId": "sg-1234567abcd", "InstanceType": "t3.small"}
  6. **Note** there is no target defined in the FIS experiment template since this is managed through the SSM Automation document and the Document parameters you just entered, so **do not amend the target section of the template**
  7. Select **Save** and then **Update experiment template**
  8. You can now **Start experiment**

## Where to Look While It Runs

The point of the experiment is what your monitoring does, so watch these during the run. The marker in the output (`FIS-SLOW-QUERY-<suffix>`) appears in the statement text and the client application name, so you can search for it directly.

| Surface | PostgreSQL | MySQL | SQL Server | Oracle |
|---|---|---|---|---|
| Session view | `pg_stat_activity` (`state='active'`, `query_start`) | `information_schema.PROCESSLIST` (`TIME`) | `sys.dm_exec_requests` (`start_time`) | `v$session` (`last_call_et`) |
| Slow query log | `log_min_duration_statement` | slow query log, `long_query_time` | n/a - use Extended Events | n/a - use AWR / `v$sql` |
| Performance Insights | Top SQL by load | Top SQL by load | Top SQL by load | Top SQL by load |
| CloudWatch | `CPUUtilization`, `DatabaseConnections` | same | same | same |

Two findings worth expecting, both specific to the `sleep` pattern:

- **Performance Insights may show `sleep` as near-zero load**, because it is waiting, not working. If your detection relies on PI load, a waiting query can hide from it.
- **The slow query log may omit `sleep` too.** MySQL's `min_examined_row_limit` filters out statements that examine no rows, which is true of `SLEEP()`.

The `realistic` pattern is designed to avoid both: it examines real rows and performs a real scan, so it should appear in the slow query log and register load in Performance Insights while still running for exactly `QueryDuration`. **If `realistic` is detected and `sleep` is not, that is a genuine gap in your coverage, not a flaw in the experiment** - it means a query that waits without working goes unseen.

### How `realistic` is built per engine

| Engine | Statement shape |
|---|---|
| PostgreSQL | `WITH scan AS (SELECT count(*) ... FROM <source> src) SELECT rows_examined, pg_sleep(n) FROM scan` |
| MySQL | `SELECT s.rows_examined, SLEEP(n) FROM (SELECT COUNT(*) ... FROM <source> src) s` |
| SQL Server | `SELECT COUNT_BIG(*) FROM <source> src; WAITFOR DELAY 'hh:mm:ss'` - a two-statement batch, since SQL Server has no sleep expression usable inside a `SELECT`. `sys.dm_exec_requests` times the whole batch, so the reported duration still covers scan plus wait |
| Oracle | `SELECT (SELECT COUNT(*) FROM <source> src) AS rows_examined, DBMS_PIPE.RECEIVE_MESSAGE('<marker>', n) AS waited FROM dual` - a single SQL statement. Falls back to a PL/SQL block if `DBMS_PIPE` is not executable, see below |

`<source>` is `TargetTableName` when set, otherwise a synthetic row source: `generate_series` (PostgreSQL), `information_schema.COLUMNS` (MySQL), a `TOP (ScanRowCount)` cross join of `sys.all_objects` (SQL Server), or `CONNECT BY LEVEL` (Oracle).

#### Oracle: why a single SQL statement matters

An anonymous PL/SQL block is hard to recognise as a slow query. `v$sql`, `v$session.sql_id` and AWR's *SQL ordered by Elapsed Time* all attribute the time to the block, not to a `SELECT` anyone would recognise, so a reviewer sees a long-running *session* rather than a long-running *query*.

`DBMS_SESSION.SLEEP` is a procedure and cannot be called from SQL, but **`DBMS_PIPE.RECEIVE_MESSAGE` is a function**, so it can. The experiment uses it to put the wait inside the statement itself: the scan runs as a scalar subquery and the wait happens in the same `SELECT`, giving the fault its own `SQL_ID` and a real elapsed time wherever SQL is ranked by duration.

The experiment probes for this at startup with a zero-timeout call and reports which form it chose:

```
Statement form: single SQL statement (DBMS_PIPE.RECEIVE_MESSAGE is executable), so the
fault has its own SQL_ID and elapsed time in v$sql and AWR
```

If `DBMS_PIPE` is not executable by `DatabaseUser` it falls back to the PL/SQL block and says so, recommending `GRANT EXECUTE ON SYS.DBMS_PIPE`. The fault is still injected either way and the session is `ACTIVE` for the full duration, so session-view monitoring works in both forms - only top-SQL attribution differs. The chosen form is reported as `OracleSingleStatementForm` in the output JSON.

**One caveat specific to this technique.** Waiting on a pipe is an *idle* wait class event (`pipe get`), so Active Session History and Performance Insights may not attribute DB load to it even though the statement's elapsed time is long. That makes the Oracle `realistic` pattern an excellent test of elapsed-time-based detection and a poor test of load-based detection. If you need Oracle to register as load, use `QueryPattern=cpu`, which does real work and appears in ASH and Performance Insights normally.

Note for SQL Server: because the statement is a two-statement batch, top-SQL views may attribute the time to the batch rather than to the inner `SELECT`. The session stays active for the full duration, so session-view monitoring is unaffected.

### How the cpu pattern reaches an exact duration

`cpu` runs a **single statement that is both long and CPU-bound**, for about `QueryDuration`. It does that without any clock trickery:

1. One **burn unit** is a bounded piece of CPU work - an inner row source of `CpuWorkUnits` rows, each doing a hash over a few kilobytes.
2. At startup the experiment **times that burn unit** over several iterations, then computes how many repeats fill `QueryDuration`.
3. The statement is the burn unit repeated that many times by a bounded outer row source.

The inner subquery is **correlated on the outer row** (`g + i`, `g + o.i`) so the planner cannot cache it and evaluate it once. Every row source is bounded, so memory stays flat however long the query runs.

Measured end to end, asking for a 300s query:

| Engine | Burn unit | Iterations | Delivered | Accuracy | Database CPU |
|---|---|---|---|---|---|
| Aurora PostgreSQL 17.7 (db.t3.medium) | 100,000 units = 0.71s | 421 | **293.7s** | 98% | 29.5% on 2 vCPU |
| RDS Oracle 19c | 100,000 units = 2.09s | 143 | **299.7s** | 99.9% | ~27% sustained |

`FreeLocalStorage` on the Aurora instance stayed flat at 7.51 GiB across the whole run - no temp spill.

**`CpuWorkUnits` controls granularity, not duration.** Aim for a burn unit of roughly half a second to a second. Too small and calibration is unreliable; too large and the query overshoots by up to one unit. If the unit comes out too short the experiment grows it automatically and reports each attempt; if growing it trips a resource limit it falls back to the last size that worked.

**SQL Server is excluded** from the calibrated form: repeating its burn means scaling `TOP`, which rebuilds the unbounded row source this design exists to avoid. Its `cpu` duration comes from `CpuWorkUnits` alone, and it says so at runtime.

#### Why it is built this way

Two simpler designs were tried first and both failed against real databases, which is worth recording:

- **An unbounded row source with a per-row clock predicate.** A PostgreSQL function scan materialises its output into a tuplestore, so an effectively unbounded `generate_series` wrote temp files until local storage ran out - it took a db.t3.medium from 7.51 GiB free to 0.70 GiB in under a minute and died with `could not write to file "base/pgsql_tmp/...": No space left on device`. The cluster recovered fully, but this is a real hazard, not a theoretical one.
- **A clock predicate on Oracle.** `DBMS_UTILITY.GET_TIME` is evaluated once per statement rather than per row, so the filter collapses to a constant and the query returns an empty result instantly.

Two calibration subtleties also came out of testing:

- The same `CpuWorkUnits` gave a 0.71s burn on Aurora PostgreSQL and **0.02s** on RDS Oracle - 35x apart - which is why the unit is grown automatically rather than trusted as given.
- Timing a *standalone* burn overestimates its cost in bulk: 0.51s standalone on Oracle against 0.39s per iteration inside the repeated statement, a 24% bias that landed the query at 75% of target. Calibration therefore times several iterations and divides.

Oracle's row generation is also memory-bound and plan-sensitive: a 3M-level `CONNECT BY` survived a 585-iteration outer but raised `ORA-30009` on a 4-iteration one, because the optimiser unnested it into a join and materialised the lot. Keeping the row count small and the per-row work heavy avoids that, which is why the burn unit ceiling is deliberately low.

Keep `ConcurrentQueries` low with `cpu`: each query saturates roughly one core, so three concurrent queries on a 2-vCPU instance will peg the database.

## Stop Conditions

The experiment template does not have any specific stop conditions defined by default. It will continue to run until the query phase completes, a step fails, or it is manually stopped via the FIS console/API. Stopping the experiment triggers the termination step, so in-flight queries are killed rather than left running.

Stop conditions are based on an AWS CloudWatch alarm based on an operational or
business metric requiring an immediate end of the fault injection. This
template makes no assumptions about your application and the relevant metrics
and does not include stop conditions by default.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. **Start Small**: One concurrent query and a short `QueryDuration` (PT2M or so) to confirm the whole path including termination, then raise `QueryDuration` to PT15M or beyond for a realistic test
2. **Measure Detection Lead Time**: Note the query start time from the output and compare against when your alarm fired. That gap is your real detection latency, and it is the single most useful number this experiment produces
3. **Probe the Threshold**: Run at `QueryDuration` just under and just over your alarm threshold. Only one should fire. If both or neither do, the threshold is not where you think it is
4. **Run All Three Patterns**: `realistic` should be caught by everything; `sleep` tests whether detection survives a query that waits without working; `cpu` adds genuine CPU load for the full duration so it should trip load-based detection too. Most gaps show up as "we only detect the expensive ones"
5. **Check the Alert Payload**: Can the on-call engineer identify the statement from the notification alone? If they would have to go digging, add the statement text and session to the alarm
6. **Add Stop Conditions**: Tie a CloudWatch alarm on a business metric to the template so a real customer impact halts the run
7. **Watch for Timeouts**: If the output reports queries cancelled well short of target, a server-side statement timeout is already truncating them. Decide whether that limit is the one you want, and note that it also caps how slow a real runaway query can get
8. **Implement Safeguards**: Ensure your platform has a statement timeout set deliberately rather than by accident, query-level monitoring independent of CPU, and a documented procedure for identifying and terminating a runaway query

## Import Experiment
You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
