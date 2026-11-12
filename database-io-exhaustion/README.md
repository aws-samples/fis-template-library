# AWS Fault Injection Service Experiment: Database I/O Exhaustion

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

When {service1} database I/O utilisation is approaching saturation, users of {workload} should be able to complete the {service1} user journey within the SLA of 2 seconds and other critical user journeys relating to {workload}; {service2} and {service3} should continue unaffected. The steady state of {n} transactions per second should be maintained. A leading alarm should be raised and the DevOps team notified within {y} minutes. The database performance insights report should provide the DevOps team with insight into I/O bottlenecks.

When the {service1} database I/O capacity is exhausted, the {workload} {service1} response times should degrade gracefully. The {workload} UI should indicate degraded performance to users. An alarm should be raised and the DevOps team notified within {y} minutes. Other critical user journeys relating to {workload}; {service2} and {service3} should continue unaffected. Once the I/O load is removed, database performance should recover within {z} minutes and the steady state of {n} transactions per second should resume.

### What does this enable me to verify?

* Appropriate customer experience metrics and observability of your database I/O is in place (were you able to detect I/O saturation approaching and once it was saturated?)
* Alarms are configured correctly for I/O metrics (ReadIOPS, WriteIOPS, ReadLatency, WriteLatency, DiskQueueDepth)
* Your app gracefully degrades under I/O pressure rather than failing catastrophically
* Read replicas or caching layers absorb load effectively
* Recovery controls and auto-scaling (if any) work as expected

## Description

This experiment tests your application's resilience to database I/O exhaustion by:

1. **Dynamically creating** an ephemeral EC2 instance as a load generator
2. **Bootstrapping** the instance with the appropriate database client (PostgreSQL, MySQL, SQL Server, or Oracle)
3. **Seeding** each worker's table with baseline rows so read and mixed workloads have real data to scan/update, then **generating heavy I/O load** with concurrent worker threads performing read, write, or mixed operations
4. **Verifying** the fault was actually injected (a minimum percentage of workers recorded I/O operations) and failing the experiment if it was not
5. **Cleaning up** the run's test tables, the load generator instance, its security group and the temporary rule on your database's security group, and failing the run, naming what is left, if any of these can't be removed

The experiment is **parameterized by database engine**, targeting these engines in RDS: Aurora PostgreSQL, RDS PostgreSQL, RDS Oracle, Aurora MySQL, RDS MySQL and RDS SQL Server. Aurora PostgreSQL, RDS MySQL, RDS Oracle and RDS SQL Server (Express) have recorded runs of this version (see **Tested with** under Prerequisites); RDS PostgreSQL and Aurora MySQL have not.

Before relying on it, run a small `WorkerThreads`/short-`ExperimentDuration` smoke test against your target engine first.

## Architecture Overview

