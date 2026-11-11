# AWS Fault Injection Service Experiment: Database Space Exhaustion

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

When {service1} database storage consumption grows towards the provisioned limit, users of {workload} should be able to complete the {service1} user journey within the SLA of 2 seconds and other critical user journeys relating to {workload}; {service2} and {service3} should continue unaffected. The steady state of {n} transactions per second should be maintained. A leading alarm on free storage space should be raised and the DevOps team notified within {y} minutes, with enough headroom remaining for the team to act before writes are refused.

When {service1} database storage is effectively exhausted, the {workload} {service1} write paths should fail fast with a clear error rather than hanging or corrupting data, and read paths should continue to serve traffic. The {workload} UI should indicate degraded functionality to users. An alarm should be raised and the DevOps team notified within {y} minutes. Other critical user journeys relating to {workload}; {service2} and {service3} should continue unaffected. Once the consumed space is released, the database should accept writes again within {z} minutes and the steady state of {n} transactions per second should resume without manual intervention.

### What does this enable me to verify?

* Appropriate observability of your database storage is in place (were you able to detect space running out before it ran out?)
* Alarms are configured correctly for storage metrics (`FreeStorageSpace`, `FreeLocalStorage`, `VolumeBytesUsed`) with enough lead time to act
* Storage autoscaling behaves as you expect - does it expand in time to keep writes flowing, does it stop at the ceiling you set, and do you know what the expansion costs? (see "Storage autoscaling will consume more space than you asked for" below)
* Your app degrades gracefully when writes are refused rather than failing in ways that lose or corrupt data
* Your runbook for reclaiming space works, and recovery is as fast as you assume

## Description

This experiment tests your application's resilience to database storage space exhaustion by:

1. **Preflight checking** the target's free storage (optional, RDS instances only) and refusing to run if the requested space would not fit within a safety margin
2. **Dynamically creating** an ephemeral EC2 instance as a load generator
3. **Bootstrapping** the instance with the appropriate database client (PostgreSQL, MySQL, SQL Server, or Oracle)
4. **Filling** the database with a user-specified amount of incompressible data, spread evenly across concurrent worker threads, each writing into its own table
5. **Verifying** the space was actually consumed by measuring real table sizes in the database catalogue, and failing the experiment if the target was not reached
6. **Holding** the exhausted-space condition for a user-specified duration, so you can observe your alarms, dashboards, and application behaviour
7. **Reclaiming** the space by dropping every table this execution created, then terminating the load generator instance

The two parameters you are most likely to change are:

- **`TargetSpaceGB`** - how much space to consume
- **`ExperimentDuration`** - how long to hold that space once it has been written

The experiment is **parameterized by database engine**, targeting these engines in RDS:
- Aurora PostgreSQL - validated end-to-end
- RDS PostgreSQL - validated end-to-end
- RDS Oracle - validated end-to-end
- Aurora MySQL - **experimental**, not yet validated end-to-end (client install, driver connect, and `executemany` fill are unexercised)
- RDS MySQL - **experimental**, not yet validated end-to-end
- RDS SQL Server - **experimental**, not yet validated end-to-end

Before relying on the MySQL or SQL Server paths, run a small `TargetSpaceGB`/short-`ExperimentDuration` smoke test against your target engine first.

### Storage autoscaling will consume more space than you asked for

**Read this before choosing `TargetSpaceGB`.** If storage autoscaling is enabled on the target, this experiment will probably not exhaust anything - it will trigger a volume expansion instead, and that expansion costs money you keep paying after the experiment ends.

**RDS storage autoscaling** (the *Enable storage autoscaling* checkbox, `MaxAllocatedStorage` in the API) expands the volume when all of the following hold:

- Free space drops below 10% of allocated storage - which is exactly what this experiment is designed to cause
- That low-storage condition persists for at least 5 minutes - which is why a long `ExperimentDuration` makes expansion far more likely than a short one
- At least 6 hours have passed since the last storage modification

When it fires, RDS grows the volume by **whichever is largest** of: 10 GiB, 10% of current allocated storage, or its prediction of the next 7 hours of growth based on the recent `FreeStorageSpace` trend. That last term is the one that bites here: the fill phase writes fast, so the predicted growth is extrapolated from an aggressive write rate and the increase can be **considerably larger than `TargetSpaceGB`**. Expansion stops at your *Maximum allocated storage* ceiling.

