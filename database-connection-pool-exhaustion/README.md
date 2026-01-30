****TODO - update to discuss modofying the experiment template with database endpoint etc. add logs, add reports if desired - can use update_experiment_template() rather than editing in the console


# AWS Fault Injection Service Experiment: Database Connection Pool Exhaustion

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Example Hypothesis

When the {service1} database connection pool is approaching it's limit, users of {workload} should be able to complete the {service1} user journey within the SLA of 2 seconds and other critical user journeys relating to {workload} {service2}, {service3} should continue unaffected. The {service1} circuit breaker should remain closed allowing additional connections to the database. A leading alarm should be raised and the DevOps team notified within {y} minutes. The database status report should run automatically providing the DevOps team with insight into database connection usage. 

When the {service1} database connection pool is exhausted, the {workload} {service1} circuit breaker should open resulting in users of {workload} being unable to complete the {service1} user journey. The {workload} UI should degrade gracefully and users should not be able to interact with the {service1} section of UI, thus preventing new connections to the {service1} database being created. An alarm should be raised and the DevOps team notified within {y} minutes. Other critical user journeys relating to {workload} {service2}, {service3} should continue unaffected. Once the {service1} database connection pool is drained, the {workload} {service1} circuit breaker should close with {z} minutes. Users should be able to commence interacting with the {service1} section of the UI and the steady of {n} transactions per second should resume.

## Description

This experiment tests your application's resilience to database connection pool exhaustion by:

1. **Dynamically creating** an ephemeral EC2 instance as a load generator (no pre-existing infrastructure required)
2. **Bootstrapping** the instance with the appropriate database client (PostgreSQL, MySQL, or SQL Server)
3. **Opening and holding** connections to exhaust the database connection pool
4. **Monitoring** application behavior during connection starvation
5. **Cleaning up** by releasing connections and terminating the load generator instance

The experiment is **parameterized by database engine**, making it reusable across:
- Aurora PostgreSQL
- Aurora MySQL
- RDS PostgreSQL
- RDS MySQL
- RDS SQL Server
- EC2-hosted databases

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

**Key Feature**: The automation creates and manages its own security group, requiring only VPC ID and database security group ID as inputs.

## Prerequisites

Before running this experiment, ensure that:

1. **VPC Configuration**:
   - You have a VPC with at least one subnet that can reach your database
   - You know the VPC ID and subnet ID
   - You know the security group ID attached to your database

2. **Database Configuration**:
   - Supported database is running (Aurora PostgreSQL, Aurora MySQL, RDS PostgreSQL, RDS MySQL, or RDS SQL Server)
   - Database is tagged with `FIS-Ready=True` (optional, for future targeting features)
   - You know the database endpoint, username, and password
   - Database parameter `max_connections` is configured (default: varies by instance class)

3. **IAM Roles**:
   - FIS execution role with permissions to start SSM automation
   - SSM automation role with permissions to launch EC2 instances and execute commands
   - EC2 instance profile with SSM managed instance permissions

4. **Secrets Manager** (Recommended):
   - Store database credentials in AWS Secrets Manager
   - Grant SSM automation role permission to retrieve the secret

5. **SSM Document**:
   - Deploy the SSM automation document (`database-connection-pool-exhaustion-automation.yaml`) to your account

## Parameters

The experiment supports the following parameters:

### Database Configuration
- **DatabaseEngine**: `postgres`, `mysql`, or `sqlserver` (default: `postgres`)
- **DatabaseEndpoint**: Database hostname or endpoint
- **DatabasePort**: Database port (default: 5432 for PostgreSQL)
- **DatabaseName**: Database name to connect to
- **DatabaseUser**: Database username
- **DatabasePasswordSecretArn**: ARN of Secrets Manager secret containing password
  - Note. Since we don't know the ARN of your secret ahead of time, the [sample ssm automation role ](aurora-postgres-connection-pool-exhaustion-ssm-automation-role-iam-policy.json) is given read access to all secrets, you should scope this down accordingly.

