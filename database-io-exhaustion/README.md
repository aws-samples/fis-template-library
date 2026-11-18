# AWS Fault Injection Service Experiment: Database I/O Exhaustion

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## What this experiment does in your account

- **You set up once:** a security group for the load generator, tagged `FIS-Experiment=DatabaseIOExhaustion`, and a rule on your database's security group that lets it in on the database port (see Prerequisites). The experiment never creates, changes or deletes a security group.
- **Each run creates:** one EC2 instance in your subnet (the load generator) and tables named `fis_io_<suffix>_<n>` in your database.
- **When a run ends or is stopped,** it drops those tables and terminates the instance. If it can't, its cleanup step fails and names what is left.
- **A stop at one exact moment can leave the instance running, and nothing reports it.** If the stop arrives in the fraction of a second as a command step finishes, Systems Manager can skip the cleanup. This was seen at the end of the table step. The instance is set to shut itself down about 200 minutes after it launched (see Known limitations).
- **After every stop,** check that the instance is gone, and in some cases the tables. The commands are under Stop Conditions.
- **The load also affects** every other client of the database. On RDS with storage autoscaling it can also raise the allocated storage, which can't be reduced afterwards (see What else is affected).

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
5. **Cleaning up** the run's test tables and the load generator instance, and failing, naming what is left, if either can't be removed. A stop at one rare moment can skip this cleanup (see Known limitations)

The experiment is **parameterized by database engine**, targeting these engines in RDS: Aurora PostgreSQL, RDS PostgreSQL, RDS Oracle, Aurora MySQL, RDS MySQL and RDS SQL Server. Aurora PostgreSQL, RDS MySQL, RDS Oracle and RDS SQL Server (Express) have recorded runs of this version (see **Tested with** under Prerequisites); RDS PostgreSQL and Aurora MySQL have not.

Before relying on it, run a small `WorkerThreads`/short-`ExperimentDuration` smoke test against your target engine first.

## Architecture Overview

```
FIS Experiment
    ↓
SSM Automation Document
    ↓
1. Launch EC2 instance (Amazon Linux 2023) into the load generator security
   group you created, client token = execution ID; its user data schedules
   its own shutdown in 200 minutes
    ↓
2. Wait for SSM Agent to be online
    ↓
3. Schedule the shutdown again in 200 minutes; install database client
    ↓
4. Run the I/O load with N worker threads for ExperimentDuration; fail if
   too few workers recorded I/O or any worker hung
    ↓
5. CleanupTables: stop this run's load process if it is still running, drop
   this run's tables, fail naming any that remain
    ↓
6. CleanupInfrastructure: terminate the instance, fail naming it if it
   isn't shutting down

On a stop: CleanupTables and CleanupInfrastructure run as
StopLoadAndDropTablesOnCancel and CleanupInfrastructureOnCancel, each bounded
to fit the 2-minute cancel window (a stop during the launch waits first for
the launch to finish; see Stop Conditions)
```

## Prerequisites

Before running this experiment, ensure that:

1. **VPC Configuration**:
   - You have a VPC with at least one subnet that can reach your database
   - You know the subnet ID, the VPC it is in, and the security group ID attached to your database
   - The subnet's route table and any VPC endpoints/NAT provide the load generator with outbound HTTPS (443) connectivity to:
     - Amazon SSM and SSM Messages endpoints (required for the SSM Agent and Run Command)
     - AWS Secrets Manager (to retrieve the database password)
     - Amazon Linux package repositories (`dnf`) and PyPI (for `pip3` installs)
     - `packages.microsoft.com` (SQL Server engine only - mssql-tools repo)
     - `download.oracle.com` (Oracle engine only - Instant Client RPMs)