The expansion is **not reversible**. RDS does not support decreasing allocated storage - undoing it means a snapshot restore or migration to a new instance. You pay for the larger volume until you do that.

Two further consequences worth planning around:

- The **6-hour cooldown** means consecutive runs of this experiment behave differently. The first run may expand the volume; a run in the next 6 hours cannot expand and so may genuinely exhaust storage instead. Do not assume the second run is as safe as the first.
- The **preflight check measures current free space, not the autoscaling ceiling**. With autoscaling enabled, the preflight may abort a run that autoscaling would have absorbed comfortably. That is deliberate - it fails closed.

**Aurora** grows its cluster volume automatically in 10 GiB increments up to the engine maximum, with no setting to disable and no maximum you control. On Aurora you cannot test storage exhaustion with this template at any realistic `TargetSpaceGB`; what you can test is write latency under heavy ingest, your storage-growth alarming, and your cost controls. Treat `TargetSpaceGB` on Aurora as primarily a **cost** decision.

#### Deciding what to do about it

| Your goal | What to do |
|---|---|
| Test that free-storage alarms fire with enough lead time | Leave autoscaling enabled. Keep `TargetSpaceGB` modest and accept that a volume expansion may occur |
| Test true storage exhaustion and write refusal | **Disable storage autoscaling on the target first** (or clear `MaxAllocatedStorage`), on a non-production instance you can rebuild. This is the only way to reliably reach the exhausted state on RDS |
| Test that autoscaling itself works and you can afford it | Leave it enabled, set a deliberately low *Maximum allocated storage*, and watch whether expansion keeps ahead of the fill rate |

Check the current setting before you run:

```
aws rds describe-db-instances \
  --db-instance-identifier <YOUR DB INSTANCE IDENTIFIER> \
  --query 'DBInstances[0].{Allocated:AllocatedStorage,MaxAutoscale:MaxAllocatedStorage,Type:StorageType}'
```

A `MaxAutoscale` of `null` means autoscaling is off and `TargetSpaceGB` is bounded only by `AllocatedStorage`. Any number means autoscaling is on, and that number is your real ceiling.

### Transaction logs mean total growth exceeds TargetSpaceGB

`TargetSpaceGB` controls the size of the **table data** written. Every engine also writes that data into its write-ahead/transaction log, so the storage actually consumed during the fill phase is **larger than `TargetSpaceGB`** - often close to double, and more if log retention is generous:

- **PostgreSQL / Aurora PostgreSQL** - WAL segments, retained until archived and past your backup retention window
- **MySQL / Aurora MySQL** - InnoDB redo log plus the binary log if binlogging is on (it is, if you use read replicas or CDC)
- **SQL Server** - the transaction log, which under the default FULL recovery model grows roughly in step with the data written and is only truncated by a log backup
- **Oracle** - redo plus archived redo logs in `FRA`, which has its own `db_recovery_file_dest_size` limit that can fill *before* your tablespace does

Budget for this in `FreeSpaceSafetyMarginPercentage`. The 20% default is a reasonable floor, not a generous one; if you are writing a large fraction of your free space, raise it.

### What happens to the space afterwards

The data written by this experiment is dropped in the `ReclaimDatabaseSpace` step, which runs on the normal path, on failure of the fill phase, and on cancellation. Afterwards:

**Dropping the tables does not reliably give the storage back to the platform.** The automation reporting that it dropped the tables is not the same as `FreeStorageSpace` recovering, and on some engines it never will. Behaviour by engine:

- **RDS PostgreSQL** - each table is backed by its own files, which are deleted on `DROP TABLE`, so `FreeStorageSpace` does recover, typically within minutes
- **RDS Oracle** - **`FreeStorageSpace` does not recover.** `DROP TABLE ... PURGE` frees the segments *inside* the tablespace, so Oracle will reuse that space for future growth, but the datafile keeps its high-water mark and never shrinks on its own. From the platform's point of view the space stays consumed. Returning it to the filesystem requires an explicit datafile shrink/resize, which this template deliberately does not attempt. Measured on a 2 GiB run against RDS Oracle 19c: `FreeStorageSpace` fell 110.65 GiB -> 108.48 GiB and stayed there after the reclaim step reported success
- **RDS MySQL** - recovery depends on `innodb_file_per_table` (see the MySQL engine notes). With it ON the tablespace file is deleted and space returns; with it OFF the shared tablespace keeps the high-water mark, like Oracle
- **RDS SQL Server** - the data file keeps its allocated size after the drop, and the transaction log keeps whatever it grew to until a log backup truncates it. Expect partial recovery at best
- **Aurora** - current engine versions perform dynamic volume resizing, so `VolumeBytesUsed` should fall back after the tables are dropped, but not instantly. Note that `VolumeBytesUsed` publishes infrequently - on a test cluster it was observed lagging by over two hours, long enough that a short run finishes before the metric ever reflects it. Do not treat a flat `VolumeBytesUsed` as proof of anything either way; check again later

