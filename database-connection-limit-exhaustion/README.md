# AWS Fault Injection Service Experiment: Database Connection Limit Exhaustion

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Example Hypotheses

When the {service1} database connection value is approaching it's limit, users of {workload} should be able to complete the {service1} user journey within the SLA of 2 seconds and other critical user journeys relating to {workload} {service2} and {service3} should continue unaffected. The {service1} circuit breaker should remain closed allowing additional connections to the database. The steady state of {n} transactions per second should be maintained. A leading alarm should be raised and the DevOps team notified within {y} minutes. The database status report should run automatically providing the DevOps team with insight into database connection usage. 

When the {service1} database connection limit is exhausted, the {workload} {service1} circuit breaker should open resulting in users of {workload} being unable to complete the {service1} user journey. The {workload} UI should degrade gracefully and users should not be able to interact with the {service1} section of UI, thus preventing new connections to the {service1} database being created. An alarm should be raised and the DevOps team notified within {y} minutes. Other critical user journeys relating to {workload} {service2} and {service3} should continue unaffected. Once the {service1} database connections are drained, the {workload} {service1} circuit breaker should close with {z} minutes. Users should be able to commence interacting with the {service1} section of the UI and the steady of {n} transactions per second should resume.

### What does this enable me to verify?

* Appropriate customer experience metrics and observability of your database is in place (were you able to detect there was an impending issue as the database connection limit approached and once the database connection limit was full?)
* Alarms are configured correctly (were the right people notified at the right time and/or automations triggered?)
* Your app gracefully degrades and customers aren't submitting transactions which you know will fail
* Your circuit breaker (if any) works as expected
* Recovery controls (if any) work as expected

## Description

This experiment tests your application's resilience to database connection limit exhaustion by:

1. **Dynamically creating** an ephemeral EC2 instance as a load generator
2. **Bootstrapping** the instance with the appropriate database client (PostgreSQL, MySQL, or SQL Server)
3. **Opening and holding** connections to exhaust the database connection limit
4. **Cleaning up** by releasing connections and terminating the load generator instance

The experiment is **parameterized by database engine**, making it reusable across:
- Aurora PostgreSQL
- Aurora MySQL
- RDS PostgreSQL
- RDS MySQL
- RDS SQL Server

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
7. Execute connection exhaustion script
    ↓
8. Hold connections for specified duration
    ↓
9. Release connections
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
   - Supported database is running (Aurora PostgreSQL, Aurora MySQL, RDS PostgreSQL, RDS MySQL, or RDS SQL Server)
   - You know the database endpoint, username, and password

### Create Required Experiment Resources

You can build all the experiment resources by executing the provided deploy.py script as follows:

```
python deploy.py --region us-east-1 --account-id 123456789012
```
Or 

1. **Experiment template**:
   - Import the FIS experiment template (`database-connection-limit-exhaustion-experiment-template.json`) into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).

2. **IAM Roles**: Create the following IAM roles in your account using the sample policies provided:
   - FIS execution role with permissions to start SSM automation
   - SSM automation role with permissions to launch EC2 instances and execute commands
   - EC2 instance profile with SSM managed instance permissions

3. **SSM Document**:
   - Deploy the SSM automation document (`database-connection-limit-exhaustion-automation.yaml`) to your account

## Parameters

The experiment requires the following parameters:

### Database Configuration
- **DatabaseEngine**: `postgres`, `mysql`, or `sqlserver` (default: `postgres`)
- **DatabaseEndpoint**: Database DNS hostname or endpoint
- **DatabasePort**: Database port (default: 5432 for PostgreSQL, use 3306 for MySQL, 1433 for SQL Server)
- **DatabaseName**: Database name to connect to
  - PostgreSQL: `postgres` (default system database)
  - MySQL: `mysql` (default system database)
  - SQL Server: `master` (default system database)
- **DatabaseUser**: Database username (default: `postgres`)
- **DatabasePasswordSecretArn**: ARN of Secrets Manager secret containing password
  - **Note** Since we don't know the ARN of your secret ahead of time, the [sample ssm automation role ](aurora-postgres-connection-limit-exhaustion-ssm-automation-role-iam-policy.json) is given read access to all secrets, you should probably scope this down accordingly.

### Connection Settings
- **MaxConnections**: Number of connections to open (default: 1000)
- **ExperimentDuration**: Total experiment duration in ISO8601 format (default: PT10M = 10 minutes, e.g., PT1H = 1 hour, PT30M = 30 minutes)
  - **Note** this is not the same as the FIS Experiment Template Max Duration (default 3 hours for this experiment template) which functions as overarching timeout.
- **RampTime**: Time to gradually ramp up to MaxConnections in ISO8601 format (default: PT1M = 1 minute, e.g., PT30S = 30 seconds, PT2M = 2 minutes, PT0S = immediate)
- **RampSteps**: Number of steps to reach MaxConnections (default: 10, e.g., 2=50% then 100%, 20=5% increments)

### Infrastructure
- **SubnetId**: Subnet ID where load generator will be launched
- **VpcId**: VPC ID where the load generator will be launched (used to create security group)
- **DatabaseSecurityGroupId**: Security group ID of the target database (automation will add temporary ingress rule)
- **InstanceType**: EC2 instance type (default: t3.small)
- **LatestAmiId**: Amazon Linux 2023 AMI ID (uses SSM parameter by default)