2. **Load generator security group**: create it once, in the subnet's VPC, and use it for every run. If your database's security group is managed by CloudFormation, the CDK or Terraform, add the group and the rule there instead, so a later deploy doesn't remove the rule or report it as drift.
   1. Create the group with the tag that the automation role's IAM policy requires. The command prints the new group's ID:
      ```
      aws ec2 create-security-group \
        --group-name FIS-DatabaseIO-LoadGenerator \
        --description "Load generator for the FIS database I/O exhaustion experiment" \
        --vpc-id <VPC ID> \
        --tag-specifications 'ResourceType=security-group,Tags=[{Key=FIS-Experiment,Value=DatabaseIOExhaustion}]'
      ```
   2. Allow it into your database's security group on the database port:
      ```
      aws ec2 authorize-security-group-ingress \
        --group-id <database security group ID> \
        --ip-permissions 'IpProtocol=tcp,FromPort=<port>,ToPort=<port>,UserIdGroupPairs=[{GroupId=<load generator security group ID>}]'
      ```
   3. Replace the group's allow-all outbound rule with two rules, the database port to your database's security group and HTTPS (443). Without this step, the load generator can send traffic anywhere:
      ```
      aws ec2 revoke-security-group-egress \
        --group-id <load generator security group ID> \
        --ip-permissions 'IpProtocol=-1,IpRanges=[{CidrIp=0.0.0.0/0}]'
      aws ec2 authorize-security-group-egress \
        --group-id <load generator security group ID> \
        --ip-permissions 'IpProtocol=tcp,FromPort=<port>,ToPort=<port>,UserIdGroupPairs=[{GroupId=<database security group ID>}]'
      aws ec2 authorize-security-group-egress \
        --group-id <load generator security group ID> \
        --ip-permissions 'IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0}]'
      ```
   4. Check the outbound rules: `aws ec2 describe-security-group-rules --filters Name=group-id,Values=<load generator security group ID> --query "SecurityGroupRules[?IsEgress].[SecurityGroupRuleId,IpProtocol,FromPort,CidrIpv4,CidrIpv6,ReferencedGroupInfo.GroupId]"`. It should list only the two rules you added. If it also lists a rule to `::/0`, remove it with `aws ec2 revoke-security-group-egress --group-id <load generator security group ID> --security-group-rule-ids <rule ID>`

   Outside a run the group has no members, so the rule on your database's security group lets nothing in. Use the group only for this experiment: anything else in it can reach the database too.

3. **Database Configuration**:
   - A supported database is running (see Description above)
   - You know the database endpoint and username, and the password is in a Secrets Manager secret (a JSON secret with a `password` key, or a plain-text secret)
   - The database user has permissions to CREATE and DROP tables. On PostgreSQL the cleanup also ends this run's own sessions with `pg_terminate_backend`, which a user may do for its own sessions. On MySQL it ends, with `KILL`, this user's sessions still running a statement on this run's tables, which a user may do for its own threads. On SQL Server it does the same if the user has `VIEW SERVER STATE` and `ALTER ANY CONNECTION`: it checks for `VIEW SERVER STATE` first, and without either permission it logs a warning and goes on. On Oracle it doesn't end sessions. Where no session is ended, a statement the killed load started can keep a table locked until the drop's deadline; the table step then fails naming the table
   - The experiment puts load on whatever database `DatabaseEndpoint` names, as long as the load generator can reach it and sign in with your secret. That includes every database that uses your database's security group and, if you kept the allow-all outbound rule, any database whose security group allows your subnet's addresses. It doesn't check which database it is, so name only a database you mean to fault