On top of all of this, transaction log and archived redo space is reclaimed on the engine's own backup schedule, not when the tables are dropped - so free space can keep *falling* for a few minutes after the experiment reports success. Any **autoscaling expansion that happened during the run is never reversed** (see above).

The practical consequence: **budget `TargetSpaceGB` as space you may not get back**, especially on Oracle and MySQL-without-file-per-table. Re-running the experiment repeatedly on the same instance ratchets consumption upward even though every run cleans up after itself.

## Architecture Overview

```
FIS Experiment
    ↓
SSM Automation Document
    ↓
1. Preflight: if RdsInstanceIdentifier is supplied, read AWS/RDS
   FreeStorageSpace and abort if TargetSpaceGB would not fit within
   FreeSpaceSafetyMarginPercentage
    ↓
2. Create temporary security group in VPC
    ↓
3. Revoke the security group's default allow-all egress rule, then add egress
   rules: Load generator → Database port, and Load generator → HTTPS (443)
   for SSM, Secrets Manager, and package repositories
    ↓
4. Add ingress rule: Database SG ← Load generator SG (database SG must be
   tagged FIS-Ready=True)
    ↓
5. Launch EC2 instance (Amazon Linux 2023) with new SG
    ↓
6. Wait for SSM Agent to be online
    ↓
7. Install database client (psql/mysql/sqlcmd/sqlplus)
    ↓
8. Fill phase: N worker threads each write TargetSpaceGB / N of incompressible
   data into their own table, bounded by FillTimeout
    ↓
9. Measure the space actually consumed from the database catalogue and fail the
   automation if less than MinSpaceAchievedPercentage of the target was reached
    ↓
10. Hold phase: keep the space consumed for ExperimentDuration
    ↓
11. Reclaim: drop every table matching this execution's prefix
    ↓
12. Terminate EC2 instance
    ↓
13. Revoke ingress rule from database SG (idempotent - runs even if the load
    generator failed to launch)
    ↓
14. Delete temporary security group
```

## Prerequisites

Before running this experiment, ensure that:

1. **VPC Configuration**:
   - You have a VPC with at least one subnet that can reach your database
   - You know the VPC ID and subnet ID
   - You know the security group ID attached to your database
   - The subnet's route table and any VPC endpoints/NAT provide the load generator with outbound HTTPS (443) connectivity to:
     - Amazon SSM and SSM Messages endpoints (required for the SSM Agent and Run Command)
     - AWS Secrets Manager (to retrieve the database password)
     - Amazon Linux package repositories (`dnf`) and PyPI (for `pip3` installs)
     - `packages.microsoft.com` (SQL Server engine only - mssql-tools repo)
     - `download.oracle.com` (Oracle engine only - Instant Client RPMs)
   - The temporary security group's egress is restricted to the database port and HTTPS (443) only - see "How It Works" Phase 2 below

2. **Database Configuration**:
   - Supported database is running (Aurora PostgreSQL, RDS PostgreSQL, and RDS Oracle are validated end-to-end; Aurora MySQL, RDS MySQL, and RDS SQL Server are experimental - see Description above)
   - You know the database endpoint, username, and password
   - The database user has permissions to CREATE and DROP tables, and a tablespace/schema quota large enough for `TargetSpaceGB` (Oracle in particular will raise ORA-01536 if the user's quota is lower than the target)
   - The database security group (`DatabaseSecurityGroupId`) is tagged `FIS-Ready=True` - the SSM automation role's IAM policy only permits ingress changes on security groups carrying this tag

3. **Storage Headroom**:
   - You have decided how much space to consume and confirmed the target can absorb it. For RDS instances, supply `RdsInstanceIdentifier` so the automation performs the free-storage preflight check for you
   - **You have checked whether storage autoscaling is enabled on the target** (`MaxAllocatedStorage` on the DB instance) and decided what you want to happen. If it is enabled, expect a volume expansion larger than `TargetSpaceGB` that you cannot reverse and will keep paying for; if you want to test genuine exhaustion, disable it first. See "Storage autoscaling will consume more space than you asked for" above for the mechanics, the cost consequences, and a decision table
   - You have budgeted for transaction log growth on top of `TargetSpaceGB` - see "Transaction logs mean total growth exceeds TargetSpaceGB" above

### Create Required Experiment Resources

1. **Experiment template**:
   - Import the FIS experiment template (`database-space-exhaustion-experiment-template.json`) into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).