## Executing the Experiment
- Once the FIS Experiment template is deployed in your account, you will need to update the template by editing the Document parameters in the console or via the API to set appropriate parameters for your desired database target and environment
- To update via the console:
  1. Open the FIS Console
  2. Select the experiment template "Database-connection-limit-Exhaustion"
  3. Select **Actions / Update Experiment Template**
  4. Select the **ExhaustConnectionLimit** Action
  5. Update the Document parameters e.g. {"DatabaseEngine": "postgres", "DatabaseEndpoint": "database-1.cluster-1234abcde.eu-west-1.rds.amazonaws.com", "DatabasePort": 5432, "DatabaseName": "postgres", "DatabaseUser": "postgres", "DatabasePasswordSecretArn": "arn:aws:secretsmanager:eu-west-1:123456789012:secret:rds!cluster-xxxx-yyyy-zzzz", "MaxConnections": "1000", "ExperimentDuration": "PT30M", "RampTime": "PT10M", "RampSteps": "15", "SubnetId": "subnet-1234-abcdef", "VpcId": "vpc-1234567abcd", "DatabaseSecurityGroupId": "sg-1234567abcd", "InstanceType": "t3.small"}
  6. **Note** there is no target defined in the FIS experiment template since this is managed through the SSM Automation document and the Document parameters you just entered
  7. Select **Save** and then **Update experiment template**
  8. You can now **Start experiment**

## How It Works

### Phase 1: Infrastructure Creation (2-3 minutes)
1. Creates a temporary security group in your VPC with name `FIS-ConnectionLimit-LoadGen-<execution-id>`
2. Adds egress rule allowing traffic from load generator to database port
3. Adds ingress rule to database security group allowing traffic from load generator
4. Launches an EC2 instance in your specified subnet with the new security group
5. Instance is tagged with `FIS-Experiment=ConnectionLimitExhaustion` and `AutoCleanup=true`
6. Waits for SSM Agent to report online status

### Phase 2: Bootstrap (1-2 minutes)
4. Installs appropriate database client based on `DatabaseEngine` parameter

### Phase 3: Connection Exhaustion (Duration: ExperimentDuration)
5. Retrieves database password from Secrets Manager
6. Validates and adjusts `RampTimeSeconds` if it exceeds `ExperimentDuration`
7. Gradually opens connections over `RampTimeSeconds` in `RampSteps` increments:
   - Each step opens `MaxConnections / RampSteps` connections
   - Time between steps: `RampTimeSeconds / RampSteps` seconds
   - **Each connection holds until experiment end**: Connections opened at T=0 hold for full `ExperimentDuration`, connections opened at T=60s hold for `ExperimentDuration - 60s`
   - **Keepalive mechanism**: Each connection sends a lightweight query (`SELECT 1`) every 30 seconds to prevent idle timeouts
   - Example: 10-minute experiment, 5-minute ramp, 10 steps
     * Step 1 (T=0): Open 10 connections → hold for 10 minutes with keepalive
     * Step 5 (T=2.5m): Open 10 connections → hold for 7.5 minutes with keepalive
     * Step 10 (T=5m): Open 10 connections → hold for 5 minutes with keepalive
   - Set `RampTimeSeconds=0` to open all connections immediately (all hold for full duration)
8. Each connection runs a keepalive loop that sends periodic queries to maintain the connection
9. All connections release simultaneously at experiment end

### Phase 4: Cleanup
10. Releases all database connections
11. Terminates the EC2 instance
12. Waits for instance termination to complete
13. Removes the ingress rule from the database security group
14. Deletes the temporary security group
15. Returns execution summary

## Stop Conditions

The experiment template does not have any specific stop conditions defined by default. It will continue to run until:
- All actions complete successfully or one fails
- Manually stopped via FIS console/API
- A custom CloudWatch alarm triggers (if configured)

## Observability and Stop Conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. **Start Small**: Begin with `MaxConnections` well below your database's `max_connections` limit
2. **Use Gradual Ramp-Up**: Set e.g. `RampTimeSeconds=600` and `RampSteps=10` to observe progressive degradation
3. **Adjust Aggressiveness**: Fewer steps (2-5) = sharper increments per step
4. **Add Stop Conditions**: Create CloudWatch alarms for critical business metrics
5. **Test Connection Limits**: Query your database's max_connections setting:
   ```sql
   -- PostgreSQL
   SHOW max_connections;
   SELECT count(*) FROM pg_stat_activity;
   
   -- MySQL
   SHOW VARIABLES LIKE 'max_connections';
   SHOW STATUS LIKE 'Threads_connected';
   ```
4. **Implement Safeguards**: Ensure your application has:
   - Connection limiting with max pool size limits
   - Connection timeout configurations
   - Retry logic with exponential backoff
   - Circuit breakers for database calls
5. **Monitor Cleanup**: Verify the EC2 instance is terminated after the experiment
6. **Cost Optimization**: Use smaller instance types (t3.micro) if connection count allows

## Connection Keepalive and Timeout Handling

The experiment uses a **keepalive loop** to maintain connections throughout the experiment duration:

- Each connection sends a lightweight query (`SELECT 1`) every 30 seconds
- Prevents idle connection timeouts from closing connections prematurely
- More realistic than single long-running query (mimics real application behavior)
