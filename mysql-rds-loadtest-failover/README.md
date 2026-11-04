# AWS Fault Injection Service Experiment: MySQL RDS Load Test and Failover

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Description

This experiment runs a database load test against a Multi-AZ Amazon RDS for MySQL DB instance from an EC2 instance, and forces a failover 5 minutes after the experiment starts, while the load test is still running. It tests how your database and application behave when the primary changes under load. In our tests with a db.t3.micro instance, the load raised the instance's CPU utilization to 95-97%.

## Hypothesis

When high CPU load is generated on a Multi-AZ MySQL RDS instance followed by a failover event, the system will transition from the primary to the standby instance with approximately 25 seconds of downtime, and applications implementing proper connection handling will automatically reconnect with a success rate of nearly 100%, maintaining normal functionality once the failover process completes.

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment and to create the resources listed below.
2. The IAM role specified in the `roleArn` field has the permissions in `mysql-rds-loadtest-failover-iam-policy.json` and the trust policy in `fis-iam-trust-relationship.json`. Replace `<YOUR ROLE NAME>` in the template with the role's name.
3. The MySQL DB instance you want to target is a Multi-AZ DB instance deployment (a primary with a standby) and has the `FIS-Ready=True` tag.
4. The EC2 instance that generates the load has the `FIS-Ready=True` tag and meets the requirements in [EC2 Instance Setup](#ec2-instance-setup).
5. Both targets use `selectionMode` `ALL`. `ForceFailover` reboots, with failover, every RDS DB instance in the Region that has the tag, and every EC2 instance that has the tag runs the load test. RDS can only force a failover on a DB instance configured for Multi-AZ, so tag only Multi-AZ DB instances, and check which resources in the Region carry the tag, including those of other workloads, before you start the experiment. We tested with one tagged DB instance and one tagged EC2 instance.
6. In the same Region, you have created:
   - the SSM document `MySQL-LoadTest-Document` from `mysql-rds-loadtest-failover-ssm-template.json`. The template refers to the document by this name.
   - a Secrets Manager secret that holds the database user's password, either as JSON with a `password` key (for example, the secret that RDS manages for the master user) or as a plain string. The document reads the password from it on the instance at run time.
   - the CloudWatch Logs log group `/aws/fis/experiment`. The template sends the experiment log there.
7. In the template's `documentParameters`, you have replaced `<YOUR DB ENDPOINT>` with the DB instance endpoint, and set `DBSecretId` to the secret's name or ARN (the default is `mysql-rds-password`). Also replace `<YOUR REGION>` and `<YOUR AWS ACCOUNT>`. To use another port, database or user, set `DBPort`, `DBName` or `DBUsername` (defaults `3306`, `testdb` and `admin`; a user name may contain letters, digits, `_`, `.`, `@` and `-`). The user must be able to create the database `DBName` if it doesn't exist, and to create a table in it. If `DBHost` isn't the DB instance endpoint, also set `DBInstanceId`, so that the load test can report the DB instance's CPU utilization.

The template doesn't put a password in the experiment. The document's `DBPassword` parameter still exists for compatibility, but a value there is stored in the experiment template, the experiment, the experiment log, the command's parameters and the command script on the instance, so leave it empty.

## Architecture Overview

This experiment uses the following components:

- **DB instance**: The Multi-AZ RDS for MySQL DB instance that receives the load and fails over
- **EC2 Load Generator Instance**: Runs the SSM document that generates the database load
- **SSM Document**: Installs the MySQL client, reads the password from Secrets Manager and runs the load test queries
- **FIS Experiment**: Starts the load test and, 5 minutes later, the failover

**Critical**: The EC2 instance acts as the load generator and must be able to connect to your DB instance. The SSM document runs on this instance, not on the DB instance.

## EC2 Instance Setup

Your EC2 instance must meet these requirements:

1. **Network Access**: The instance's security group allows outbound connections to the DB instance on port 3306 (or the port you set in `DBPort`), and the DB instance's security group allows inbound connections from the instance on that port. The instance also needs outbound HTTPS to Systems Manager, Secrets Manager, CloudWatch and the operating system's package repositories.
2. **MySQL Client and AWS CLI**: The SSM document's first step installs the client, `bc` and `jq`: `mariadb105` on Amazon Linux 2023 (which has no `mysql` package), `mysql` on Amazon Linux 2, CentOS and RHEL, and `mysql-client` on Ubuntu and Debian. It fails on other operating systems, and if the installation takes longer than 240 seconds. We tested only Amazon Linux 2023. The document also runs the AWS CLI (`aws`) to read the secret and the CPU utilization, and doesn't install it. Amazon Linux AMIs include it; on other images, install it first.
3. **SSM Agent**: Ensure SSM Agent is installed and the instance appears in Systems Manager
4. **IAM Role**: Attach an instance profile whose role has the `AmazonSSMManagedInstanceCore` policy and `secretsmanager:GetSecretValue` on the secret, plus `kms:Decrypt` on its key, allowed by the key policy, if the secret uses a customer managed key. Add `cloudwatch:GetMetricStatistics` (resource `*`) if you want the load test to report the DB instance's CPU utilization; without it the document reports the CPU utilization as not available.
5. **Tagging**: Tag the instance with `FIS-Ready=True`

Test connectivity from the instance before running the experiment. The document installs the client in its first step, so install it yourself for this test (on Amazon Linux 2023, `sudo dnf install -y mariadb105`):
```bash
mysql -h your-rds-endpoint -u your-username -p -e "SELECT 1;"
```

## ⚠️ Database Impact Warning

**IMPORTANT**: This experiment will create a test table in your MySQL database:

### Tables Created:
- `loadtest` - Load testing table with auto-increment primary key
- Test database (if `DBName` parameter specifies a non-existing database)

### Impact:
- Tables will persist after the experiment completes
- Test data will be inserted during load testing: in our tests about 30 rows per second, or about 17,000-18,000 rows in a 10-minute run
- No existing data will be modified or deleted. Use a database that has no other table named `loadtest`, such as the default `testdb`: the load test inserts into an existing `loadtest` table.
- Tables use `IF NOT EXISTS` clauses to avoid conflicts

### Cleanup:
If you need to remove what the experiment created, drop the table (replace `testdb` if you set `DBName`):
```sql
DROP TABLE IF EXISTS testdb.loadtest;
```
If the experiment created the database and nothing else uses it, you can drop the database instead:
```sql
DROP DATABASE IF EXISTS testdb;
```

## How it works

This experiment runs a database load test and fails over the DB instance while the load runs:

1. **Load generation**: `RunLoadTest` starts with the experiment and runs for 11 minutes. It runs the SSM document on the load generator with `Duration` 600, `Concurrency` 25 and `TargetCPU` 80. The document installs the MySQL client, reads the password from the secret, checks the connection, creates the database and the `loadtest` table if they don't exist (it stops if it can't create the table), and starts 25 workers. Each worker repeats an insert and four queries, each over a new connection with a 15-second timeout, until the 600 seconds are up. Every 30 seconds the document reports the number of running workers, the database connections and the DB instance's CPU utilization. Reaching `TargetCPU` is only reported: the template decides when the failover starts.
2. **Warm-up**: `WaitBeforeFailover` starts at the same time and waits 5 minutes.
3. **Failover**: `ForceFailover` then reboots the DB instance with failover, which makes the standby the new primary while the load test is still running.
4. **After the failover**: the workers reconnect through the DB instance endpoint, which now points to the new primary, and the load runs on until its 600 seconds are up. `StopLoadTest` runs after `RunLoadTest` ends and stops any worker that is still running, for example if you set `Duration` longer than `RunLoadTest`'s duration.