2. **IAM Roles**: Create the following IAM roles in your account using the sample policies provided:
   - FIS execution role (`DatabaseSpaceExhaustion-FIS-Role`) with permissions to start SSM automation (`database-space-exhaustion-fis-role-iam-policy.json`)
   - SSM automation role (`DatabaseSpaceExhaustion-SSM-Automation-Role`) with permissions to launch EC2 instances, execute commands, and read CloudWatch metrics for the preflight check (`database-space-exhaustion-ssm-automation-role-iam-policy.json`)
   - EC2 instance role (`SSM-Managed-Instance-Profile-Role`, attached via instance profile `SSM-Managed-Instance-Profile`) with the `AmazonSSMManagedInstanceCore` managed policy **and** `database-space-exhaustion-ec2-instance-role-iam-policy.json`
     - **Important**: the load generator retrieves the database password via `boto3.get_secret_value()` inside the `AWS-RunShellScript` command, which runs under this EC2 instance role - not the SSM automation role. Secrets Manager (and KMS, if the secret uses a customer-managed key) permissions belong here, scoped to your specific secret ARN
   - **Note**: this template hardcodes the role/document names above (the automation document's `assumeRole` and the FIS action's `documentArn`/`roleArn` reference them directly). Create the roles with these exact names, or update `database-space-exhaustion-automation.yaml` and `database-space-exhaustion-experiment-template.json` consistently if you rename them.

3. **SSM Document**:
   - Deploy the SSM automation document (`database-space-exhaustion-automation.yaml`) to your account, naming it `DatabaseSpaceExhaustion-Automation`

## Parameters

The experiment requires the following parameters:

### Database Configuration
- **DatabaseEngine**: `postgres`, `mysql`, `sqlserver`, or `oracle` (default: `postgres`)
- **DatabaseEndpoint**: Database DNS hostname or endpoint
- **DatabasePort**: Database port (default: 5432 for PostgreSQL, use 3306 for MySQL, 1433 for SQL Server, 1521 for Oracle)
- **DatabaseName**: Database name (or service name for Oracle) to connect to. **Target a dedicated test database, not a system database** - do not point this at SQL Server's `master` or MySQL's `mysql` schema, since the experiment writes gigabytes into it
- **DatabaseUser**: Database username (default: `postgres`)
- **DatabasePasswordSecretArn**: ARN of Secrets Manager secret containing password

### Space and Duration Settings
- **TargetSpaceGB**: How much storage space to consume, in GiB, spread evenly across the worker threads (default: 10). **This is the size of the fault** - start small and increase it once you trust your observability
- **ExperimentDuration**: How long to hold the exhausted-space condition once `TargetSpaceGB` has been written, in ISO8601 format (default: PT10M = 10 minutes). This is the **hold phase only**; the fill phase runs before it and is bounded separately by `FillTimeout`. **Keep `FillTimeout` + `ExperimentDuration` well under PT170M**: the FIS action's `maxDuration` is fixed at PT180M (3h), and client install plus the reclaim phase also consume part of that budget
- **WorkerThreads**: Number of concurrent worker threads writing data (default: 5). Each worker fills its own table with `TargetSpaceGB / WorkerThreads`. More workers fill faster but put more concurrent write pressure on the database
- **RowSizeMB**: Size in MiB of the binary payload written per row (default: 1). Larger rows fill space with fewer statements; smaller rows produce more row-level churn
- **FillTimeout**: Maximum time allowed for the fill phase in ISO8601 format (default: PT30M). If the target has not been written by then, workers stop filling and the achieved space is checked against `MinSpaceAchievedPercentage`. Budget roughly 1 minute per GiB per worker as a conservative starting point, then tune from your first run
- **MinSpaceAchievedPercentage**: Minimum percentage of `TargetSpaceGB` that must actually be measured as consumed for the experiment to be treated as a successful fault injection (default: 90). If this threshold isn't met, the `FillDatabaseSpace` step - and the automation execution - fails. The space is still reclaimed