4. **Load generator**:
   - The default AMI is the latest Amazon Linux 2023 image, which includes the SSM Agent, cloud-init (which runs the launch's user data), `python3`, `bash` 5, coreutils `timeout` and systemd `shutdown`, all of which the scripts use. If you pass another `LatestAmiId`, it must provide the same
   - The instance keeps its per-run files in `/var/lib/fis-database-io-exhaustion/<execution-id>`, readable only by root

5. **Tested with**: Aurora PostgreSQL 17.9, one `db.t4g.medium` writer, in `ca-central-1`, with the default parameters: 50 of 50 workers, 154,168 operations, no errors. The writer's WriteIOPS (a per-second rate, averaged over each minute) rose from 16 to 21 up to between 3,749 and 12,736, and the load was limited by CPU (85 to 92%) more than by storage: ReadIOPS stayed at 0 to 3, because reads came from the buffer cache, and DiskQueueDepth was 0 except for one minute at 7. RDS MySQL 8.0 (`db.t3.small`, 20 GB gp3, `eu-west-1`): 50 of 50 workers, 53,833 operations, WriteIOPS from under 1 up to between 210 and 751, ReadIOPS up to 661, CPU up to 91%; a stop at peak dropped all 50 tables, and with a lock held on one table the cleanup ended the session holding it and dropped every table. RDS Oracle (`oracle-se2` 19c, `db.t3.small`, 20 GB, `us-east-2`): 50 of 50 workers, 318,382 operations, WriteIOPS from about 2 up to between 1,041 and 1,759; a stop at peak dropped all 50 tables, and with a lock held on one table the drop returned ORA-00054, so the step named that table to drop by hand while the instance was still terminated. RDS SQL Server 2022 Express (`db.t3.small`, 20 GB, `eu-north-1`): 50 of 50 workers, 22,528 operations, ReadIOPS from 0 to 1 up to between 2,910 and 2,937; a stop at peak dropped all 50 tables, and with a login lacking `VIEW SERVER STATE` the cleanup logged the documented warning and still dropped them. RDS PostgreSQL, Aurora MySQL, other instance classes and other Regions haven't been tested

### Create Required Experiment Resources

1. **Experiment template**:
   - Import the FIS experiment template (`database-io-exhaustion-experiment-template.json`) into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).

2. **IAM Roles**: Create the following IAM roles in your account using the sample policies provided:
   - FIS execution role (`DatabaseIOExhaustion-FIS-Role`) with permissions to start SSM automation (`database-io-exhaustion-fis-role-iam-policy.json`) and trust policy `fis-iam-trust-relationship.json`
   - SSM automation role (`DatabaseIOExhaustion-SSM-Automation-Role`) with permissions to launch EC2 instances and execute commands (`database-io-exhaustion-ssm-automation-role-iam-policy.json`) and trust policy `ssm-iam-trust-relationship.json`
   - EC2 instance role (`SSM-Managed-Instance-Profile-Role`, attached via instance profile `SSM-Managed-Instance-Profile`) with the `AmazonSSMManagedInstanceCore` managed policy **and** `database-io-exhaustion-ec2-instance-role-iam-policy.json`, and trust policy `ec2-iam-trust-relationship.json`
     - **Important**: the load generator retrieves the database password via `boto3.get_secret_value()` inside the `AWS-RunShellScript` command, which runs under this EC2 instance role - not the SSM automation role. Secrets Manager (and KMS, if the secret uses a customer-managed key) permissions belong here, scoped to your specific secret ARN. Any other instance that uses the same instance profile also gets read access to that secret
   - **Note**: this template hardcodes the role/document names above (the automation document's `assumeRole` and the FIS action's `documentArn`/`roleArn` reference them directly). Create the roles with these exact names, or update `database-io-exhaustion-automation.yaml` and `database-io-exhaustion-experiment-template.json` consistently if you rename them.
   - The SSM automation role can launch the load generator only into a security group tagged `FIS-Experiment=DatabaseIOExhaustion`, run commands only on instances tagged `ManagedBy=FIS-SSM-Automation` and `FIS-Experiment=DatabaseIOExhaustion`, terminate only such instances, and add tags only when it launches an instance. It has no permission to create, change or delete security groups

3. **SSM Document**:
   - Deploy the SSM automation document (`database-io-exhaustion-automation.yaml`) to your account, naming it `DatabaseIOExhaustion-Automation`

### If you used an earlier version of this experiment