```
FIS Experiment
    ↓
SSM Automation Document
    ↓
1. Create temporary security group FIS-DatabaseIO-LoadGen-<execution-id>
    ↓
2. Replace its default allow-all egress with: database port → database SG,
   and HTTPS (443) for SSM, Secrets Manager and package repositories
    ↓
3. Add ingress rule: Database SG ← load generator SG (database SG must be
   tagged FIS-Ready=True)
    ↓
4. Launch EC2 instance (Amazon Linux 2023), client token = execution ID;
   its user data schedules its own shutdown in 200 minutes
    ↓
5. Wait for SSM Agent to be online
    ↓
6. Schedule the shutdown again in 200 minutes; install database client
    ↓
7. Run the I/O load with N worker threads for ExperimentDuration; fail if
   too few workers recorded I/O or any worker hung
    ↓
8. CleanupTables: stop this run's load process if it is still running, drop
   this run's tables, fail naming any that remain
    ↓
9. CleanupInfrastructure: terminate the instance, revoke the ingress rule,
   delete the security group, fail naming anything left

On a stop: steps 8 and 9 run as StopLoadAndDropTablesOnCancel and
CleanupInfrastructureOnCancel, each bounded to fit the 2-minute cancel window
(a stop during step 4 waits first for the launch to finish; see Stop Conditions)
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
   - The temporary security group's egress is restricted to the database port and HTTPS (443) only - see "How It Works" Phase 1 below

2. **Database Configuration**:
   - A supported database is running (see Description above)
   - You know the database endpoint and username, and the password is in a Secrets Manager secret (a JSON secret with a `password` key, or a plain-text secret)
   - The database user has permissions to CREATE and DROP tables. On PostgreSQL the cleanup also ends this run's own sessions with `pg_terminate_backend`, which a user may do for its own sessions. On MySQL it ends, with `KILL`, this user's sessions still running a statement on this run's tables, which a user may do for its own threads. On SQL Server it does the same if the user has `VIEW SERVER STATE` and `ALTER ANY CONNECTION`: it checks for `VIEW SERVER STATE` first, and without either permission it logs a warning and goes on. On Oracle it doesn't end sessions. Where no session is ended, a statement the killed load started can keep a table locked until the drop's deadline; the table step then fails naming the table
   - The database security group (`DatabaseSecurityGroupId`) is tagged `FIS-Ready=True` - the SSM automation role's IAM policy only permits ingress changes on security groups carrying this tag. The experiment doesn't check the database itself for the tag: it puts load on whatever database `DatabaseEndpoint` names, so name only a database you mean to fault

3. **Load generator**:
   - The default AMI is the latest Amazon Linux 2023 image, which includes the SSM Agent, cloud-init (which runs the launch's user data), `python3`, `bash` 5, coreutils `timeout` and systemd `shutdown`, all of which the scripts use. If you pass another `LatestAmiId`, it must provide the same
   - The instance keeps its per-run files in `/var/lib/fis-database-io-exhaustion/<execution-id>`, readable only by root

4. **Tested with**: Aurora PostgreSQL 17.9, one `db.t4g.medium` writer, in `eu-central-1`, with the default parameters. Three completion runs each ran 50 of 50 workers with no errors and did 105,281, 96,157 and 93,151 operations. In the first, the writer's WriteIOPS (a per-second rate, averaged over each minute) rose from 12 to 23 up to between 3,720 and 12,351, and the load was limited by CPU (72 to 95%) more than by storage: ReadIOPS stayed at 0 to 2, because reads came from the buffer cache, and DiskQueueDepth was mostly 0, with single minutes at 9 and 41. RDS MySQL 8.0 (`db.t3.small`, 20 GB gp3, `eu-west-1`): 50 of 50 workers, 52,240 operations, WriteIOPS from 0 to 3 up to 177 to 661 and ReadIOPS up to 702, CPU 89%; the completion run dropped all 50 tables, and a stop at peak and a stop with a lock held on one table both dropped every table and ended the run's sessions. RDS Oracle (`oracle-se2` 19c, `db.t3.small`, 20 GB, `us-east-2`): 50 of 50 workers, 338,772 operations, WriteIOPS from about 2 to between 1,210 and 1,547; the completion run and a stop at peak dropped all 50 tables, and with a lock held on one table the drop returned ORA-00054, so the step named that table to drop by hand while the infrastructure cleanup still succeeded. RDS SQL Server Express (`db.t3.small`, 20 GB, `eu-north-1`): 50 of 50 workers, 15,955 operations, ReadIOPS from 0 to 2 up to between 1,132 and 2,484; the completion run and a stop at peak dropped all 50 tables, and with a login lacking `VIEW SERVER STATE` the cleanup logged the documented warning and still dropped them. RDS PostgreSQL, Aurora MySQL, other instance classes and other Regions haven't been tested

### Create Required Experiment Resources

1. **Experiment template**:
   - Import the FIS experiment template (`database-io-exhaustion-experiment-template.json`) into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).

2. **IAM Roles**: Create the following IAM roles in your account using the sample policies provided:
   - FIS execution role (`DatabaseIOExhaustion-FIS-Role`) with permissions to start SSM automation (`database-io-exhaustion-fis-role-iam-policy.json`) and trust policy `fis-iam-trust-relationship.json`
   - SSM automation role (`DatabaseIOExhaustion-SSM-Automation-Role`) with permissions to launch EC2 instances and execute commands (`database-io-exhaustion-ssm-automation-role-iam-policy.json`) and trust policy `ssm-iam-trust-relationship.json`
   - EC2 instance role (`SSM-Managed-Instance-Profile-Role`, attached via instance profile `SSM-Managed-Instance-Profile`) with the `AmazonSSMManagedInstanceCore` managed policy **and** `database-io-exhaustion-ec2-instance-role-iam-policy.json`, and trust policy `ec2-iam-trust-relationship.json`
     - **Important**: the load generator retrieves the database password via `boto3.get_secret_value()` inside the `AWS-RunShellScript` command, which runs under this EC2 instance role - not the SSM automation role. Secrets Manager (and KMS, if the secret uses a customer-managed key) permissions belong here, scoped to your specific secret ARN. Any other instance that uses the same instance profile also gets read access to that secret
   - **Note**: this template hardcodes the role/document names above (the automation document's `assumeRole` and the FIS action's `documentArn`/`roleArn` reference them directly). Create the roles with these exact names, or update `database-io-exhaustion-automation.yaml` and `database-io-exhaustion-experiment-template.json` consistently if you rename them.
   - The SSM automation role can run commands only on instances tagged `ManagedBy=FIS-SSM-Automation` and `FIS-Experiment=DatabaseIOExhaustion`, terminate only such instances, change only security groups with those tags or `FIS-Ready=True`, and add tags only when it creates an instance or a security group. `ec2:RunInstances` isn't limited further

3. **SSM Document**:
   - Deploy the SSM automation document (`database-io-exhaustion-automation.yaml`) to your account, naming it `DatabaseIOExhaustion-Automation`

## Parameters

The experiment requires the following parameters. Each has an allowed pattern, so a value with spaces, quotes or shell characters is rejected before the run starts.

### Database Configuration
- **DatabaseEngine**: `postgres`, `mysql`, `sqlserver`, or `oracle` (default: `postgres`)
- **DatabaseEndpoint**: Database DNS hostname or endpoint
- **DatabasePort**: Database port (default: 5432 for PostgreSQL, use 3306 for MySQL, 1433 for SQL Server, 1521 for Oracle)
- **DatabaseName**: Database name (or service name for Oracle) to connect to
- **DatabaseUser**: Database username (default: `postgres`)
- **DatabasePasswordSecretArn**: ARN of Secrets Manager secret containing password

### I/O Load Settings
- **WorkerThreads**: Number of concurrent worker threads generating I/O, 1 to 999 (default: 50). Each opens its own database connection
- **ExperimentDuration**: Length of the timed I/O phase in ISO8601 format, from `PT1S` to `PT110M` (default: PT10M = 10 minutes). The load script refuses a longer value before it starts any load, because the `ExhaustDatabaseIO` command is bounded at 7,320 seconds (`executionTimeout`) and the FIS action's `maxDuration` is PT180M
- **IOPattern**: I/O pattern to generate (default: `mixed`)
  - `read` - Heavy SELECT queries with random row access and full table scans
  - `write` - Heavy INSERT and UPDATE operations with large payloads
  - `mixed` - Combination of reads, writes, and updates
- **SeedRowCount**: Rows inserted into each worker's table before the timed I/O phase begins (default: 500). Ensures `read` and `mixed` patterns query/update real data instead of an empty table
- **MinActiveWorkerPercentage**: Minimum percentage of worker threads that must record at least one I/O operation for the experiment to be treated as a successful fault injection (default: 50). If this threshold isn't met (or zero total operations were recorded), the `ExhaustDatabaseIO` step - and the automation execution - fails

### Infrastructure
- **SubnetId**: Subnet ID where load generator will be launched
- **VpcId**: VPC ID where the load generator will be launched (used to create security group)
- **DatabaseSecurityGroupId**: Security group ID of the target database, must be tagged `FIS-Ready=True` (automation will add temporary ingress rule)
- **InstanceType**: EC2 instance type for Load Generator (default: t3.medium - use larger instances for high thread counts)

## Executing the Experiment
- Once the FIS Experiment template is deployed in your account, you will need to **update the experiment template** by editing it in the console or via the API to set appropriate parameters for your desired database target and environment
- To update via the console:
  1. Open the FIS Console
  2. Select the experiment template "Database-io-exhaustion"
  3. Select **Actions / Update Experiment Template**
  4. Select the **ExhaustDatabaseIO** Action
  5. Update the **Document parameters** to match your target e.g. {"DatabaseEngine": "postgres", "DatabaseEndpoint": "database-1.cluster-1234abcde.eu-west-1.rds.amazonaws.com", "DatabasePort": "5432", "DatabaseName": "postgres", "DatabaseUser": "postgres", "DatabasePasswordSecretArn": "arn:aws:secretsmanager:eu-west-1:123456789012:secret:rds!cluster-xxxx", "WorkerThreads": "50", "ExperimentDuration": "PT10M", "IOPattern": "mixed", "SeedRowCount": "500", "MinActiveWorkerPercentage": "50", "SubnetId": "subnet-0123456789abcdef0", "VpcId": "vpc-0123456789abcdef0", "DatabaseSecurityGroupId": "sg-0123456789abcdef0", "InstanceType": "t3.medium"}
  6. **Note** there is no target defined in the FIS experiment template since this is managed through the SSM Automation document and the Document parameters you just entered, so **do not amend the target section of the template**
  7. Select **Save** and then **Update experiment template**
  8. You can now **Start experiment**

## How It Works

Each step has its own timeout, given in brackets. The whole runbook, at its longest, fits inside the FIS action's `maxDuration` of PT180M.

### Phase 1: Infrastructure Creation
1. Creates a temporary security group in your VPC named `FIS-DatabaseIO-LoadGen-<execution-id>`, tagged `ManagedBy=FIS-SSM-Automation` and `FIS-Experiment=DatabaseIOExhaustion` (60 s)
2. Revokes the security group's default allow-all outbound rule, then adds explicit egress rules: load generator → database port, and load generator → HTTPS (443) for SSM, Secrets Manager, and package repositories. Only these two rules exist afterward (60 s)
3. Adds an ingress rule to the database security group allowing the database port from the load generator's security group. The IAM policy allows this only if the database security group is tagged `FIS-Ready=True` (60 s)
4. Launches an EC2 instance in your subnet with the new security group, the client token set to the automation execution ID, `InstanceInitiatedShutdownBehavior=terminate`, user data that schedules the instance's own shutdown 200 minutes after its first boot (so that if no cleanup runs at all, it still terminates itself after the experiment's `maxDuration` has passed), and the tags `FIS-Experiment=DatabaseIOExhaustion`, `ManagedBy=FIS-SSM-Automation` and `AutoCleanup=true` (300 s)
5. Waits for the SSM Agent to report online (300 s)

### Phase 2: Bootstrap
6. Schedules the instance's shutdown again, 200 minutes from now, in case the user data didn't run. Then installs the database client for `DatabaseEngine` (900 s)

### Phase 3: I/O Exhaustion
7. Creates `/var/lib/fis-database-io-exhaustion` (root only, mode 0700; the step fails if it exists with another owner or mode) and a subdirectory for this execution, and writes the load script and the cleanup script there
8. Starts the load script and records its PID and start time in that directory. The script retrieves the database password from Secrets Manager using the **EC2 instance role**, refuses an `ExperimentDuration` outside `PT1S`-`PT110M`, then launches `WorkerThreads` threads, each:
   - Creating its own table `fis_io_<execution-suffix>_<thread_id>`, where `<execution-suffix>` is the last 8 characters of the automation execution ID, so tables never collide with other tables or with a concurrent run's
   - Connecting with a 10-second connect timeout (on Oracle, `TRANSPORT_CONNECT_TIMEOUT=10` in the connect descriptor); on PostgreSQL with `application_name=fis_io_<execution-suffix>`
   - Seeding `SeedRowCount` rows, then performing I/O based on `IOPattern` until `ExperimentDuration` ends:
     - **Write**: INSERT rows with 4KB text + 8KB binary payload
     - **Read**: SELECT with random ordering, COUNT queries, size queries
     - **Mixed**: All of the above plus random UPDATE operations
   - Dropping its own table when it finishes (errors in this drop are ignored; step 10 catches what it leaves)
9. Waits for the workers until 300 seconds after the duration ends. The step fails if any worker is still running then, or if fewer than `MinActiveWorkerPercentage` of the workers recorded I/O. The summary (active workers, total operations and errors, `FaultInjected`) is in the `ExhaustDatabaseIO` command output; the automation's own outputs are the instance ID and the security group ID (7,500 s; the command is bounded at 7,320 s)

### Phase 4: Cleanup
10. **CleanupTables** (300 s): stops this run's load process if it is still running, by its recorded PID while the start time still matches, or by its command line naming this run's own script path. It never signals another run's process. It then connects to the database with a 3-second lock timeout (and an 8-second statement timeout on PostgreSQL), ends this run's own sessions (on PostgreSQL by their `application_name`; on MySQL and SQL Server, this user's sessions running a statement other than a drop on this run's tables; on SQL Server only if the user has `VIEW SERVER STATE`, and otherwise it logs a warning), drops every `fis_io_<execution-suffix>_*` table, and retries within a 180-second deadline. A statement a killed client started can keep its table locked on the server until the server notices the client is gone, which is why it ends those sessions and retries. It then lists the tables again: if any remain, or anything failed, the step fails and its output names them, and the run ends Failed. The next step still runs
11. **CleanupInfrastructure** (540 s): finds this run's instance by its client token and terminates it, finds this run's security group by its name, reads the database security group, revokes any ingress rule there whose source is this run's group, then reads the database security group back. A run whose ingress change was refused has no rule there, so nothing is revoked or reported. Within a 480-second deadline it then waits for termination (until 15 seconds before the deadline), listing the instances by client token again on every poll and terminating any it hadn't seen, and deletes the security group, retrying while the group is still in use. Before each retry it lists the instances again, reads the database security group again and revokes any rule there whose source is this run's group, since a cancelled step can still add one after the first read. No earlier than 20 seconds after it started, it lists the instances and the security group once more, restores the database security group for every group still listed and deletes it, and reads the group back. Last, it reads the database security group once more for rules naming any group this run listed, deleted or not, and revokes them: a rule that names a deleted group can remain if it was added just after the delete, before EC2 had seen it, or if your database's security group is in a peered VPC, where the delete doesn't wait for it ([VPC peering security groups](https://docs.aws.amazon.com/vpc/latest/peering/vpc-peering-security-groups.html)). The later listings are there because EC2's lists are eventually consistent, so the first listing can miss an instance or group created seconds earlier ([eventual consistency](https://docs.aws.amazon.com/ec2/latest/devguide/eventual-consistency.html)). Each EC2 call has a 5-second connect timeout, a 10-second read timeout and three attempts, and no call starts within 8 seconds of the deadline. Each problem is recorded once per kind, so a later failure replaces it and a later success of the same kind, such as a good read, listing or delete, drops it; the others still run. A delete that is throttled or gets no answer is retried, as one that finds the group still in use is. A delete answering that the group doesn't exist isn't taken as proof, since EC2 can answer that for a group created moments earlier ([error codes](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/errors-overview.html)): the last listing decides, as it also does for a delete that failed. The step then fails naming what is left, from the last listing that succeeded if a final one couldn't run. Its output and its error also give this run's table pattern `fis_io_<execution-suffix>_*`, so tables left by a table step that never ran can still be found. It finds everything from what this run set at creation, not from earlier steps' outputs, so it also cleans up after a step that failed partway. A failure in any earlier step goes straight to this step, after Phase 3 by way of CleanupTables

### What else is affected
- **Every other client of the database**: the load uses the database's I/O, buffer cache, CPU and `WorkerThreads` + 1 connections, and replicas may lag. Run it only against a database whose other users expect the fault
- **Storage**: the tables grow throughout the run. On RDS with storage autoscaling, this can raise the allocated storage, which can't be reduced afterwards. Aurora storage grows and shrinks on its own
- **The database security group**: it gains one ingress rule for the database port from the load generator's security group, which only the load generator uses, so no other source gains access. If the group is managed by CloudFormation or the CDK, the rule shows up as drift while it exists, and a stack update during the run may remove it
- **The subnet**: one instance and one network interface for the length of the run

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until the automation execution ends: after the load and its cleanup, or when a step fails.

Stop conditions are based on an AWS CloudWatch alarm based on an operational or 
business metric requiring an immediate end of the fault injection. This 
template makes no assumptions about your application and the relevant metrics 
and does not include stop conditions by default.

A stop cancels the automation. Systems Manager then runs the cancel workflow for at most two minutes, so the runbook has a separate, shorter cleanup for it:

- **Before the load starts** (Phases 1 and 2): `CleanupInfrastructureOnCancel` (60 s) terminates the instance if one was launched, revokes the ingress rule, and deletes the security group. No tables exist yet
- **During the load or CleanupTables**: `StopLoadAndDropTablesOnCancel` (45 s; it gives up after 30 s if the SSM Agent doesn't take the command) stops this run's load process and drops its tables, retrying within a 25-second deadline, then `CleanupInfrastructureOnCancel` runs
- **During CleanupInfrastructure**: `CleanupInfrastructureOnCancel` runs again; it is safe to run twice

The stop path revokes the ingress rule right after it asks EC2 to terminate the instance, before it waits for termination. `CleanupInfrastructureOnCancel` does what CleanupInfrastructure does, including the later listings and the last read, but gives each EC2 call a 2-second connect timeout, a 3-second read timeout and two attempts, starts no call within 8 seconds of its 50-second deadline, and stops waiting for termination 15 seconds before that deadline. If the instance hasn't terminated by then, the temporary security group is left and the step fails naming it. A cancelled script step's EC2 calls can still reach EC2 after the stop path has started (in the tests, 1 to 2 seconds after the stop), so a stop while AuthorizeInboundFromLoadGenerator runs can add the ingress rule after the stop path's first read of your database's security group. The temporary group can't be deleted while a rule on another group in the same VPC names it ([DeleteSecurityGroup](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DeleteSecurityGroup.html)), so before each retry of the delete, and again for every group the last listing still shows, the stop path reads your database's security group again and revokes any rule there whose source is this run's group. Its last read catches such a rule that arrived after the delete. A stop just after the launch or the group's creation can leave an instance or group that even the later listings don't show yet; the instance's user data schedules its shutdown 200 minutes after first boot, and an empty group can be removed as Manual restore describes. The tests didn't observe the user data's own schedule: every check ran after InstallDatabaseClient had scheduled the shutdown again. On MySQL, SQL Server or Oracle, a statement the killed load started can also keep a table locked past the 25-second deadline; the table step then fails naming the table.

In the tests on Aurora PostgreSQL, a stop at peak load cleaned up within 37 to 56 seconds, with the rule, instance and group gone within 51 seconds. A stop during LaunchLoadGenerator took longer, because the cancelled launch step itself runs for 96 to 150 seconds before the cleanup can start: the cancel workflow ended 125 to 198 seconds after the stop, and the ingress rule stayed for 100 to 155 seconds. At peak load, 21 to 31 seconds passed between `CleanupInfrastructureOnCancel`'s terminate request and the group's deletion, and the step stops waiting for termination about 35 seconds after it starts, so on `t3.medium` in `eu-central-1` a termination a few seconds slower than any seen would leave the empty security group, which the step then names (see Known limitations below). A stop during CleanupInfrastructure left the cancelled step's script running beside `CleanupInfrastructureOnCancel`: both terminated the instance, one deleted the group, and the cancel step's output named only the instance, although nothing was left. On every stop during a command step, the automation role's `ssm:CancelCommand` call is denied; the stop's own steps end the command, so nothing depends on it.

**After every stop, check the automation's step results**, because FIS shows the experiment Stopped whether or not the cleanup finished. Find the execution ID as in Manual restore below, then run `aws ssm describe-automation-step-executions --automation-execution-id <execution ID> --query "StepExecutions[].[StepName,StepStatus,FailureMessage]"`. If `StopLoadAndDropTablesOnCancel` or `CleanupInfrastructureOnCancel` failed, remove what its message names as Manual restore describes. A stopped experiment can't be resumed; start a new one ([stop an experiment](https://docs.aws.amazon.com/fis/latest/userguide/stop-experiment.html)).

A stop doesn't undo the load's effects on the database, such as storage growth or replica lag; the database recovers on its own once the load ends.

### Known limitations

A stop has to finish its cleanup inside the Systems Manager cancellation window, which runs for about two minutes. Within that window:

- **A slow instance termination can leave the empty temporary security group.** The stop path revokes the ingress rule on your database's security group early, then waits for the load generator to terminate before deleting the temporary group, but only until about 35 seconds into the step (its 50-second deadline less a 15-second margin). In the tests the group was deleted 21 to 31 seconds after the terminate request, on every peak-load stop, so a termination a few seconds slower than any seen would leave the temporary group, now empty and unreferenced, and the step names it; remove it with the Manual restore command below.
- **A stop during the failure path can skip the cleanup.** If the load has failed (for example an unreachable database or fewer active workers than `MinActiveWorkerPercentage`) and a stop lands in the brief window while the table-cleanup step runs, Systems Manager can end the automation `Failed` without running the stop cleanup, leaving the load generator, its security group and the ingress rule while the experiment shows as stopped. It was seen in one of the three failure-path stops that landed in that window during testing. It is Systems Manager's cancellation behavior on an already-failing automation, not something the document controls. The load generator terminates itself 200 minutes after it boots; remove the security group and the ingress rule with Manual restore.
- **The stop cleanup is not instant.** Under slow EC2 responses `CleanupInfrastructureOnCancel` can take most of the two-minute window; it still completes and names anything it could not remove.
- **A killed load can leave a locked table on some engines.** If a statement holds a lock on one of the run's tables past the table step's deadline, the drop times out and the step names that table to drop by hand; this was shown on Oracle with a lock held on purpose (ORA-00054). In the stops tested, the killed load's own sessions ended within about 1.5 seconds and left no locked table, including a SQL Server login without `VIEW SERVER STATE` or `ALTER ANY CONNECTION`, which still dropped every table. A stop in the first minute, while the rows are seeded, was not tested; it is the likeliest moment for a lock to be held on Oracle or SQL Server.

- **On a busy database the stop's table drop can run out of time.** The stop path gives the table drop a 25-second deadline. In the tests, when other load shared the writer, three stops reached that deadline with 1, 13 and 41 tables still present; the step failed naming them, and Manual restore drops them. No Aurora PostgreSQL peak-load stop in this campaign ran without other load on the writer, so this wasn't tested with the writer otherwise idle; on RDS MySQL, Oracle and SQL Server, single-run stops dropped all 50 tables in seconds. The cause wasn't established.

### Manual restore

If a run ends Failed or Stopped and its output names something left, remove it as follows. First find the automation execution ID: FIS starts the runbook by its ARN, so list recent executions and pick the one for this document:

```
aws ssm describe-automation-executions \
  --filters Key=StartTimeAfter,Values=<experiment start time, for example 2026-10-31T09:00:00Z> \
  --query "AutomationExecutionMetadataList[?contains(DocumentName, 'DatabaseIOExhaustion-Automation')].[AutomationExecutionId,AutomationExecutionStatus,ExecutionStartTime]"