### Safety
- **RdsInstanceIdentifier**: Optional RDS DB instance identifier (default: empty). When supplied, the automation reads the `AWS/RDS` `FreeStorageSpace` metric before launching anything and aborts if `TargetSpaceGB` would not fit within the safety margin. It measures **currently free space, not the storage autoscaling ceiling**, so with autoscaling enabled it may abort a run that autoscaling would have absorbed - it fails closed by design. **Leave empty for Aurora**, which does not publish `FreeStorageSpace`
- **FreeSpaceSafetyMarginPercentage**: Percentage of currently free storage that must remain free after writing `TargetSpaceGB` (default: 20). Only applied when `RdsInstanceIdentifier` is supplied

### Infrastructure
- **SubnetId**: Subnet ID where load generator will be launched
- **VpcId**: VPC ID where the load generator will be launched (used to create security group)
- **DatabaseSecurityGroupId**: Security group ID of the target database, must be tagged `FIS-Ready=True` (automation will add temporary ingress rule)
- **InstanceType**: EC2 instance type for Load Generator (default: t3.medium - use a network-optimised type such as m5.large or larger when writing tens of GiB, since fill speed is bound by instance network throughput)

## Engine-Specific Details

All four engine paths are implemented in `database-space-exhaustion-automation.yaml`, in the `fill_worker_<engine>` functions of the `FillDatabaseSpace` step and the `reclaim_<engine>` functions of the `ReclaimDatabaseSpace` step. This section documents what each one actually does, so you can review or adapt an engine path without running it.

| | PostgreSQL | MySQL | SQL Server | Oracle |
|---|---|---|---|---|
| Status | Validated | **Experimental** | **Experimental** | Validated |
| Default port | 5432 | 3306 | 1433 | 1521 |
| Client installed | `postgresql15`, `psycopg2-binary` | `mariadb105`, `mysql-connector-python` | `mssql-tools18`, `unixODBC-devel`, `pyodbc` | Instant Client 23.4 RPMs, `oracledb` |
| Payload column | `BYTEA` + `STORAGE EXTERNAL` | `LONGBLOB` | `VARBINARY(MAX)` | `BLOB` |
| Space measured via | `pg_total_relation_size()` | `information_schema.tables` after `ANALYZE TABLE` | `sys.dm_db_partition_stats` | `user_segments` + `user_lobs` |
| Table discovery for reclaim | `pg_tables` | `information_schema.tables` | `sys.tables` | `user_tables` |
| Drop statement | `DROP TABLE IF EXISTS` | `DROP TABLE IF EXISTS` | `DROP TABLE IF EXISTS` | `DROP TABLE ... PURGE` |

Common to every engine: each worker owns one table named `fis_sp_<execution-suffix>_<thread_id>`, writes `os.urandom` payloads of `RowSizeMB` in batches capped at roughly 16 MiB, and stops after about 10 insert errors so a database that has genuinely stopped accepting writes ends the fill phase rather than spinning.

### PostgreSQL and Aurora PostgreSQL (validated)

The payload column is set to `STORAGE EXTERNAL` immediately after table creation. Without this, TOAST would try to compress the payload - harmless for random bytes, but the explicit setting means the bytes written are the bytes stored regardless of future defaults. `pg_total_relation_size()` includes the TOAST table and indexes, so the measured figure is a true total. Because the reclaim phase drops tables rather than deleting rows, no vacuum is needed to return the space.

### MySQL and Aurora MySQL (experimental - unvalidated)

Unexercised in this template: the client install, the driver connect, and the `executemany` fill path. `mysql-connector-python` rewrites `executemany` into a single multi-row `INSERT`, so each batch is one large statement.

Specific things to expect:

1. **Measurement is an estimate.** `information_schema.tables.data_length + index_length` is an InnoDB approximation derived from sampled statistics, and can be off by several percent in either direction even straight after `ANALYZE TABLE`. The default `MinSpaceAchievedPercentage` of 90 can therefore fail a run that actually worked. **Set `MinSpaceAchievedPercentage` to 80 for your first MySQL run** and compare the reported `SpaceConsumedBytes` against `FreeStorageSpace` to calibrate.
2. **`innodb_file_per_table` must be ON** (the default on RDS and Aurora MySQL). If it is OFF, the data lands in the shared tablespace, and `DROP TABLE` returns the space to that tablespace without ever returning it to the filesystem - the reclaim phase will report success while `FreeStorageSpace` stays flat. Verify with `SELECT @@innodb_file_per_table;` before running.
3. **`max_allowed_packet` is not a concern at default settings.** Batches are capped at ~16 MiB by construction, well under the 64 MiB default. It only becomes a risk if you set `RowSizeMB` above roughly 60, since a single row is never split across statements. The symptom would be `ER_NET_PACKET_TOO_LARGE` or an abrupt "Lost connection to MySQL server during query".
4. **Binary logging doubles the write volume** if it is enabled (it is, if you use read replicas, blue/green, or CDC). See the transaction-log section above.