- Update the SSM document, the automation role's policy and the experiment template's `documentParameters` together: remove `VpcId` and `DatabaseSecurityGroupId`, and add `LoadGeneratorSecurityGroupId`. A template that still passes the old parameters fails to start the automation with `InvalidAutomationExecutionParametersException`. If you update the existing document with `aws ssm update-document`, make the new version the default, because FIS runs the default version: `aws ssm update-document-default-version --name DatabaseIOExhaustion-Automation --document-version <new version>`
- Create the load generator's security group as Prerequisites item 2 describes. The `FIS-Ready=True` tag on your database's security group is no longer used
- Earlier versions had no self-shutdown, so a load generator an interrupted run left can still be running. While no experiment from this template is running, list them with `aws ec2 describe-instances --filters Name=tag:FIS-Experiment,Values=DatabaseIOExhaustion Name=instance-state-name,Values=pending,running,stopping,stopped --query "Reservations[].Instances[].[InstanceId,State.Name,LaunchTime]"`, terminate each with `aws ec2 terminate-instances --instance-ids <instance ID>`, and wait with `aws ec2 wait instance-terminated --instance-ids <instance ID>`. Earlier versions also left tables on a stop. Still with no experiment running, list every table whose name starts with `fis_io_`: in Manual restore's queries use the pattern `fis\_io\_%` (`fis[_]io[_]%` on SQL Server, `FIS\_IO\_%` on Oracle), and drop the tables as it describes
- Earlier versions created a security group for each run and added a rule for it to your database's security group. To list any that an interrupted run left: `aws ec2 describe-security-groups --filters Name=tag:FIS-Experiment,Values=DatabaseIOExhaustion Name=tag:ManagedBy,Values=FIS-SSM-Automation --query "SecurityGroups[].[GroupId,GroupName]"`. Your new group doesn't carry `ManagedBy`, so it isn't listed. For each group listed, find the rule that names it with `aws ec2 describe-security-group-rules --filters Name=group-id,Values=<database security group ID> --query "SecurityGroupRules[?ReferencedGroupInfo.GroupId=='<old group ID>'].SecurityGroupRuleId"`, remove it with `aws ec2 revoke-security-group-ingress --group-id <database security group ID> --security-group-rule-ids <rule ID>`, then delete the group with `aws ec2 delete-security-group --group-id <old group ID>`

## Parameters

The experiment requires the following parameters. Each has an allowed pattern or a list of allowed values, so a value with spaces, quotes or shell characters is rejected before the run starts.

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
- **LoadGeneratorSecurityGroupId**: The security group you created for the load generator (see Prerequisites), in the subnet's VPC and tagged `FIS-Experiment=DatabaseIOExhaustion`. Without the tag, the launch fails with `UnauthorizedOperation`
- **InstanceType**: EC2 instance type for Load Generator (default: t3.medium - use larger instances for high thread counts)

## Executing the Experiment
- Once the FIS Experiment template is deployed in your account, you will need to **update the experiment template** by editing it in the console or via the API to set appropriate parameters for your desired database target and environment
- To update via the console:
  1. Open the FIS Console
  2. Select the experiment template "Database-io-exhaustion"
  3. Select **Actions / Update Experiment Template**
  4. Select the **ExhaustDatabaseIO** Action
  5. Update the **Document parameters** to match your target e.g. {"DatabaseEngine": "postgres", "DatabaseEndpoint": "database-1.cluster-1234abcde.eu-west-1.rds.amazonaws.com", "DatabasePort": "5432", "DatabaseName": "postgres", "DatabaseUser": "postgres", "DatabasePasswordSecretArn": "arn:aws:secretsmanager:eu-west-1:123456789012:secret:rds!cluster-xxxx", "WorkerThreads": "50", "ExperimentDuration": "PT10M", "IOPattern": "mixed", "SeedRowCount": "500", "MinActiveWorkerPercentage": "50", "SubnetId": "subnet-0123456789abcdef0", "LoadGeneratorSecurityGroupId": "sg-0123456789abcdef0", "InstanceType": "t3.medium"}
  6. **Note** there is no target defined in the FIS experiment template since this is managed through the SSM Automation document and the Document parameters you just entered, so **do not amend the target section of the template**
  7. Select **Save** and then **Update experiment template**
  8. You can now **Start experiment**

## How It Works

Each step has its own timeout, given in brackets. The whole runbook, at its longest, fits inside the FIS action's `maxDuration` of PT180M.

### Phase 1: Launch
1. Launches an EC2 instance in your subnet with your load generator security group, the client token set to the automation execution ID, `InstanceInitiatedShutdownBehavior=terminate`, user data that schedules the instance's own shutdown 200 minutes after its first boot (so that if no cleanup runs at all, it still terminates itself after the experiment's `maxDuration` has passed), and the tags `FIS-Experiment=DatabaseIOExhaustion`, `ManagedBy=FIS-SSM-Automation` and `AutoCleanup=true` (300 s)
2. Waits for the SSM Agent to report online (300 s)