### Connection Pool Settings
- **MaxConnections**: Number of connections to open (default: 100)
- **ExperimentDuration**: Total experiment duration in ISO8601 format (default: PT10M = 10 minutes, e.g., PT1H = 1 hour, PT30M = 30 minutes)
- **RampTime**: Time to gradually ramp up to MaxConnections in ISO8601 format (default: PT1M = 1 minute, e.g., PT30S = 30 seconds, PT2M = 2 minutes, PT0S = immediate)
- **RampSteps**: Number of steps to reach MaxConnections (default: 10, e.g., 2=50% then 100%, 20=5% increments)

### Infrastructure
- **SubnetId**: Subnet ID where load generator will be launched
- **VpcId**: VPC ID where the load generator will be launched (used to create security group)
- **DatabaseSecurityGroupId**: Security group ID of the target database (automation will add temporary ingress rule)
- **InstanceType**: EC2 instance type (default: t3.small)
- **LatestAmiId**: Amazon Linux 2023 AMI ID (uses SSM parameter by default)

## How It Works

### Phase 1: Infrastructure Creation (2-3 minutes)
1. Creates a temporary security group in your VPC with name `FIS-ConnectionPool-LoadGen-<execution-id>`
2. Adds egress rule allowing traffic from load generator to database port
3. Adds ingress rule to database security group allowing traffic from load generator
4. Launches an EC2 instance in your specified subnet with the new security group
5. Instance is tagged with `FIS-Experiment=ConnectionPoolExhaustion` and `AutoCleanup=true`
6. Waits for SSM Agent to report online status

### Phase 2: Bootstrap (1-2 minutes)
4. Installs appropriate database client based on `DatabaseEngine` parameter:
   - PostgreSQL: `postgresql15` client
   - MySQL: `mysql` client
   - SQL Server: `mssql-tools` and ODBC drivers

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
9. Monitors connection success/failure rates throughout
10. All connections release simultaneously at experiment end

### Phase 4: Cleanup
10. Releases all database connections
11. Terminates the EC2 instance
12. Waits for instance termination to complete
13. Removes the ingress rule from the database security group
14. Deletes the temporary security group
15. Returns execution summary

## Stop Conditions

The experiment does not have any specific stop conditions defined by default. It will continue to run until:
- All actions complete successfully
- Manually stopped via FIS console/API
- A custom CloudWatch alarm triggers (if configured)

## Observability and Stop Conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

### Recommended Metrics to Monitor

**Database Metrics** (CloudWatch RDS/Aurora):
- `DatabaseConnections` - Should reach max_connections
- `CPUUtilization` - May increase due to connection overhead
- `FreeableMemory` - May decrease
- `ReadLatency` / `WriteLatency` - May increase

**Application Metrics**:
- Connection pool exhaustion errors
- Request timeout rates
- HTTP 5xx error rates
- Application response times

**Example CloudWatch Alarm** (Application Error Rate):
```json
{
  "AlarmName": "HighApplicationErrorRate",
  "MetricName": "5XXError",
  "Namespace": "AWS/ApplicationELB",
  "Statistic": "Sum",
  "Period": 60,
  "EvaluationPeriods": 2,
  "Threshold": 10,
  "ComparisonOperator": "GreaterThanThreshold"
}
```

## Ramp-Up Strategy and Connection Hold Times

The experiment aligns with FIS experiment duration semantics. Each connection holds until the experiment ends, creating sustained pressure throughout the experiment.

### How Connection Hold Times Work

**Key Concept**: Connections opened earlier hold longer than connections opened later, ensuring all connections remain open until experiment end.

**Example: 10-minute experiment with 5-minute ramp**
```
T=0m:   Open 20 connections → hold for 10 minutes
T=1m:   Open 20 connections → hold for 9 minutes  
T=2m:   Open 20 connections → hold for 8 minutes
T=3m:   Open 20 connections → hold for 7 minutes
T=4m:   Open 20 connections → hold for 6 minutes
T=5m:   Open 20 connections → hold for 5 minutes
T=10m:  All 100 connections close simultaneously
```