### SQL Server (experimental - unvalidated)

Unexercised in this template: the `mssql-tools18` install, the ODBC Driver 18 connect, and the `fast_executemany` fill path.

Specific things to expect:

1. **`fast_executemany` with `VARBINARY(MAX)` is the most likely failure point.** The fill worker sets `cursor.fast_executemany = True`, which makes pyodbc pre-bind parameters to the column's declared width; this is a well-known source of errors against `MAX` types, typically surfacing as a truncation error, an `HY010` function-sequence error, or heavy memory use on the load generator. **If the SQL Server fill phase fails, the first thing to try is deleting the `cursor.fast_executemany = True` line** from `fill_worker_sqlserver` in `database-space-exhaustion-automation.yaml`. The fill will be slower but should work.
2. **Do not point `DatabaseName` at `master`.** Create a dedicated test database on the instance and target that. Writing gigabytes into `master` is poor practice and makes the result harder to interpret.
3. **`DROP TABLE IF EXISTS` requires SQL Server 2016 (13.x) or later.** On an earlier version the reclaim phase will fail with a syntax error and leave the data in place; replace it with the `IF OBJECT_ID('<table>', 'U') IS NOT NULL DROP TABLE <table>` form in `reclaim_sqlserver`.
4. **The FULL recovery model is the RDS default**, so the transaction log grows roughly in step with the data written and is only truncated by a log backup. Expect total space consumption near double `TargetSpaceGB`, and expect the log *not* to shrink back when the tables are dropped.
5. **Data file autogrowth is a second ceiling inside the RDS volume.** If the data file cannot grow you get error 1105, "Could not allocate space ... filegroup is full" - which is arguably the cleanest exhaustion signal of any of these engines, and a good thing to assert your application handles.
6. `reserved_page_count` counts allocated-but-unused pages, so the measured figure can slightly overstate the payload. This makes the `MinSpaceAchievedPercentage` check more lenient, not less, so the default of 90 is safe here.

### Oracle (validated)

Table creation runs inside a PL/SQL block that tolerates ORA-00955 (name already used), so a retry cannot fail on an existing table. Payloads are bound with `setinputsizes(oracledb.BLOB)`, which is required for LOB `executemany` to work. Space is measured by summing `user_segments` for the table, its LOB segment, and its LOB index - a BLOB column stores almost everything outside the table segment, so counting the table segment alone would report close to nothing.

Specific things to expect:

1. **The database user needs a tablespace quota of at least `TargetSpaceGB`.** Without it the fill fails with ORA-01536, "space quota exceeded for tablespace". Grant with `ALTER USER <user> QUOTA <n>G ON <tablespace>;` or `QUOTA UNLIMITED`.
2. **`DROP TABLE ... PURGE` is deliberate.** A plain `DROP TABLE` moves the segments to the recycle bin and frees no space at all, which would leave the fault injected after the experiment reported success.
3. **Even with `PURGE`, `FreeStorageSpace` will not recover.** The segments are freed inside the tablespace and Oracle will reuse them, but the datafile does not shrink, so the platform still sees the space as used. This is expected Oracle behaviour, not a cleanup failure - verified on a 2 GiB run where free space fell 110.65 GiB -> 108.48 GiB and stayed there. Plan `TargetSpaceGB` on Oracle as space you are spending, not borrowing, and do not use `FreeStorageSpace` recovery as your check that cleanup worked - check that no `FIS_SP_%` tables remain instead.
3. **The Fast Recovery Area can fill before your tablespace does.** Archived redo for the fill phase lands in the FRA, bounded by `db_recovery_file_dest_size`. Hitting that limit stalls the database in a way that looks like, but is not, the fault you intended to inject.
4. The 30-character identifier limit on older Oracle versions is why the table prefix is kept short (`fis_sp_` plus 8 characters of execution ID).

