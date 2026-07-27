# AWS Fault Injection Service Experiment: Database I/O Exhaustion

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Example Hypotheses

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
3. **Generating heavy I/O load** with concurrent worker threads performing read, write, or mixed operations
4. **Cleaning up** all test tables and terminating the load generator instance

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
2. Add egress rule: Load generator → Database port
    ↓
3. Add ingress rule: Database SG ← Load generator SG
    ↓
4. Launch EC2 instance (Amazon Linux 2023) with new SG
    ↓
5. Wait for SSM Agent to be online
    ↓
6. Install database client (psql/mysql/sqlcmd/sqlplus)
    ↓
7. Execute I/O exhaustion script with N worker threads
    ↓
8. Workers perform heavy read/write/mixed operations
    ↓
9. Cleanup test tables
    ↓
10. Terminate EC2 instance
    ↓
11. Remove ingress rule from database SG
    ↓
12. Delete temporary security group
```

## Prerequisites

Before running this experiment, ensure that:

1. **VPC Configuration**:
   - You have a VPC with at least one subnet that can reach your database
   - You know the VPC ID and subnet ID
   - You know the security group ID attached to your database

2. **Database Configuration**:
   - Supported database is running (Aurora PostgreSQL, Aurora MySQL, RDS PostgreSQL, RDS MySQL, RDS SQL Server, or RDS Oracle)
   - You know the database endpoint, username, and password
   - The database user has permissions to CREATE and DROP tables

### Create Required Experiment Resources

1. **Experiment template**:
   - Import the FIS experiment template (`database-io-exhaustion-experiment-template.json`) into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).

2. **IAM Roles**: Create the following IAM roles in your account using the sample policies provided:
   - FIS execution role with permissions to start SSM automation
   - SSM automation role with permissions to launch EC2 instances and execute commands
   - EC2 instance profile with the AmazonSSMManagedInstanceCore managed policy attached

3. **SSM Document**:
   - Deploy the SSM automation document (`database-io-exhaustion-automation.yaml`) to your account

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

### Infrastructure
- **SubnetId**: Subnet ID where load generator will be launched
- **VpcId**: VPC ID where the load generator will be launched (used to create security group)
- **DatabaseSecurityGroupId**: Security group ID of the target database (automation will add temporary ingress rule)
- **InstanceType**: EC2 instance type for Load Generator (default: t3.medium - use larger instances for high thread counts)

## Executing the Experiment
- Once the FIS Experiment template is deployed in your account, you will need to **update the experiment template** by editing it in the console or via the API to set appropriate parameters for your desired database target and environment
- To update via the console:
  1. Open the FIS Console
  2. Select the experiment template "Database-io-exhaustion"
  3. Select **Actions / Update Experiment Template**
  4. Select the **ExhaustDatabaseIO** Action
  5. Update the **Document parameters** to match your target e.g. {"DatabaseEngine": "postgres", "DatabaseEndpoint": "database-1.cluster-1234abcde.eu-west-1.rds.amazonaws.com", "DatabasePort": "5432", "DatabaseName": "postgres", "DatabaseUser": "postgres", "DatabasePasswordSecretArn": "arn:aws:secretsmanager:eu-west-1:123456789012:secret:rds!cluster-xxxx", "WorkerThreads": "50", "ExperimentDuration": "PT10M", "IOPattern": "mixed", "SubnetId": "subnet-1234-abcdef", "VpcId": "vpc-1234567abcd", "DatabaseSecurityGroupId": "sg-1234567abcd", "InstanceType": "t3.medium"}
  6. **Note** there is no target defined in the FIS experiment template since this is managed through the SSM Automation document and the Document parameters you just entered, so **do not amend the target section of the template**
  7. Select **Save** and then **Update experiment template**
  8. You can now **Start experiment**

## How It Works

### Phase 1: Infrastructure Creation (2-3 minutes)
1. Creates a temporary security group in your VPC with name `FIS-DatabaseIO-LoadGen-<execution-id>`
2. Adds egress rule allowing traffic from load generator to database port
3. Adds ingress rule to database security group allowing traffic from load generator
4. Launches an EC2 instance in your specified subnet with the new security group
5. Instance is tagged with `FIS-Experiment=DatabaseIOExhaustion` and `AutoCleanup=true`
6. Waits for SSM Agent to report online status

### Phase 2: Bootstrap (1-2 minutes)
7. Installs appropriate database client based on `DatabaseEngine` parameter

### Phase 3: I/O Exhaustion (Duration: ExperimentDuration)
8. Retrieves RDS password from Secrets Manager
9. Launches `WorkerThreads` concurrent threads, each:
   - Creating its own test table (`fis_io_test_<thread_id>`)
   - Continuously performing I/O operations based on `IOPattern`:
     - **Write**: INSERT rows with 4KB text + 8KB binary payload
     - **Read**: SELECT with random ordering, COUNT queries, size queries
     - **Mixed**: All of the above plus random UPDATE operations
   - Each thread operates independently to maximise I/O pressure
10. Operations continue until `ExperimentDuration` expires

### Phase 4: Cleanup
11. Each worker thread drops its test table
12. Terminates the EC2 instance
13. Waits for instance termination to complete
14. Removes the ingress rule from the database security group
15. Deletes the temporary security group
16. Returns execution summary with total I/O operations performed

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
