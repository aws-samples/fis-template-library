# AWS Fault Injection Service Experiment: Database Blocking Locks

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Description

The experiment starts an SSM Automation runbook that launches a temporary EC2 instance (the load generator) next to your database. A harness on that instance opens one Blocker session that holds a row-level lock for `ExperimentDuration`, and ramps in `WaiterCount` Waiter sessions that each wait on the same row. Use it to rehearse **detection and diagnosis** of row-lock contention: can your team find the session holding the lock, and does your runbook for "a transaction is holding a row lock too long" work?

It has two modes, chosen by `TargetTableName`:

- **Synthetic_Mode** (the default, `fis_blocking_locks_target`): the harness creates a one-column table if it doesn't exist, locks its only row, and drops the table at the end if this run created it. No application reads that table, so the lock affects only the experiment's own sessions, although its `WaiterCount` + 2 connections count against `max_connections` (see [What else is affected](#what-else-is-affected)).
- **Real_Mode** (any other table name): the harness locks the first row, by primary key, of an application table you name. Application statements that need that row wait, as [What else is affected](#what-else-is-affected) describes per engine.

Locking one row is a narrow fault. On PostgreSQL and MySQL, plain `SELECT` statements don't wait on a row lock. To degrade every code path that opens a connection, use [`database-connection-limit-exhaustion`](../database-connection-limit-exhaustion/README.md) instead.

Supported engines: Aurora PostgreSQL, Aurora MySQL, RDS for PostgreSQL, RDS for MySQL and RDS for SQL Server. See [Prerequisites](#prerequisites) for which of these have been tested.

## Hypothesis

If one session holds a row lock on {table} in the {service} database for `ExperimentDuration` while `WaiterCount` sessions wait on that row, the time from the first blocked Waiter to an alarm on the engine's blocked-session signal should not exceed {x} minutes, and the error rate of {critical user journey} should not exceed {y}%.

The hypothesis is false if the alarm doesn't reach ALARM within {x} minutes of the harness log line `Ramp 1/...`, or if the journey's error rate goes above {y}% during the run. Each harness log line starts with its UTC time. The log is the output of the InjectBlockingLocks step's command, available once the step ends: find the command ID in that step's outputs (`aws ssm describe-automation-step-executions --automation-execution-id <EXECUTION ID> --filters Key=StepName,Values=InjectBlockingLocks`) and read up to 24,000 characters with `aws ssm get-command-invocation --command-id <COMMAND ID> --instance-id <INSTANCE ID>` ([GetCommandInvocation](https://docs.aws.amazon.com/systems-manager/latest/APIReference/API_GetCommandInvocation.html)). The blocked-session signal for each engine, and the configuration it needs:

- **Aurora MySQL and RDS for MySQL**: the Performance Insights counters `db.Locks.innodb_row_lock_waits.avg` (row-lock waits; it climbs while Waiters wait), alarmed with the `DB_PERF_INSIGHTS` metric math function. Performance Insights must be on. Aurora MySQL doesn't support it on any `db.t2` or `db.t3` class, or on `db.t4g.micro` and `db.t4g.small` ([Aurora instance class support](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/USER_DatabaseInsights.Engines.html)); RDS for MySQL doesn't support it on `db.t2.micro`, `db.t2.small`, `db.t3.micro`, `db.t3.small`, `db.t4g.micro` and `db.t4g.small` ([RDS instance class support](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_DatabaseInsights.Engines.html)).
- **RDS for SQL Server**: `db.General Statistics.Processes blocked.avg`, alarmed with `DB_PERF_INSIGHTS`, with Performance Insights on.
- **Aurora PostgreSQL and RDS for PostgreSQL**: Performance Insights shows the waits as the `Lock:tuple` and `Lock:transactionid` wait events, which `DB_PERF_INSIGHTS` doesn't expose. To alarm, set `log_lock_waits = on` in the parameter group, publish the PostgreSQL log to CloudWatch Logs, and add a metric filter on `still waiting for`. PostgreSQL writes that line when a wait passes `deadlock_timeout` ([log_lock_waits](https://www.postgresql.org/docs/current/runtime-config-logging.html#GUC-LOG-LOCK-WAITS)), so the filter counts Waiters as they start to wait, not Waiters still waiting: alarm on its onset, not on a level. It can log the same wait again: in one test run, all 50 Waiters logged it a second time at the same moment, 53 to 107 seconds into their waits; the cause wasn't found. Any other client that waits longer than `deadlock_timeout` adds lines too, so an onset alarm can fire twice in one run. In one test run, with `ExperimentDuration` `PT1M` and `RampTime` `PT30S` rather than the defaults, an alarm on the filter (`Sum` over 60-second periods, `ALARM` at 1 or more) reached ALARM 82 seconds after the first ramp step. `log_lock_waits` applies to every database that uses the parameter group, and adds a log line for every lock wait longer than `deadlock_timeout` from any client, which adds CloudWatch Logs ingestion and storage cost. Use a parameter group for this database only, and set the parameter back to its previous value when you no longer need the alarm.

The PostgreSQL alarm path depends on settings outside this experiment. Check them before you rely on the hypothesis.

## Prerequisites

Before running this experiment, ensure that:

1. You have the permissions to create the IAM roles, the SSM document and the experiment template below, and to start the experiment.
2. The database the experiment targets has the tag `FIS-Ready=True`, and `DatabaseEndpoint` is a writer endpoint: an RDS instance endpoint, an Aurora cluster endpoint, or the endpoint of the Aurora cluster's writer instance. Tag the DB instance for an instance endpoint and the DB cluster for a cluster endpoint. The harness creates a table and locks a row, which a read-only server refuses, so the runbook's first step refuses reader endpoints, custom endpoints, reader instances, read replicas, and clusters that replicate from another cluster or have no writer instance. It finds the resource with `DescribeDBInstances` and `DescribeDBClusters` and fails, before it changes anything, unless the endpoint matches exactly one instance or cluster, that resource has the tag, and `DatabasePort` is its port. An RDS Proxy endpoint or your own DNS name matches nothing, so use the RDS endpoint. Don't use a secondary cluster of an Aurora global database, which is read-only; if the first step doesn't refuse it, the run fails when the harness can't create the table or take the lock.
3. The database's security group, `DatabaseSecurityGroupId`, has the tag `FIS-Ready=True` and is attached to that database. The first step checks both. The SSM automation role can add and remove ingress rules only on security groups with this tag.
4. These IAM roles exist, with the names the files hardcode:
   - `DatabaseBlockingLocks-FIS-Role`, the FIS experiment role, with [database-blocking-locks-fis-role-iam-policy.json](database-blocking-locks-fis-role-iam-policy.json) and the trust policy [fis-iam-trust-relationship.json](fis-iam-trust-relationship.json).
   - `DatabaseBlockingLocks-SSM-Automation-Role`, the runbook's role, with [database-blocking-locks-ssm-automation-role-iam-policy.json](database-blocking-locks-ssm-automation-role-iam-policy.json) and the trust policy [ssm-iam-trust-relationship.json](ssm-iam-trust-relationship.json).
   - The instance profile `DatabaseBlockingLocks-Instance-Profile`, and the role behind it, which must also be named `DatabaseBlockingLocks-Instance-Profile` (the SSM automation role may launch an instance only with that profile and pass only that role), with the managed policy `AmazonSSMManagedInstanceCore`, [database-blocking-locks-instance-profile-iam-policy.json](database-blocking-locks-instance-profile-iam-policy.json) (`secretsmanager:GetSecretValue` on your database secret only) and the trust policy [ec2-iam-trust-relationship.json](ec2-iam-trust-relationship.json). If the secret is encrypted with a customer managed KMS key, the role also needs `kms:Decrypt` on the key. The harness reads the password on the instance, as this role; the SSM automation role has no Secrets Manager permission. Anyone who can run commands on an instance with this profile can read the secret, so use the profile only for this experiment.

   Replace `<YOUR DATABASE SECRET ARN>` in the instance profile policy.

   Replace `<YOUR REGION>` and `<YOUR AWS ACCOUNT>` in the policies and trust policies.
5. The SSM Automation document [database-blocking-locks-automation.yaml](database-blocking-locks-automation.yaml) is created in your account and Region with the name `DatabaseBlockingLocks-Automation`.
6. The database password is in a Secrets Manager secret, as a plain string or as JSON with a `password` key (the shape of an RDS-managed master user secret).
7. `DatabaseName` is a database the user `DatabaseUser` can create and drop tables in (Synthetic_Mode), or the database that holds your table (Real_Mode). Don't use an engine's system database such as `mysql` or `master`. The default, `postgres`, only exists on PostgreSQL.
8. For Real_Mode only: the table has a primary key and at least one row, and `DatabaseUser` can `SELECT` from it and from `information_schema.table_constraints` and `information_schema.key_column_usage` (PostgreSQL and MySQL), or `sys.indexes`, `sys.index_columns` and `sys.columns` (SQL Server). On PostgreSQL and MySQL the name must be unqualified; on SQL Server it can be `schema.table`, and an unqualified name means `dbo`.
9. The subnet `SubnetId` is in the VPC `VpcId`, can reach the database on `DatabasePort`, and has a route to the internet (for example through a NAT gateway). The load generator installs its database client with `dnf` and `pip3` from PyPI, and for SQL Server from `packages.microsoft.com`, and reaches the Systems Manager and Secrets Manager endpoints.
10. Nothing else you run reaches the database through more than `max_connections` minus `WaiterCount` minus two connections: the harness opens one connection per Waiter, a Blocker connection and a short control connection.
11. Tested on: Aurora PostgreSQL 17.9 (writer and one reader on `db.t4g.medium`), through the cluster endpoint, in Synthetic_Mode, in `ap-northeast-1`. Real_Mode, the other engines, other endpoint types and other Regions haven't been tested.

The load generator runs Amazon Linux 2023 (the public SSM parameter `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64`), with `python3`, `psycopg2-binary`, `mysql-connector-python` or `pyodbc` and the Microsoft ODBC Driver 18 for SQL Server. The `pip3` packages aren't pinned, so each run installs their latest versions.

### Parameters

Set these in the action's document parameters. Each parameter in the table has an `allowedPattern` or `allowedValues` in the document, which rejects any value outside it before the run starts.

| Parameter | Default | Meaning |
|---|---|---|
| `DatabaseEngine` | `postgres` | `postgres`, `mysql` or `sqlserver`. |
| `DatabaseEndpoint` | none | The writer endpoint hostname, see prerequisite 2. Letters, digits, dots and hyphens. |
| `DatabasePort` | `5432` | The database's port, such as `3306` for MySQL and `1433` for SQL Server. The first step fails if it isn't. |
| `DatabaseName` | `postgres` | See prerequisite 7. Letters, digits, `_` and `-`. |
| `DatabaseUser` | `postgres` | Letters, digits, `_`, `.`, `@` and `-`. |
| `DatabasePasswordSecretArn` | none | The secret's ARN. |
| `TargetTableName` | `fis_blocking_locks_target` | The default selects Synthetic_Mode; any other name selects Real_Mode. Letters, digits and `_`, with an optional `schema.` prefix. On PostgreSQL the name is quoted, so give it in the case the catalog holds: a table created unquoted as `Orders` is `orders`. |
| `WaiterCount` | `50` | Waiter sessions to start, 1 to 9999. |
| `ExperimentDuration` | `PT10M` | How long the Blocker holds the lock, in ISO 8601 `PT` form such as `PT30M` or `PT1H`. More than zero and at most `PT2H`; the first step fails, before anything is created, on any other value. |
| `RampTime` | `PT1M` | Time over which the Waiters start. `PT0S` starts them all at once. A value longer than `ExperimentDuration` is cut to it. |
| `RampSteps` | `10` | Number of steps in the ramp. The last step must start before the hold ends, or the run fails (see [How it works](#how-it-works), step 7). |
| `VpcId`, `SubnetId` | none | Where the load generator runs. |
| `DatabaseSecurityGroupId` | none | See prerequisite 3. |
| `InstanceType` | `t3.small` | The load generator's instance type. It must be an x86_64 type, because the AMI is x86_64: a Graviton type such as `t4g.small` fails at launch. |

To set them, open the template in the FIS console, choose **Actions**, **Update experiment template**, select the `InjectBlockingLocks` action and edit **Document parameters**. The template has no targets, because the runbook finds the database itself: don't add any. A Synthetic_Mode example:

```json
{"DatabaseEngine":"postgres","DatabaseEndpoint":"database-1.cluster-1234abcde.eu-west-1.rds.amazonaws.com","DatabasePort":"5432","DatabaseName":"fis_test","DatabaseUser":"postgres","DatabasePasswordSecretArn":"arn:aws:secretsmanager:eu-west-1:123456789012:secret:rds!cluster-1234abcd-5678-90ef-abcd-1234567890ab-AbCdEf","WaiterCount":"50","ExperimentDuration":"PT30M","RampTime":"PT10M","RampSteps":"10","VpcId":"vpc-0123456789abcdef0","SubnetId":"subnet-0123456789abcdef0","DatabaseSecurityGroupId":"sg-0123456789abcdef0","InstanceType":"t3.small","TargetTableName":"fis_blocking_locks_target"}
```

For Real_Mode, set `TargetTableName` to your table, for example `"TargetTableName":"application_orders"`, after reading [What else is affected](#what-else-is-affected).

Each Waiter sets its own session's wait limits so that it waits for the whole hold: `lock_timeout` and `statement_timeout` to 0 on PostgreSQL, `innodb_lock_wait_timeout` to `ExperimentDuration` plus 600 seconds and `max_execution_time` to 0 on MySQL, and `LOCK_TIMEOUT -1` on SQL Server. A database default such as MySQL's 50-second `innodb_lock_wait_timeout` ([innodb_lock_wait_timeout](https://dev.mysql.com/doc/refman/8.0/en/innodb-parameters.html#sysvar_innodb_lock_wait_timeout)) therefore doesn't end them.

## How it works

The FIS action `aws:ssm:start-automation-execution` starts the runbook and waits for it, for at most the action's `maxDuration` of 200 minutes. The runbook's steps:

1. **CheckTargets** checks that `ExperimentDuration` is more than zero and at most `PT2H`, reads the tags of `DatabaseSecurityGroupId` and finds the DB instance or cluster whose endpoint is `DatabaseEndpoint`, paging through every instance and cluster in the Region. It fails unless the security group and exactly one database have `FIS-Ready=True`, the group is attached to that database, `DatabasePort` is its port, and the endpoint is a writer endpoint (prerequisite 2). Nothing has been created yet, so a failure here leaves nothing behind. Last, it deletes load generator groups that earlier runs left behind: groups tagged `FIS-Experiment=DatabaseBlockingLocks` whose name holds the execution ID of an automation execution that has ended (or no longer exists), skipping any that EC2 still reports in use.
2. **CreateSecurityGroup** creates the group `FIS-DatabaseBlockingLocks-LoadGen-<execution ID>` in `VpcId`, tagged `FIS-Experiment=DatabaseBlockingLocks`, `AutoCleanup=true` and `ManagedBy=FIS-SSM-Automation`. A new group starts with an outbound rule that allows all traffic ([create a security group](https://docs.aws.amazon.com/vpc/latest/userguide/creating-security-groups.html)), which the instance needs for the database, Systems Manager and its package downloads.
3. **AuthorizeInboundFromLoadGenerator** adds one ingress rule to the database's group: TCP on `DatabasePort` from the load generator's group only, with the description `FIS load generator <execution ID>`.
4. **LaunchLoadGenerator** starts one instance of `InstanceType` in `SubnetId` with the new group, the instance profile `DatabaseBlockingLocks-Instance-Profile` and IMDSv2 required, tagged as in step 2 and with `FIS-Execution=<execution ID>`, bounded to 600 seconds. Its user data runs `shutdown -h +210` and its shutdown behavior is `terminate`, so the instance terminates itself 210 minutes after launch if cleanup never does.
5. **WaitForSSMAgent** waits up to 300 seconds for the instance to register with Systems Manager.
6. **InstallDatabaseClient** installs the client for `DatabaseEngine`, bounded to 900 seconds.
7. **InjectBlockingLocks** writes the harness to `/var/lib/fis-blocking-locks/`, a directory only root can read, starts it in its own session with `setsid`, so that ending the command's process group on a cancel doesn't reach it, and waits for it. The harness records its own process ID and start time there before anything else, then exits at once if the file `stop` is there (StopHarness creates it). The shell doesn't start the harness if `stop` is already there. The step is bounded to 7,800 seconds (`executionTimeout`). Each line the harness logs starts with its UTC time. The harness:
   1. Reads the password from Secrets Manager.
   2. Synthetic_Mode: creates `fis_blocking_locks_target (id INT PRIMARY KEY)` with row `id = 1` if the table doesn't exist. Before it creates it, it writes the file `table` in the same directory, which it removes only after the drop commits. Real_Mode: checks that your table exists and has a row, reads its primary key columns, and picks the first row by primary key. Real_Mode runs only `SELECT` statements on your table.
   3. Opens the Blocker session, sets a 5-second lock wait timeout on it, and locks the row with `SELECT ... FOR UPDATE` (PostgreSQL and MySQL) or `SELECT ... WITH (UPDLOCK, HOLDLOCK)` (SQL Server). If another session already holds the row, this fails after 5 seconds and the run fails instead of queueing behind it.
   4. Holds the lock for `ExperimentDuration`, counted from when it got the lock. The Blocker sleeps in the harness, not in the database, and runs `SELECT 1` every 15 seconds to check its connection is still open.
   5. Starts the Waiters on the ramp schedule: `WaiterCount` spread over `min(RampSteps, WaiterCount)` steps, `RampTime` (cut to `ExperimentDuration`) divided by the steps apart, rounded down to whole seconds and at least 1 second, with any remainder in the last step. With the defaults that's 10 steps of 5 Waiters, 6 seconds apart. With `RampTime=PT5S` and 10 steps, the steps are 1 second apart, so the last starts after 9 seconds. Each Waiter opens its own connection, sets its session's wait limits as [Parameters](#parameters) says, and runs the same locking `SELECT` on the same row, so it waits on the Blocker.
   6. When `ExperimentDuration` has passed, commits the Blocker. The Waiters then get the row in turn, commit and close. The harness waits up to 60 seconds in total for them, then drops the table if this run created it, with a 5-second lock wait timeout. From the start of that cleanup it ignores `SIGTERM`, so a stop can't cut the drop short.

   The harness exits non-zero, which fails the step and the experiment, when: the server ends the Blocker's transaction before `ExperimentDuration` (exit 11, logged as `Blocker tx ended by the server`), fewer than `WaiterCount` Waiters could connect (exit 12), the table it created can't be dropped (exit 13), a Waiter ended with an error before the Blocker released the row, for example because something on the server ended its session (exit 14, after the harness has held the lock for the rest of `ExperimentDuration`), a Waiter started its locking `SELECT` after the Blocker released the row, for example because the last ramp step starts after a short hold ends (exit 15), another session holds the row (exit 5, or 25 in Real_Mode), or a check on the parameters, the secret, the connection or the Real_Mode table fails.
8. **StopHarness** runs on every path after step 7, including a stop. It first creates the file `stop` in the harness directory, then reads the harness's record, matched by process ID and start time so that a reused process ID is never signalled. A harness that writes its record after `stop` exists sees it and exits before it connects, and one that wrote its record before is found from it, so a stop as the step starts can't leave a harness running. It sends the recorded process `SIGTERM`. The harness then closes the Blocker connection, which rolls back its transaction and releases the lock, drops the table if this run created it, and exits; the Waiters' connections close as the process exits. If the harness is still running after 25 seconds, the step sends `SIGKILL` and fails. The step also fails, saying to drop the table by hand, if the file `table` is still there, which means this run created the table and didn't drop it, whatever ended the harness.
9. **Cleanup** finds this run's security group by its name and its instance by the tag `FIS-Execution=<execution ID>`, so it doesn't depend on the outputs of the steps it cleans up after. It revokes the ingress rule from step 3, terminates the instance and waits up to 480 seconds for it to be `terminated`, then deletes the group. A cancelled AuthorizeInboundFromLoadGenerator can re-add the rule after that first revoke, so on a `DependencyViolation` (the group is still in use because the rule came back) it revokes the rule again and retries the delete until its wait runs out; a group that is already gone (`InvalidGroup.NotFound`) counts as deleted. Last, it revokes once more, reads the database's group back, and fails, naming this run's load generator group, if a rule from that group is still there. Any failure fails the run. **CleanupOnCancel** is the same step with a 90-second wait, for a stop during Cleanup.

### Step outcomes

| Step | If it fails | If the experiment is stopped during it |
|---|---|---|
| CheckTargets | The run ends Failed; nothing was changed. | The run ends; nothing was changed. |
| CreateSecurityGroup to InstallDatabaseClient | Cleanup. Failed. | CleanupOnCancel. |
| InjectBlockingLocks | StopHarness, then Cleanup. Failed. | StopHarness, then Cleanup. |
| StopHarness | Cleanup. Failed. | CleanupOnCancel. |
| Cleanup | Failed, with what it couldn't remove named in its error. | CleanupOnCancel. |
| CleanupOnCancel | Failed, as for Cleanup. | The run ends; anything left is removed by hand. |

Each run records what it changed on the resources themselves, under its own automation execution ID: the security group's name contains it, the instance carries it in the tag `FIS-Execution`, the database ingress rule is found by its source group, and the harness's process record and table marker are on the run's own instance. A step that was cancelled or failed partway, and produced no outputs, still leaves those records.

### Overlapping runs

Two runs never share an instance, a security group or an ingress rule, and each removes only the rule whose source is its own group. Two runs against the same row can't both lock it: the second run's Blocker waits 5 seconds, fails, and that run ends Failed without touching the first run's lock or table. In Synthetic_Mode the second run sees the table already exists, so it never drops it. If two Synthetic_Mode runs start within the moment between one run checking that the table exists and creating it, both treat the table as theirs. The first to finish then tries to drop it while the other holds its lock, times out after 5 seconds and fails with exit 13, leaving the table; the run still holding the lock drops it when it ends.

### Timings

The steps that wait or run commands have these bounds: 600 seconds for the launch, 300 for the agent, 960 for the install, 8,100 for the harness, 90 for StopHarness and 600 for Cleanup. Together that's 177.5 minutes, which leaves 22.5 of the action's 200-minute `maxDuration` for CheckTargets, CreateSecurityGroup and AuthorizeInboundFromLoadGenerator, which make a few API calls each. If the runbook still runs past `maxDuration`, FIS stops it, as a stop does. A normal run takes `ExperimentDuration` plus setup and cleanup: in the test, two runs with the defaults on Aurora PostgreSQL took 14 min 46 s and 15 min 7 s: about 3½ minutes of setup, the 600-second hold (the ramp runs inside it), about 43 seconds of StopHarness and Cleanup, and 30 to 40 seconds before FIS marked the experiment completed after the runbook ended. In both runs all 50 Waiters were waiting at the client's first 5-second sample after the last ramp step, about 57 seconds after the first. When the experiment is stopped, Systems Manager gives the cancel path at most two minutes ([Automation actions](https://docs.aws.amazon.com/systems-manager/latest/userguide/automation-actions.html)), so StopHarness runs first, then the revoke, then termination. Cleanup waits for termination before it deletes the group, so when termination takes longer than what's left of the two minutes, the group stays. The first step of the next run deletes it once the instance is gone and no rule on your database's group references it, or you can delete it by hand. If the cancel path is cut off before the instance is terminated, the instance still terminates itself 210 minutes after launch.

### What else is affected

- **The database's security group** gets one ingress rule on `DatabasePort` whose only source is the load generator's group, for the length of the run. If the group is managed by CloudFormation or the CDK, the rule shows up as drift ([drift detection](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-cfn-stack-drift.html)), and a stack update during the run can remove it, which cuts the harness off and fails the run.
- **Connections**: the run uses `WaiterCount` + 2 connections. If the database is close to `max_connections`, other clients can be refused.
- **Synthetic_Mode** creates the table `fis_blocking_locks_target` in `DatabaseName` for the length of the run. Schema comparison or migration tools that run meanwhile will see it.
- **Real_Mode** locks one row of your table. Which statements wait on it depends on the engine:
  - **PostgreSQL**: `UPDATE`, `DELETE`, and `SELECT ... FOR UPDATE`, `FOR NO KEY UPDATE`, `FOR SHARE` and `FOR KEY SHARE` on that row wait; plain `SELECT` doesn't ([row-level locks](https://www.postgresql.org/docs/current/explicit-locking.html#LOCKING-ROWS)). PostgreSQL records a row lock in the row itself, so locking it writes to disk, although no value changes.
  - **MySQL (InnoDB)**: `UPDATE`, `DELETE`, `SELECT ... FOR UPDATE` and `SELECT ... FOR SHARE` (or `LOCK IN SHARE MODE`) on that row wait; plain `SELECT` doesn't ([locking reads](https://dev.mysql.com/doc/refman/8.0/en/innodb-locking-reads.html)).
  - **SQL Server**: with Read Committed Snapshot Isolation (RCSI) off, which is the default, plain `SELECT` on that row waits too, as do `UPDATE` and `DELETE`. With RCSI on, plain `SELECT` reads a row version and doesn't wait ([row versioning](https://learn.microsoft.com/en-us/sql/relational-databases/sql-server-transaction-locking-and-row-versioning-guide)). Check with `SELECT name, is_read_committed_snapshot_on FROM sys.databases WHERE name = DB_NAME();`, where `1` means on.
- **Load generator groups of earlier runs**: CheckTargets deletes groups tagged `FIS-Experiment=DatabaseBlockingLocks`, named `FIS-DatabaseBlockingLocks-LoadGen-<execution ID>`, whose automation execution has ended. Don't give that tag and name to groups of your own.
- **The subnet**: the load generator takes one IP address in `SubnetId` and sends its package downloads through the subnet's route to the internet.
- **Database timeouts**: on PostgreSQL, `idle_in_transaction_session_timeout` ends the Blocker only if it's set below about 15 seconds, because the Blocker's `SELECT 1` every 15 seconds resets it ([client connection defaults](https://www.postgresql.org/docs/current/runtime-config-client.html)). PostgreSQL 17 added `transaction_timeout`, which limits a whole transaction however active it is, so any value below `ExperimentDuration` ends the Blocker early. On MySQL, `max_execution_time` applies only to read-only `SELECT` statements ([max_execution_time](https://dev.mysql.com/doc/refman/8.0/en/server-system-variables.html#sysvar_max_execution_time)), and the Blocker never runs a long statement. Whatever ends the Blocker or a Waiter early, the harness logs it and the run fails.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped, until the runbook finishes, which is `ExperimentDuration` after the Blocker gets its lock plus setup and cleanup, or until a step fails.

Stop conditions are based on an AWS CloudWatch alarm based on an operational or 
business metric requiring an immediate end of the fault injection. This 
template makes no assumptions about your application and the relevant metrics 
and does not include stop conditions by default.

A stop, from the console, the API or a stop condition, makes FIS cancel the runbook. A stopped experiment can't be resumed ([stop an experiment](https://docs.aws.amazon.com/fis/latest/userguide/stop-experiment.html)). What the stop does depends on where the runbook is:

- **During step 1**: the runbook ends. Nothing was changed.
- **During setup** (steps 2 to 6): CleanupOnCancel removes the rule, terminates the instance and deletes the group, finding each from its name or tag.
- **While the lock is held** (step 7): StopHarness ends the harness with `SIGTERM`, which releases the lock and drops a table this run created, then Cleanup removes the rule, the instance and the group. In the test, the harness released the lock and dropped the table 1 second after the stop. If the harness doesn't exit within 25 seconds it's killed: the database still ends its sessions and releases the lock when their connections close, but a table this run created is left, and StopHarness fails saying so. It fails the same way whenever the harness ended without dropping a table it created.
- **During cleanup**: a stop during StopHarness or Cleanup runs CleanupOnCancel, which is safe to run twice.

Without StopHarness, terminating the instance leaves the harness's connections open on the server until its TCP keepalive gives up on them, and the lock stays held until then: on Aurora PostgreSQL in the test, 5 min 50 s to 5 min 55 s after the terminate call (5-second samples).

If the cancel path runs past Systems Manager's two-minute limit, the rest of the cleanup doesn't run: the group stays until the next run's first step deletes it, and an instance that wasn't terminated yet terminates itself 210 minutes after launch. If the cut-off comes before the ingress rule is removed, the rule still references the group, so the next run's first step can't delete the group and skips it without saying so: remove the rule first, then the group, as below. In the tests, the cancel path ended 41 to 43 seconds after a stop during the hold, StopHarness or Cleanup's revoke, 14 seconds after a stop during Cleanup's delete, about 70 seconds in a test that forced a cancelled authorize to keep re-adding the rule for about 45 seconds (six failed deletes, each followed by another revoke, then a seventh that deleted the group), 68 seconds when the harness ignored `SIGTERM` and StopHarness killed it after 25 seconds (leaving the table, as above), 68 seconds after a stop during the install, and 177 seconds after a stop during the launch, because the cancelled launch step went on waiting for the instance for 137 seconds. None was cut off. A stop during the hold while the instance's SSM Agent can't be reached, where StopHarness would run to its 90-second timeout before Cleanup's roughly 40 seconds, wasn't tested.

FIS shows the experiment stopped as soon as you stop it, while the runbook's cleanup goes on. A cancelled step's script can also keep making its calls for a while after Systems Manager shows it Cancelled: in the test an ingress authorize ran 1 to 4 seconds after a stop, and a cancelled Cleanup went on terminating and deleting for about 30 seconds beside CleanupOnCancel. Nothing was left in any test run. When a cancelled authorize re-adds the rule after cleanup's first revoke, the load generator group won't delete (`DependencyViolation`); cleanup then revokes the rule again and retries, and a final pass revokes once more and fails only if a rule from this run's load generator group is still on the database group. In a test that forced a cancelled step to keep re-adding the rule for about 45 seconds, the delete failed with `DependencyViolation` six times, each followed by another revoke, and the seventh attempt deleted the group once the re-adding stopped, leaving nothing. A group the cancelled step deleted first (`InvalidGroup.NotFound`) counts as done, so the run doesn't fail on it. Wait until the automation execution has ended, not the experiment, then check, and remove anything left by hand:

```bash
# The run's instance (tag FIS-Execution) and security group (name FIS-DatabaseBlockingLocks-LoadGen-<execution ID>)
aws ec2 describe-instances --filters Name=tag:FIS-Experiment,Values=DatabaseBlockingLocks Name=instance-state-name,Values=pending,running,shutting-down,stopping,stopped --query 'Reservations[].Instances[].[InstanceId,Tags[?Key==`FIS-Execution`]|[0].Value]'
aws ec2 describe-security-groups --filters Name=tag:FIS-Experiment,Values=DatabaseBlockingLocks --query 'SecurityGroups[].[GroupId,GroupName]'
# Ingress rules on the database's group whose source is a load generator group
aws ec2 describe-security-group-rules --filters Name=group-id,Values=<YOUR DATABASE SECURITY GROUP ID> --query 'SecurityGroupRules[?IsEgress==`false` && ReferencedGroupInfo.GroupId!=`null`].[SecurityGroupRuleId,ReferencedGroupInfo.GroupId,Description]'

aws ec2 revoke-security-group-ingress --group-id <YOUR DATABASE SECURITY GROUP ID> --security-group-rule-ids <RULE ID>
aws ec2 terminate-instances --instance-ids <INSTANCE ID>
aws ec2 delete-security-group --group-id <LOAD GENERATOR SECURITY GROUP ID>
```

Remove only rules whose description is `FIS load generator <execution ID>`. If the synthetic table was left, drop it on the database (`dbo.fis_blocking_locks_target` on SQL Server):

```sql
DROP TABLE fis_blocking_locks_target;
```

A stop condition you add stops the run in the same way, at whatever point it fires. To test it, set its alarm to ALARM during a run with `aws cloudwatch set-alarm-state --alarm-name <ALARM NAME> --state-value ALARM --state-reason "FIS stop condition test"` ([SetAlarmState](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_SetAlarmState.html)), and check that the experiment stops and the lock is released.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case. If you change `FIS-Ready=True`, change it in the runbook's `CheckTargets` step and in the SSM automation role's ingress statement too.
2. Identifying business metrics tied to the journeys that read or write the table you lock.
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm on the engine's blocked-session signal from the [Hypothesis](#hypothesis).
4. Adding a stop condition tied to the alarm to automatically halt the experiment if critical thresholds are breached.
5. Starting with a small `WaiterCount`, such as 10, and Synthetic_Mode, to check the signal appears where you expect it before you scale up or switch to Real_Mode.
6. Before each run, checking the settings that can end the Blocker early: on PostgreSQL `SHOW idle_in_transaction_session_timeout;` and, on version 17 or later, `SHOW transaction_timeout;`. Waiters set their own wait limits, so `lock_timeout`, `statement_timeout` and MySQL's `innodb_lock_wait_timeout` don't end them, but they still apply to your application's sessions.
7. After each run, checking that the instance and the security group are gone, the database's group has no load generator rule, and `fis_blocking_locks_target` is gone if the run created it.

## Import Experiment
You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