### Smoke-testing an unvalidated engine path

Before trusting MySQL or SQL Server, run the whole automation small, on a throwaway instance, and check the reclaim actually happened:

```
TargetSpaceGB=1  WorkerThreads=2  RowSizeMB=1
ExperimentDuration=PT1M  FillTimeout=PT10M  MinSpaceAchievedPercentage=50
```

Then confirm three things: the `FillDatabaseSpace` step output JSON reports `FaultInjected: true` with a plausible `SpaceConsumedBytes`, the `ReclaimDatabaseSpace` step lists the tables it dropped, and no table matching `fis_sp_%` remains in the database. If all three hold, scale `TargetSpaceGB` up.

## Executing the Experiment
- Once the FIS Experiment template is deployed in your account, you will need to **update the experiment template** by editing it in the console or via the API to set appropriate parameters for your desired database target and environment
- To update via the console:
  1. Open the FIS Console
  2. Select the experiment template "Database-space-exhaustion"
  3. Select **Actions / Update Experiment Template**
  4. Select the **ExhaustDatabaseSpace** Action
  5. Update the **Document parameters** to match your target e.g. {"DatabaseEngine": "postgres", "DatabaseEndpoint": "database-1.cluster-1234abcde.eu-west-1.rds.amazonaws.com", "DatabasePort": "5432", "DatabaseName": "postgres", "DatabaseUser": "postgres", "DatabasePasswordSecretArn": "arn:aws:secretsmanager:eu-west-1:123456789012:secret:rds!cluster-xxxx", "TargetSpaceGB": "10", "ExperimentDuration": "PT10M", "WorkerThreads": "5", "RowSizeMB": "1", "FillTimeout": "PT30M", "MinSpaceAchievedPercentage": "90", "RdsInstanceIdentifier": "", "FreeSpaceSafetyMarginPercentage": "20", "SubnetId": "subnet-1234-abcdef", "VpcId": "vpc-1234567abcd", "DatabaseSecurityGroupId": "sg-1234567abcd", "InstanceType": "t3.medium"}
  6. **Note** there is no target defined in the FIS experiment template since this is managed through the SSM Automation document and the Document parameters you just entered, so **do not amend the target section of the template**
  7. Select **Save** and then **Update experiment template**
  8. You can now **Start experiment**

## How It Works

### Phase 1: Preflight (seconds)
1. If `RdsInstanceIdentifier` is supplied, reads the most recent `AWS/RDS` `FreeStorageSpace` datapoint for that instance and calculates the usable free space as `free × (1 - FreeSpaceSafetyMarginPercentage / 100)`. If `TargetSpaceGB` exceeds that figure, the automation aborts immediately - before any EC2 instance or security group is created. If the identifier is empty the check is skipped, and `TargetSpaceGB` alone bounds the fault

### Phase 2: Infrastructure Creation (2-3 minutes)
2. Creates a temporary security group in your VPC with name `FIS-DatabaseSpace-LoadGen-<execution-id>`, tagged `ManagedBy=FIS-SSM-Automation` and `FIS-Experiment=DatabaseSpaceExhaustion`
3. Revokes the security group's default allow-all outbound rule, then adds explicit egress rules: load generator → database port, and load generator → HTTPS (443) for SSM, Secrets Manager, and package repositories. The load generator's outbound access is **not** unrestricted - only these two rules exist afterward
4. Adds ingress rule to the database security group allowing traffic from the load generator (requires the database security group to be tagged `FIS-Ready=True`)
5. Launches an EC2 instance in your specified subnet with the new security group
6. Instance is tagged with `FIS-Experiment=DatabaseSpaceExhaustion`, `ManagedBy=FIS-SSM-Automation`, and `AutoCleanup=true`
7. Waits for SSM Agent to report online status

### Phase 3: Bootstrap (1-2 minutes)
8. Installs appropriate database client based on `DatabaseEngine` parameter

### Phase 4: Fill (up to FillTimeout)
9. Retrieves the database password from Secrets Manager, using the **EC2 instance role** (not the SSM automation role) since this call runs inside the `AWS-RunShellScript` command on the load generator
10. Launches `WorkerThreads` concurrent threads, each:
    - Creating its own uniquely-named table (`fis_sp_<execution-suffix>_<thread_id>`, where `<execution-suffix>` is derived from the automation execution ID) - this guarantees no collision with pre-existing tables or tables from a concurrent run, and that cleanup only ever drops objects this execution created
    - Writing batched rows of `RowSizeMB` incompressible payload (`os.urandom`) until its share of `TargetSpaceGB` has been written or `FillTimeout` expires. Payloads are incompressible so engines with page or LOB compression still consume the full requested space; on PostgreSQL the payload column is additionally set to `STORAGE EXTERNAL` to bypass TOAST compression
    - Giving up after 10 consecutive-ish insert errors, so a database that has genuinely stopped accepting writes ends the fill phase rather than spinning