If you change the timing, keep `WaitBeforeFailover`'s duration at least 1 minute shorter than `Duration`, so the failover completes while the load runs, and keep `RunLoadTest`'s duration at least 1 minute longer than `Duration`, to cover the installation and setup steps, so that stopping the experiment cancels the load. `Duration` accepts 1 to 780 seconds, so that setup and the load finish before the document's load step times out after 900 seconds.

Measured in our tests, over 8 failovers, with a db.t3.micro instance running MySQL 8.4 and an Amazon Linux 2023 load generator:
- The load raised the DB instance's CPU utilization to 95-97% and held 24-26 database connections at its peak.
- RDS reported the failover complete 25-55 seconds after it started.
- New connections, tried once per second, failed for 12-16 seconds in each failover, and all attempts after that succeeded.
- The load continued on the new primary after the failover, and ended with the document's 600 seconds, before `RunLoadTest` ended.

The experiment targets resources with the `FIS-Ready=True` tag for safety and control.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until `StopLoadTest` finishes, about 12 minutes after the experiment starts. If you stop the experiment while `RunLoadTest` runs, FIS cancels the load test's command and the load stops: in our tests it stopped within 7 seconds of the stop, both before and after the failover, and no load test process or credentials file was left on the instance. A stop during the warm-up also cancels the failover. Stopping doesn't stop or undo a failover that FIS has already started. If the load test fails, for example because the instance can't read the secret, FIS fails `RunLoadTest` and ends the experiment before the failover: in our test with a secret the instance couldn't read, the experiment failed within a minute and the failover was cancelled.

Stop conditions are based on an AWS CloudWatch alarm based on an operational or 
business metric requiring an immediate end of the fault injection. This 
template makes no assumptions about your application and the relevant metrics 
and does not include stop conditions by default.

During the experiment, watch the DB instance's `CPUUtilization` and `DatabaseConnections` metrics, its RDS events (`Multi-AZ instance failover started` and `Multi-AZ instance failover completed`), and your application's response times and error rates.

## Files included

- `mysql-rds-loadtest-failover-template.json`: Main FIS experiment template
- `mysql-rds-loadtest-failover-iam-policy.json`: Required IAM permissions
- `mysql-rds-loadtest-failover-ssm-template.json`: SSM document for load testing
- `fis-iam-trust-relationship.json`: IAM trust policy for FIS service

## Next Steps
As you adapt this scenario to your needs, we recommend:
1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to your DB instance's performance.
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of high CPU load and failover.
4. Adding a stop condition tied to the alarm to automatically halt the experiment if critical thresholds are breached.
5. Customizing the SSM document parameters to adjust load test concurrency, duration, and target CPU utilization, within the timing rules in [How it works](#how-it-works).
6. Testing the experiment in a non-production environment first, and checking how your application's connection handling copes with the primary change.

## Import Experiment
You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
