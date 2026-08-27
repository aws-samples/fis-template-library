# AWS Fault Injection Service Experiment: Database I/O Exhaustion

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE

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
5. **Cleaning up** all test tables and terminating the load generator instance

The experiment is **parameterized by database engine**, making it reusable across engines in RDS:
- Aurora PostgreSQL
- Aurora MySQL
- RDS PostgreSQL
- RDS MySQL
- RDS SQL Server
- RDS Oracle

## Architecture Overview

```
FIS Experiment
    ↓
SSM Automation Document
    ↓
1. Create temporary security group in VPC
    ↓
2. Revoke the security group's default allow-all egress rule, then add egress
   rules: Load generator → Database port, and Load generator → HTTPS (443)
   for SSM, Secrets Manager, and package repositories
    ↓
3. Add ingress rule: Database SG ← Load generator SG (database SG must be
   tagged FIS-Ready=True)
    ↓
4. Launch EC2 instance (Amazon Linux 2023) with new SG
    ↓
5. Wait for SSM Agent to be online
    ↓
6. Install database client (psql/mysql/sqlcmd/sqlplus)
    ↓
7. Execute I/O exhaustion script with N worker threads: each worker seeds its
   table with baseline rows, then performs heavy read/write/mixed operations
   for the experiment duration
    ↓
8. Verify a minimum percentage of workers actually recorded I/O operations;
   fail the automation if the fault was not reliably injected
    ↓
9. Cleanup: each worker drops its own uniquely-named table
    ↓
10. Terminate EC2 instance
    ↓
11. Revoke ingress rule from database SG (idempotent - runs even if the load
    generator failed to launch)
    ↓
12. Delete temporary security group
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
   - Supported database is running (Aurora PostgreSQL, Aurora MySQL, RDS PostgreSQL, RDS MySQL, RDS SQL Server, or RDS Oracle)
   - You know the database endpoint, username, and password
   - The database user has permissions to CREATE and DROP tables
   - The database security group (`DatabaseSecurityGroupId`) is tagged `FIS-Ready=True` - the SSM automation role's IAM policy only permits ingress changes on security groups carrying this tag

### Create Required Experiment Resources

1. **Experiment template**:
   - Import the FIS experiment template (`database-io-exhaustion-experiment-template.json`) into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).

2. **IAM Roles**: Create the following IAM roles in your account using the sample policies provided:
   - FIS execution role (`DatabaseIOExhaustion-FIS-Role`) with permissions to start SSM automation (`database-io-exhaustion-fis-role-iam-policy.json`)
   - SSM automation role (`DatabaseIOExhaustion-SSM-Automation-Role`) with permissions to launch EC2 instances and execute commands (`database-io-exhaustion-ssm-automation-role-iam-policy.json`)
   - EC2 instance role (`SSM-Managed-Instance-Profile-Role`, attached via instance profile `SSM-Managed-Instance-Profile`) with the `AmazonSSMManagedInstanceCore` managed policy **and** `database-io-exhaustion-ec2-instance-role-iam-policy.json`
     - **Important**: the load generator retrieves the database password via `boto3.get_secret_value()` inside the `AWS-RunShellScript` command, which runs under this EC2 instance role - not the SSM automation role. Secrets Manager (and KMS, if the secret uses a customer-managed key) permissions belong here, scoped to your specific secret ARN
   - **Note**: this template hardcodes the role/document names above (the automation document's `assumeRole` and the FIS action's `documentArn`/`roleArn` reference them directly). Create the roles with these exact names, or update `database-io-exhaustion-automation.yaml` and `database-io-exhaustion-experiment-template.json` consistently if you rename them.

3. **SSM Document**:
   - Deploy the SSM automation document (`database-io-exhaustion-automation.yaml`) to your account, naming it `DatabaseIOExhaustion-Automation`

## Parameters

The experiment requires the following parameters:

### Database Configuration
- **DatabaseEngine**: `postgres`, `mysql`, `sqlserver`, or `oracle` (default: `postgres`)
- **DatabaseEndpoint**: Database DNS hostname or endpoint
- **DatabasePort**: Database port (default: 5432 for PostgreSQL, use 3306 for MySQL, 1433 for SQL Server, 1521 for Oracle)
- **DatabaseName**: Database name (or service name for Oracle) to connect to
- **DatabaseUser**: Database username (default: `postgres`)
- **DatabasePasswordSecretArn**: ARN of Secrets Manager secret containing password

### I/O Load Settings
- **WorkerThreads**: Number of concurrent worker threads generating I/O (default: 50)
- **ExperimentDuration**: Total experiment duration in ISO8601 format (default: PT10M = 10 minutes)
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
  5. Update the **Document parameters** to match your target e.g. {"DatabaseEngine": "postgres", "DatabaseEndpoint": "database-1.cluster-1234abcde.eu-west-1.rds.amazonaws.com", "DatabasePort": "5432", "DatabaseName": "postgres", "DatabaseUser": "postgres", "DatabasePasswordSecretArn": "arn:aws:secretsmanager:eu-west-1:123456789012:secret:rds!cluster-xxxx", "WorkerThreads": "50", "ExperimentDuration": "PT10M", "IOPattern": "mixed", "SeedRowCount": "500", "MinActiveWorkerPercentage": "50", "SubnetId": "subnet-1234-abcdef", "VpcId": "vpc-1234567abcd", "DatabaseSecurityGroupId": "sg-1234567abcd", "InstanceType": "t3.medium"}
  6. **Note** there is no target defined in the FIS experiment template since this is managed through the SSM Automation document and the Document parameters you just entered, so **do not amend the target section of the template**
  7. Select **Save** and then **Update experiment template**
  8. You can now **Start experiment**

## How It Works

### Phase 1: Infrastructure Creation (2-3 minutes)
1. Creates a temporary security group in your VPC with name `FIS-DatabaseIO-LoadGen-<execution-id>`, tagged `ManagedBy=FIS-SSM-Automation` and `FIS-Experiment=DatabaseIOExhaustion`
2. Revokes the security group's default allow-all outbound rule, then adds explicit egress rules: load generator → database port, and load generator → HTTPS (443) for SSM, Secrets Manager, and package repositories. The load generator's outbound access is **not** unrestricted - only these two rules exist afterward
3. Adds ingress rule to the database security group allowing traffic from the load generator (requires the database security group to be tagged `FIS-Ready=True`)
4. Launches an EC2 instance in your specified subnet with the new security group
5. Instance is tagged with `FIS-Experiment=DatabaseIOExhaustion`, `ManagedBy=FIS-SSM-Automation`, and `AutoCleanup=true`
6. Waits for SSM Agent to report online status

### Phase 2: Bootstrap (1-2 minutes)
7. Installs appropriate database client based on `DatabaseEngine` parameter

### Phase 3: I/O Exhaustion (Duration: ExperimentDuration)
8. Retrieves the database password from Secrets Manager, using the **EC2 instance role** (not the SSM automation role) since this call runs inside the `AWS-RunShellScript` command on the load generator
9. Launches `WorkerThreads` concurrent threads, each:
   - Creating its own uniquely-named test table (`fis_io_<execution-suffix>_<thread_id>`, where `<execution-suffix>` is derived from the automation execution ID) - this guarantees no collision with pre-existing tables or tables from a concurrent run, and that cleanup only ever drops objects this execution created
   - Seeding `SeedRowCount` rows into the table before the timed phase starts, so `read` and `mixed` patterns have real data to scan/update instead of querying an empty table
   - Continuously performing I/O operations based on `IOPattern`:
     - **Write**: INSERT rows with 4KB text + 8KB binary payload
     - **Read**: SELECT with random ordering, COUNT queries, size queries
     - **Mixed**: All of the above plus random UPDATE operations
   - Each thread operates independently to maximise I/O pressure, tracking both successful operations and errors
10. Operations continue until `ExperimentDuration` expires
11. Aggregates results across all workers and checks `MinActiveWorkerPercentage`: if fewer than the required percentage of workers recorded I/O operations (or zero total operations were recorded), the script exits non-zero, the `ExhaustDatabaseIO` step fails, and the automation execution reports failure rather than a false success

### Phase 4: Cleanup
12. Each worker thread drops its own test table (in a `finally` block, so this runs even if the timed loop hit errors)
13. Terminates the EC2 instance
14. Waits for instance termination to complete
15. Revokes the ingress rule from the database security group - idempotent, and reached even if `LaunchLoadGenerator` itself failed, so a partially-created run never leaves an orphaned ingress rule blocking security group deletion
16. Deletes the temporary security group
17. Returns execution summary including total I/O operations, error counts, and whether the fault was successfully injected

## Stop Conditions

The experiment template does not have any specific stop conditions defined by default. It will continue to run until:
- All actions complete successfully or one fails
- Manually stopped via FIS console/API
- A custom CloudWatch alarm triggers (if configured)

## Observability and Stop Conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

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
4. **Add Stop Conditions**: Create CloudWatch alarms for critical business metrics
5. **Scale Gradually**: Increase `WorkerThreads` in increments to find your I/O saturation point
6. **Implement Safeguards**: Ensure your application has:
   - Query timeout configurations
   - Read replica routing for read-heavy workloads
   - Caching layers (ElastiCache/DAX) to reduce database I/O
   - Connection pool timeout and retry logic
7. **Cost Optimization**: Use t3.medium for moderate loads, scale up for extreme I/O generation
8. **Tune Fault Verification**: Raise `MinActiveWorkerPercentage` if you want stricter confirmation that the fault was injected, or review `TotalOperationErrors` in the execution output to spot connectivity/throttling issues

## Import Experiment
You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