### Phase 2: Bootstrap
3. Schedules the instance's shutdown again, 200 minutes from now, in case the user data didn't run. Then installs the database client for `DatabaseEngine` (900 s)

### Phase 3: I/O Exhaustion
4. Creates `/var/lib/fis-database-io-exhaustion` (root only, mode 0700; the step fails if it exists with another owner or mode) and a subdirectory for this execution, and writes the load script and the cleanup script there
5. Starts the load script and records its PID and start time in that directory. The script retrieves the database password from Secrets Manager using the **EC2 instance role**, refuses an `ExperimentDuration` outside `PT1S`-`PT110M`, then launches `WorkerThreads` threads, each:
   - Creating its own table `fis_io_<execution-suffix>_<thread_id>`, where `<execution-suffix>` is the last 8 characters of the automation execution ID. Two runs get the same suffix only by chance, about 1 in 4 billion. Don't give your own tables names starting with `fis_io_`: the cleanup drops tables that match the run's pattern
   - Connecting with a 10-second connect timeout (on Oracle, `TRANSPORT_CONNECT_TIMEOUT=10` in the connect descriptor); on PostgreSQL with `application_name=fis_io_<execution-suffix>`
   - Seeding `SeedRowCount` rows, then performing I/O based on `IOPattern` until `ExperimentDuration` ends:
     - **Write**: INSERT rows with 4KB text + 8KB binary payload
     - **Read**: SELECT with random ordering, plus COUNT and size queries on PostgreSQL
     - **Mixed**: All of the above plus random UPDATE operations
   - Dropping its own table when it finishes (errors in this drop are ignored; step 7 catches what it leaves)
6. Waits for the workers until 300 seconds after the duration ends. The step fails if any worker is still running then, or if fewer than `MinActiveWorkerPercentage` of the workers recorded I/O. The summary (active workers, total operations and errors, `FaultInjected`) is in the `ExhaustDatabaseIO` command output; the automation's own output is the instance ID (7,500 s; the command is bounded at 7,320 s)