This creates a **sustained connection pool exhaustion** from the moment MaxConnections is reached until experiment end.

### Configuration Examples

```yaml
# Gentle 10-minute experiment with 5-minute ramp
ExperimentDuration: 600  # 10 minutes total
RampTimeSeconds: 300     # 5 minutes to reach max
RampSteps: 20            # 5% increments
MaxConnections: 100
# Result: Pool exhausted from T=5m to T=10m (5 minutes of sustained pressure)

# Aggressive 5-minute experiment with 1-minute ramp  
ExperimentDuration: 300  # 5 minutes total
RampTimeSeconds: 60      # 1 minute to reach max
RampSteps: 2             # 50% jumps
MaxConnections: 200
# Result: Pool exhausted from T=1m to T=5m (4 minutes of sustained pressure)

# Immediate spike with sustained hold
ExperimentDuration: 600  # 10 minutes total
RampTimeSeconds: 0       # Immediate
MaxConnections: 100
# Result: Pool exhausted from T=0 to T=10m (full 10 minutes of pressure)
```

### Validation and Auto-Adjustment

If `RampTimeSeconds` exceeds `ExperimentDuration`, the script automatically adjusts:
```yaml
ExperimentDuration: 300   # 5 minutes
RampTimeSeconds: 600      # 10 minutes (invalid!)
# Auto-adjusted to: RampTimeSeconds = 300
```

### Gradual Ramp-Up (Recommended)
Set `RampTimeSeconds` and `RampSteps` to control the ramp profile:

**Examples:**

```yaml
# Gentle ramp: 100 connections over 5 minutes in 20 steps
ExperimentDuration: 600  # 10 minutes
RampTimeSeconds: 300     # 5 minutes
RampSteps: 20
MaxConnections: 100
# Result: 5 connections every 15 seconds (5% increments)
# Sustained exhaustion: 5 minutes (from T=5m to T=10m)

# Moderate ramp: 100 connections over 2 minutes in 10 steps  
ExperimentDuration: 600  # 10 minutes
RampTimeSeconds: 120     # 2 minutes
RampSteps: 10
MaxConnections: 100
# Result: 10 connections every 12 seconds (10% increments)
# Sustained exhaustion: 8 minutes (from T=2m to T=10m)

# Aggressive ramp: 200 connections over 2 minutes in 2 steps
ExperimentDuration: 300  # 5 minutes
RampTimeSeconds: 120     # 2 minutes
RampSteps: 2
MaxConnections: 200
# Result: 100 connections at T=0 (hold 5m), 100 at T=1m (hold 4m)
# Sustained exhaustion: 3 minutes (from T=2m to T=5m)
```

### Immediate Mode
Set `RampTimeSeconds=0`:
- All connections open as quickly as possible
- All connections hold for full `ExperimentDuration`
- `RampSteps` is ignored in this mode
- Simulates sudden connection spike with maximum sustained pressure
- Useful for testing worst-case scenarios

**Recommendation**: Start with gradual ramp-up (e.g., ExperimentDuration=600s, RampTimeSeconds=120s, RampSteps=10) to observe how your application degrades under increasing connection pressure, with sustained exhaustion for the remaining time.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. **Start Small**: Begin with `MaxConnections` well below your database's `max_connections` limit
2. **Use Gradual Ramp-Up**: Set `RampTimeSeconds=120` and `RampSteps=10` to observe progressive degradation
3. **Adjust Aggressiveness**: Fewer steps (2-5) = more aggressive, more steps (10-20) = gentler ramp
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
   - Connection pooling with max pool size limits
   - Connection timeout configurations
   - Retry logic with exponential backoff
   - Circuit breakers for database calls
5. **Monitor Cleanup**: Verify the EC2 instance is terminated after the experiment
6. **Cost Optimization**: Use smaller instance types (t3.micro) if connection count allows

## Security Considerations