```

- **Tables**: the suffix is the last 8 letters and digits of the execution ID, in lower case. Connect to the database as the experiment's user, list the tables named `fis_io_<suffix>_<n>`, then drop each one:
  - PostgreSQL: `SELECT tablename FROM pg_tables WHERE tablename LIKE 'fis\_io\_<suffix>\_%';`, then `DROP TABLE <name>;`
  - MySQL: `SELECT table_name FROM information_schema.tables WHERE table_schema = '<database>' AND table_name LIKE 'fis\_io\_<suffix>\_%';`, then ``DROP TABLE `<name>`;``
  - SQL Server: `SELECT name FROM sys.tables WHERE schema_id = SCHEMA_ID() AND name LIKE 'fis[_]io[_]<suffix>[_]%';`, then `DROP TABLE [<name>];`
  - Oracle (names are upper case): `SELECT table_name FROM user_tables WHERE table_name LIKE 'FIS\_IO\_<SUFFIX>\_%' ESCAPE '\';`, then `DROP TABLE "<NAME>" PURGE;`
- **Instance**: `aws ec2 describe-instances --filters Name=client-token,Values=<execution ID> --query "Reservations[].Instances[].[InstanceId,State.Name]"`, then `aws ec2 terminate-instances --instance-ids <instance ID>`
- **Ingress rule and security group**: `aws ec2 describe-security-groups --filters Name=group-name,Values=FIS-DatabaseIO-LoadGen-<execution ID> --query "SecurityGroups[].GroupId"`, then `aws ec2 revoke-security-group-ingress --group-id <database security group ID> --ip-permissions "IpProtocol=tcp,FromPort=<port>,ToPort=<port>,UserIdGroupPairs=[{GroupId=<load generator security group ID>}]"`, and once the instance has terminated, `aws ec2 delete-security-group --group-id <load generator security group ID>`. If that group is already gone but a rule on the database security group still names it, list that rule's ID with `aws ec2 describe-security-group-rules --filters Name=group-id,Values=<database security group ID> --query "SecurityGroupRules[?ReferencedGroupInfo.GroupId=='<load generator security group ID>'].SecurityGroupRuleId"` and remove it with `aws ec2 revoke-security-group-ingress --group-id <database security group ID> --security-group-rule-ids <rule ID>` ([DescribeSecurityGroupRules](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeSecurityGroupRules.html), [RevokeSecurityGroupIngress](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_RevokeSecurityGroupIngress.html))

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. **Start Small**: Begin with a low `WorkerThreads` count (10-20) to observe baseline I/O impact
2. **Monitor Key Metrics**: Watch these CloudWatch metrics during the experiment:
   ```
   - ReadIOPS / WriteIOPS
   - ReadLatency / WriteLatency
   - DiskQueueDepth
   - ReadThroughput / WriteThroughput
   - CPUUtilization (I/O wait component)
   ```
3. **Choose I/O Pattern**: Use `write` to stress storage throughput, `read` to stress buffer cache misses, or `mixed` for realistic load
4. **Add Stop Conditions**: Create CloudWatch alarms for critical business metrics. An alarm stop runs the same stop path as a manual stop (see Stop Conditions), which is built to end the load within the cancel window. To check that the alarm stops the experiment, set it to ALARM during a run with `aws cloudwatch set-alarm-state --alarm-name <name> --state-value ALARM --state-reason test` ([SetAlarmState](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_SetAlarmState.html))
5. **Scale Gradually**: Increase `WorkerThreads` in increments to find your I/O saturation point
6. **Implement Safeguards**: Ensure your application has:
   - Query timeout configurations
   - Read replica routing for read-heavy workloads
   - Caching layers (ElastiCache/DAX) to reduce database I/O
   - Connection pool timeout and retry logic
7. **Cost Optimization**: Use t3.medium for moderate loads, scale up for extreme I/O generation
8. **Tune Fault Verification**: Raise `MinActiveWorkerPercentage` if you want stricter confirmation that the fault was injected, or review `TotalOperationErrors` in the `ExhaustDatabaseIO` command output to spot connectivity/throttling issues

## Import Experiment
You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