### Phase 4: Cleanup
7. **CleanupTables** (300 s): stops this run's load process if it is still running, by its recorded PID while the start time still matches, or by its command line naming this run's own script path. It never signals another run's process. It then connects to the database with a 3-second lock timeout (and an 8-second statement timeout on PostgreSQL), ends this run's own sessions (on PostgreSQL by their `application_name`; on MySQL and SQL Server, this user's sessions running a statement other than a drop on this run's tables; on SQL Server only if the user has `VIEW SERVER STATE`, and otherwise it logs a warning), drops every `fis_io_<execution-suffix>_*` table, and retries within a 180-second deadline. A statement a killed client started can keep its table locked on the server until the server notices the client is gone, which is why it ends those sessions and retries. It then lists the tables again: if any remain, or the cleanup couldn't finish, the step fails and its output names them, and the run ends Failed. The next step still runs
8. **CleanupInfrastructure** (180 s): finds this run's instance by its client token and terminates it. EC2's lists are eventually consistent, so a listing can miss an instance launched seconds earlier ([eventual consistency](https://docs.aws.amazon.com/ec2/latest/devguide/eventual-consistency.html)). The step therefore keeps listing, every 5 seconds while an instance isn't yet shutting down, and terminates any it hasn't yet asked EC2 to terminate, until a listing started at least 20 seconds after the step began shows nothing still running, within a 120-second deadline. AWS doesn't say how long a new instance can stay unlisted, so this is a margin, not a guarantee: an instance it misses is still set to shut itself down, and the load generator check under Stop Conditions finds it. A listing that fails is retried. Each EC2 call has a 5-second connect timeout, a 10-second read timeout and three attempts, and no call starts within 8 seconds of the deadline. The step then fails naming any instance that isn't shutting down or terminated, for example one with termination protection, and a listing that kept failing. Its output and its error also give this run's table pattern `fis_io_<execution-suffix>_*`, so tables left by a table step that never ran can still be found. It finds the instance by the client token this run set at launch, not from earlier steps' outputs, so it also cleans up after a step that failed partway. A failure in any earlier step goes straight to this step, after Phase 3 by way of CleanupTables

### What else is affected
- **Every other client of the database**: the load uses the database's I/O, buffer cache, CPU and `WorkerThreads` + 1 connections, and replicas may lag. Run it only against a database whose other users expect the fault
- **Storage**: the tables grow throughout the run. On RDS with storage autoscaling, this can raise the allocated storage, which can't be reduced afterwards. Aurora storage grows and shrinks on its own
- **The database security group**: it keeps the rule you added for the load generator's group between runs. Outside a run that group has no members, so no other source gains access. The experiment doesn't change the group
- **The subnet**: one instance and one network interface for the length of the run

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until the automation execution ends: after the load and its cleanup, or when a step fails.

Stop conditions are based on an AWS CloudWatch alarm based on an operational or 
business metric requiring an immediate end of the fault injection. This 
template makes no assumptions about your application and the relevant metrics 
and does not include stop conditions by default.

A stop cancels the automation. Systems Manager then runs the cancel workflow for at most two minutes, so the runbook has a separate, shorter cleanup for it:

- **Before the load starts** (Phases 1 and 2): `CleanupInfrastructureOnCancel` (60 s) terminates the instance if one was launched. No tables exist yet
- **During the load or CleanupTables**: `StopLoadAndDropTablesOnCancel` (45 s; it gives up after 30 s if the SSM Agent doesn't take the command) stops this run's load process and drops its tables, retrying within a 25-second deadline, then `CleanupInfrastructureOnCancel` runs
- **During CleanupInfrastructure**: `CleanupInfrastructureOnCancel` runs again; it is safe to run twice

`CleanupInfrastructureOnCancel` does what CleanupInfrastructure does, but gives each EC2 call a 2-second connect timeout, a 3-second read timeout and two attempts, starts no call within 8 seconds of its 50-second deadline, and stops listing 15 seconds before that deadline. A stop just after the launch can leave an instance that even the later listing doesn't show yet. Its user data schedules its shutdown 200 minutes after first boot, and the load generator check below finds it. The tests didn't observe the user data's own schedule: every check ran after InstallDatabaseClient had scheduled the shutdown again. On MySQL, SQL Server or Oracle, a statement the killed load started can also keep a table locked past the 25-second deadline; the table step then fails naming the table.

In the tests, a stop at peak load with no lock held ended the run 36 to 41 seconds after the stop, and the cleanup's terminate call reached EC2 about 8 to 11 seconds after it. A stop during LaunchLoadGenerator takes longer, because the cancelled launch step keeps running until the launch finishes, 147 to 164 seconds after the stop in the tests, before the cleanup can start; those runs ended 178 to 195 seconds after the stop. A stop during CleanupInfrastructure ended the run about 32 seconds after the stop, with both cleanup copies run and no step failed. On a stop during a command step, CloudTrail usually shows the automation role's `ssm:CancelCommand` call denied, because the role isn't allowed it. The stop's own steps end the load instead: in five stops 0.5 to 3 seconds after the load step started, the load had already started on the instance, and the stop's table step ended it and dropped its tables. A stop in the fraction of a second before the load command starts wasn't reached, so whether that command can still start afterwards wasn't tested.

**After every stop, check three things**, because FIS shows the experiment Stopped whether or not the cleanup finished. Find the execution ID as in Manual restore below, and wait until the automation has ended: `aws ssm get-automation-execution --automation-execution-id <execution ID> --query "AutomationExecution.AutomationExecutionStatus"` shows anything other than `InProgress` or `Cancelling` (normally `Cancelled`, `Failed` or `Success`). FIS shows Stopped within seconds, but after a stop during the launch the cleanup doesn't start for up to about three minutes, so an earlier check finds an instance the cleanup hasn't reached yet. Then:

- **The step results**: `aws ssm describe-automation-step-executions --automation-execution-id <execution ID> --query "StepExecutions[].[StepName,StepStatus,FailureMessage]"`. If `StopLoadAndDropTablesOnCancel` or `CleanupInfrastructureOnCancel` failed, remove what its message names as Manual restore describes
- **The load generator**: `aws ec2 describe-instances --filters Name=tag:FIS-Experiment,Values=DatabaseIOExhaustion Name=instance-state-name,Values=pending,running,stopping,stopped --query "Reservations[].Instances[].[InstanceId,State.Name,LaunchTime]"`. This lists every load generator that is still alive, and needs no execution ID. If it lists an instance while no experiment from this template is running, that instance's cleanup didn't finish (see Known limitations): terminate it with `aws ec2 terminate-instances --instance-ids <instance ID>`
- **The tables**, if the stop came during the load (`ExhaustDatabaseIO` shows `Cancelled`) or the load generator check found an instance: list this run's tables as Manual restore describes. A load command that hadn't yet started on the instance when you stopped isn't cancelled, and whether it can still start and create tables wasn't tested

A stopped experiment can't be resumed; start a new one ([stop an experiment](https://docs.aws.amazon.com/fis/latest/userguide/stop-experiment.html)).

A stop doesn't undo the load's effects on the database. I/O and replica lag recover on their own once the load ends. On RDS with storage autoscaling, allocated storage that grew doesn't shrink; Aurora storage shrinks on its own.

### Known limitations

- **A stop at the wrong moment can skip the cleanup.** If a stop arrives in the fraction of a second as `CleanupTables` finishes, Systems Manager can end the automation without running either stop step. In the tests, 14 stops were aimed at that moment and 13 arrived while `CleanupTables` was finishing. 4 of those 13 skipped the cleanup, all on runs whose load worked; none of 20 stops at other moments did, and earlier tests also saw it on a run whose load had failed. The same moment at the end of the other command steps wasn't hit in testing, so assume it can happen there too. The load generator is left running, no step names it, and FIS shows the experiment as stopped. By that moment the table step has finished, so the run's tables are gone unless that step failed to drop some. The instance is set to shut itself down about 200 minutes after it launched. The tests saw the shutdown scheduled but terminated every leftover by hand, so the shutdown itself wasn't observed. The load generator check under Stop Conditions finds the instance sooner. If it happens at the end of the load step instead, tables can be left too; the checks under Stop Conditions find both. The experiment doesn't change security groups, so nothing else is left.
- **The stop cleanup isn't instant.** Under slow responses the two stop steps can take most of the two-minute cancel window (their timeouts are 45 and 60 seconds). They are built to finish and name what they couldn't remove, but this wasn't tested with slow responses. If `StopLoadAndDropTablesOnCancel` failed because the SSM Agent didn't take its command, its message names no tables: list them as Manual restore describes.
- **A killed load can leave a locked table on some engines.** If a statement holds a lock on one of the run's tables past the table step's deadline, the drop times out and the step names that table to drop by hand; this was shown on Oracle with a lock held on purpose (ORA-00054). In the stops at peak load, no table was left locked. On SQL Server the killed load's own sessions were gone within about 1.5 seconds; on MySQL 16 of them were still running a statement when the cleanup checked, and it ended them. A SQL Server login without `VIEW SERVER STATE` or `ALTER ANY CONNECTION` still dropped every table. A stop in the first minute, while the rows are seeded, was tested once on Aurora PostgreSQL, where every table was dropped; on Oracle and SQL Server, where it is the likeliest moment for a lock to be held, it wasn't tested.
- **On a busy database the stop's table drop can run out of time.** The stop path gives the table drop a 25-second deadline. In earlier tests on Aurora PostgreSQL, when other runs' load shared the writer, three stops reached that deadline with 1, 13 and 41 tables still present; the step failed naming them, and Manual restore drops them. With the writer otherwise idle, two stops 5 minutes into the load dropped all 50 tables in 4 to 5 seconds. Single-run stops on RDS MySQL, Oracle and SQL Server also dropped all 50, in 4 to 8 seconds. The cause wasn't established.

### Manual restore

If a run ends Failed or Stopped and its output names something left, or the checks after a stop find something left, remove it as follows. First find the automation execution ID: FIS starts the runbook by its ARN, so list recent executions and pick the one for this document:

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
- **When you stop using the experiment**: remove the rule from your database's security group with `aws ec2 revoke-security-group-ingress --group-id <database security group ID> --ip-permissions 'IpProtocol=tcp,FromPort=<port>,ToPort=<port>,UserIdGroupPairs=[{GroupId=<load generator security group ID>}]'`, then, once no load generator is running, delete the group with `aws ec2 delete-security-group --group-id <load generator security group ID>`

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