- **Credentials**: Always use Secrets Manager for database passwords
- **Network Isolation**: Use private subnets and security groups to restrict access
- **IAM Permissions**: Follow least privilege principle for all IAM roles
- **Cleanup**: The automation includes error handling to ensure instance termination even on failure

## Connection Keepalive and Timeout Handling

### Keepalive Mechanism

The experiment uses a **keepalive loop** to maintain connections throughout the experiment duration:

- Each connection sends a lightweight query (`SELECT 1`) every 30 seconds
- Prevents idle connection timeouts from closing connections prematurely
- Works around network device idle timeouts (NAT gateways, load balancers)
- More realistic than single long-running query (mimics real application behavior)

### Why Keepalive is Necessary

Without keepalive, connections could be closed by:

1. **Database idle timeouts**:
   - PostgreSQL: `idle_in_transaction_session_timeout`
   - MySQL: `wait_timeout`, `interactive_timeout`
   - SQL Server: Connection timeout settings

2. **Network infrastructure timeouts**:
   - NAT Gateway: 350 seconds idle timeout (default)
   - Load balancers: Various idle timeout settings
   - Stateful firewalls: Connection tracking timeouts

3. **Client library timeouts**:
   - Database client tools may have their own timeout settings

### Database Parameter Considerations

While the keepalive mechanism handles most timeout scenarios, you may want to verify these database parameters:

**PostgreSQL/Aurora PostgreSQL:**
```sql
-- Check statement timeout (0 = disabled)
SHOW statement_timeout;

-- Check idle in transaction timeout (0 = disabled)  
SHOW idle_in_transaction_session_timeout;
```

**MySQL/Aurora MySQL:**
```sql
-- Check wait timeout (default: 28800 seconds = 8 hours)
SHOW VARIABLES LIKE 'wait_timeout';

-- Check interactive timeout
SHOW VARIABLES LIKE 'interactive_timeout';

-- Check max execution time (0 = disabled)
SHOW VARIABLES LIKE 'max_execution_time';
```

**SQL Server:**
```sql
-- Check connection timeout settings
SELECT * FROM sys.configurations WHERE name LIKE '%timeout%';
```

**Note**: The keepalive approach (30-second query interval) should work with default database settings for most RDS/Aurora configurations. Explicit timeout adjustments are typically not required.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).

## Troubleshooting

### Instance Not Launching
- Verify subnet has available IP addresses
- Check IAM instance profile exists and has SSM permissions
- Ensure AMI ID is valid for your region
- Verify VPC ID is correct

### Security Group Creation Fails
- Check SSM automation role has `ec2:CreateSecurityGroup` permission
- Verify VPC ID is correct and accessible
- Ensure security group limit not exceeded in VPC

### Cannot Connect to Database
- Verify database security group ID is correct
- Check database endpoint is correct and reachable
- Confirm database credentials in Secrets Manager are valid
- Verify subnet has route to database (same VPC or VPC peering/transit gateway configured)

### Connections Not Exhausting Pool
- Increase `MaxConnections` parameter
- Verify database `max_connections` setting
- Check if connections are being closed prematurely

### Instance Not Terminating
- Check SSM automation execution logs
- Manually terminate instances tagged with `AutoCleanup=true`
- Review IAM permissions for EC2 termination

### Security Group Not Deleted
- Verify instance was terminated first (security groups can't be deleted while in use)
- Check for any remaining network interfaces attached to the security group
- Manually delete security groups with name pattern `FIS-ConnectionPool-LoadGen-*`

## Cost Estimate

Approximate costs per experiment run:
- EC2 instance (t3.small): ~$0.02/hour
- Data transfer: Negligible for connection testing
- CloudWatch Logs: ~$0.01

**Total per 5-minute experiment**: < $0.05

## Related Experiments

- `aurora-cluster-failover` - Test Aurora failover behavior
- `aurora-postgres-cluster-loadtest-failover` - Combined load and failover testing for Aurora PostgreSQL
- `mysql-rds-loadtest-failover` - Combined load and failover testing for MySQL RDS
- `elasticache-redis-connection-failure` - Similar connection exhaustion pattern for Redis
