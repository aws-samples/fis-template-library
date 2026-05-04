# AWS Fault Injection Service Experiment: Database Blocking Locks

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Example Hypotheses

When the {service1} database is subjected to row-level blocking locks, the engine-specific blocked-waiter signal for {workload} should climb in a predictable, stepped pattern that tracks the `WaiterCount` ramp, and operations should be able to detect the event within {y} minutes via the engine-specific blocked-waiter metric (Aurora MySQL `BlockedTransactions`, RDS SQL Server `db.General Statistics.Processes blocked`, or the lock-tree view in CloudWatch Database Insights for PostgreSQL). Other critical user journeys relating to {workload}; {service2} and {service3} should continue unaffected. A leading alarm should be raised and the DevOps team notified within {y} minutes.

When the `ExperimentDuration` elapses and the Blocker session COMMITs, all Waiter sessions should unblock, complete their UPDATEs, and close, and the engine-specific blocked-waiter metric should return to baseline within {z} minutes without manual database intervention. The steady state of {n} transactions per second against {service1} should resume.

### What does this enable me to verify?

* Appropriate customer experience metrics and observability of your database are in place (were you able to detect the blocked-waiter signal as it climbed with the Waiter ramp?)
* Alarms are configured correctly on the engine-specific blocked-waiter metric (were the right people notified at the right time and/or automations triggered?)
* Your application gracefully handles transactions that block on contended rows (retries, timeouts, circuit breakers)
* Recovery controls (if any) work as expected once the Blocker releases its lock

## Description

This experiment tests your application's resilience to database row-level lock contention by:

1. **Dynamically creating** an ephemeral EC2 instance as a load generator
2. **Bootstrapping** the instance with the appropriate database client (PostgreSQL, MySQL, or SQL Server)
3. **Opening one Blocker session** that holds a row-level lock on a dedicated `fis_blocking_locks_target` table for the full `ExperimentDuration`
4. **Ramping in `WaiterCount` Waiter sessions** over `RampTime` across `RampSteps` evenly spaced steps, where each Waiter opens a connection, begins a transaction, and issues an `UPDATE` against the Blocker-held row so that it shows up as a blocked transaction on the database
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
   - You have stored the database password as an AWS Secrets Manager secret and know its ARN. The secret can be either a raw string or a JSON document with a `password` key (the shape used by the RDS-managed master password secret).

### Create Required Experiment Resources

1. **Experiment template**:
   - Import the FIS experiment template (`database-blocking-locks-template.json`) into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).

2. **IAM Roles**: Create the following IAM roles in your account using the sample policies provided:
   - FIS execution role (`DatabaseBlockingLocks-FIS-Role`) with permissions to start SSM automation
   - SSM automation role (`DatabaseBlockingLocks-SSM-Automation-Role`) with permissions to launch EC2 instances, execute commands, read the database password from Secrets Manager, and manage the ephemeral security group
   - EC2 instance profile (`SSM-Managed-Instance-Profile`) with the `AmazonSSMManagedInstanceCore` managed policy attached

3. **SSM Document**:
   - Deploy the SSM automation document (`database-blocking-locks-automation.yaml`) to your account

## Parameters

The experiment requires the following parameters:

### Database Configuration
- **DatabaseEngine**: `postgres`, `mysql`, or `sqlserver` (default: `postgres`)
- **DatabaseEndpoint**: Database DNS hostname or endpoint
- **DatabasePort**: Database port (default: 5432 for PostgreSQL, use 3306 for MySQL, 1433 for SQL Server)
- **DatabaseName**: Database name to connect to e.g.
  - PostgreSQL: `postgres` (default system database)
  - MySQL: `mysql` (default system database)
  - SQL Server: `master` (default system database)
- **DatabaseUser**: Database username (default: `postgres`)
- **DatabasePasswordSecretArn**: ARN of Secrets Manager secret containing password
  - **Note** Since we don't know the ARN of your secret ahead of time, the sample SSM automation role ([database-blocking-locks-ssm-automation-role-iam-policy.json](database-blocking-locks-ssm-automation-role-iam-policy.json)) is given read access to all secrets, you should probably scope this down accordingly.

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
    3. Issues `UPDATE fis_blocking_locks_target SET counter = counter + 1 WHERE id = 1`
    4. Blocks on the Blocker's row lock
14. Example: `WaiterCount=50`, `RampTime=PT1M`, `RampSteps=10` produces 10 steps of 5 Waiters each, roughly 6 seconds apart, so the engine-specific blocked-waiter metric climbs in ten 5-unit increments.

### Phase 5: Cleanup
15. When `ExperimentDuration` elapses, the Blocker COMMITs and closes its connection.
16. Every Waiter's blocked `UPDATE` returns, the Waiter COMMITs, and the Waiter closes its connection.
17. The harness joins all Waiter threads.
18. If this run created the `fis_blocking_locks_target` table, the harness drops it. If a pre-existing matching table was reused, the harness leaves it in place.
19. The automation terminates the EC2 instance, waits for termination to complete, revokes the ingress rule from the database security group, and deletes the ephemeral security group.

## Stop Conditions

The experiment template does not have any specific stop conditions defined by default. It will continue to run until:
- All actions complete successfully or one fails
- Manually stopped via FIS console/API
- A custom CloudWatch alarm triggers (if configured)

## Observability and Stop Conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

### Where to look for the blocked-waiter signal per engine

The engine-specific metric that reflects blocked waiters is different for each supported engine. Each Waiter that is currently blocked on the Target_Row contributes approximately 1 to the corresponding count, and the `ExperimentDuration` parameter directly controls how long the Blocker holds the row lock.

- **Aurora MySQL**: the `BlockedTransactions` Amazon CloudWatch metric at the instance level.
- **RDS SQL Server**: the `db.General Statistics.Processes blocked` counter in Performance Insights.
- **Aurora PostgreSQL and RDS PostgreSQL**: blocked waiters are surfaced via lock-tree analysis in **CloudWatch Database Insights (Advanced mode)** rather than as a top-level CloudWatch metric.

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
3. **Create a CloudWatch Alarm on the Blocked-Waiter Metric**: Build a CloudWatch alarm on the engine-specific metric that reflects blocked waiters (`BlockedTransactions` on Aurora MySQL, `db.General Statistics.Processes blocked` on RDS SQL Server, or a Database Insights lock-tree metric on PostgreSQL).
4. **Add the Alarm as an FIS Stop Condition**: Attach that alarm as a `stopConditions` entry on the FIS experiment template so the experiment auto-halts if the blocked-waiter count exceeds a threshold that would be unsafe in your environment.
5. **Run the DBA Pre-flight Check**: Confirm that `idle_in_transaction_session_timeout` is unset, zero, or greater than `ExperimentDuration` before running against any shared database.
6. **Monitor Cleanup**: Verify that the EC2 instance is terminated, the ephemeral security group is deleted, and the `fis_blocking_locks_target` table is gone (if this run created it) after the experiment.

## Import Experiment

To import the experiment template into your AWS account, follow the step-by-step instructions in the [fis-template-library-tooling](https://github.com/aws-samples/fis-template-library-tooling) repository, which supports both AWS CLI and AWS CDK based deployment.