11. Measures the space actually consumed from the engine's own catalogue (`pg_total_relation_size`, `information_schema.tables`, `sys.dm_db_partition_stats`, `user_segments` + `user_lobs`) rather than trusting the bytes-written counter
12. Aggregates across workers and checks `MinSpaceAchievedPercentage`: if less than the required percentage of `TargetSpaceGB` was consumed (or nothing was consumed), the script exits non-zero and the automation reports failure rather than a false success. The reclaim step still runs

### Phase 5: Hold (Duration: ExperimentDuration)
13. Holds the consumed space in place for `ExperimentDuration`. Nothing is written or deleted during this window - it exists so you can watch your storage alarms fire, check your dashboards, and exercise your application against a database that is short of space

### Phase 6: Reclaim and Cleanup
14. Drops every table whose name matches this execution's prefix. Tables are **discovered from the database catalogue** rather than regenerated from the worker count, so a run that failed part-way through still has every table it created removed. This step is reached on the normal path, on fill-phase failure, and on cancellation
15. Terminates the EC2 instance
16. Waits for instance termination to complete
17. Revokes the ingress rule from the database security group - idempotent, and reached even if `LaunchLoadGenerator` itself failed, so a partially-created run never leaves an orphaned ingress rule blocking security group deletion
18. Deletes the temporary security group
19. Returns execution summary including bytes written, space measured as consumed, percentage of target achieved, and whether the fault was successfully injected

## Stop Conditions

The experiment template does not have any specific stop conditions defined by default. It will continue to run until the fill phase, hold phase, and reclaim phase complete, one of them fails, or it is manually stopped via the FIS console/API. Stopping the experiment manually triggers the reclaim phase, so the consumed space is released rather than left behind.

Stop conditions are based on an AWS CloudWatch alarm based on an operational or
business metric requiring an immediate end of the fault injection. This
template makes no assumptions about your application and the relevant metrics
and does not include stop conditions by default.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. **Start Small**: Begin with a `TargetSpaceGB` of 1-2 GiB and a short `ExperimentDuration` to validate the whole path - including reclaim - before consuming a meaningful fraction of your storage
2. **Monitor Key Metrics**: Watch these CloudWatch metrics during the experiment:
   ```
   - FreeStorageSpace (RDS)
   - FreeLocalStorage (Aurora)
   - VolumeBytesUsed / AuroraVolumeBytesLeftTotal (Aurora)
   - WriteIOPS / WriteThroughput / WriteLatency
   - DatabaseConnections
   ```
3. **Set a Leading Alarm**: Create a CloudWatch alarm on free storage with a threshold that leaves your team time to act, and use this experiment to confirm it fires early enough
4. **Add Stop Conditions**: Tie that alarm to the experiment template's stop conditions so a real impact on business metrics halts the fault automatically
5. **Use the Preflight**: Always set `RdsInstanceIdentifier` for RDS instance targets - it is the cheapest safeguard available and runs before any resource is created
6. **Watch the Cost Tail**: After the run, check `AllocatedStorage` on the instance (RDS) or `VolumeBytesUsed` (Aurora). On RDS, any autoscaling expansion the experiment triggered is permanent and cannot be reversed without a snapshot restore - confirm whether one happened, and factor it into whether you run this again on that instance
7. **Tune Fill Throughput**: If the fill phase hits `FillTimeout`, increase `WorkerThreads`, increase `RowSizeMB`, or move to a larger `InstanceType` - fill speed is usually bound by load generator network throughput, not the database
8. **Implement Safeguards**: Ensure your application and platform have:
   - Storage autoscaling or a documented, rehearsed procedure for extending storage
   - Alarming on free storage trend, not just an absolute floor
   - Retention and archival jobs that keep growth predictable
   - Write paths that fail fast and surface a clear error when the database refuses writes
9. **Rehearse Recovery**: Use the hold phase to practise your "database is out of space" runbook while the condition is real but controlled

## Import Experiment
You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
