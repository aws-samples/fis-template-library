# AWS Fault Injection Service Experiment: MySQL RDS Load Test and Failover

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Description

This experiment runs a database load test against a Multi-AZ Amazon RDS for MySQL DB instance from an EC2 instance, and forces a failover 5 minutes after it starts the load test, while the load test is still running. The load test fails the experiment unless a failover started and completed while it ran. It tests how your database and application behave when the primary changes under load. In our tests with a db.t3.micro DB instance, the load raised the instance's CPU utilization to 94% in a run to completion.

## Hypothesis

If a Multi-AZ RDS for MySQL DB instance is forced to fail over while the load test runs against it, the time during which new connections to the DB instance endpoint fail should not exceed 60 seconds, and every connection attempt after that should succeed. Replace 60 seconds with the gap your application can tolerate.

To check it, open a new connection to the DB instance endpoint every second during the experiment, or watch your application's connection errors, and measure how long new connections fail after the failover starts. A gap longer than your threshold, or failed attempts after connections succeed again, proves the hypothesis false. The load test also reports whether the DB instance's CPU utilization reached `TargetCPU` (80%). On a DB instance class larger than the one we tested, raise `Concurrency` for a heavier load.

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment and to create the resources listed below.
2. The IAM role specified in the `roleArn` field has the permissions in `mysql-rds-loadtest-failover-iam-policy.json` and the trust policy in `fis-iam-trust-relationship.json`. In the policy, replace `<YOUR REGION>` and `<YOUR AWS ACCOUNT>`. If you name the SSM document something other than `MySQL-LoadTest-Document`, change its name in the policy and in the template's `documentArn`. Replace `<YOUR ROLE NAME>` in the template with the role's name.
3. The MySQL DB instance you want to target is a Multi-AZ DB instance deployment (a primary with a standby) and has the `FIS-Ready=True` tag.
4. The EC2 instance that generates the load has the `FIS-Ready=True` tag and meets the requirements in [EC2 Instance Setup](#ec2-instance-setup).
5. Both targets use `selectionMode` `ALL`. `ForceFailover` reboots, with failover, every RDS DB instance in the Region that has the tag, and every EC2 instance that has the tag runs the document. Only one load test runs against a DB instance at a time (see [How it works](#how-it-works)), so with two tagged EC2 instances the document stops at setup and fails on one of them: tag exactly one EC2 instance. RDS can only force a failover on a DB instance configured for Multi-AZ, so tag only Multi-AZ DB instances, and check which resources in the Region carry the tag, including those of other workloads, before you start the experiment. We tested with one tagged DB instance and one tagged EC2 instance.
6. In the same Region, you have created:
   - the SSM document `MySQL-LoadTest-Document` from `mysql-rds-loadtest-failover-ssm-template.json`. The template refers to the document by this name.
   - a Secrets Manager secret that holds the database user's password, either as JSON with a `password` key (for example, the secret that RDS manages for the master user) or as a plain string. The document reads the password from it on the instance at run time.
   - the CloudWatch Logs log group `/aws/fis/experiment`. The template sends the experiment log there.
7. In the template's `documentParameters`, you have replaced `<YOUR DB ENDPOINT>` with the DB instance endpoint, and set `DBSecretId` to the secret's name or ARN (the default is `mysql-rds-password`). Also replace `<YOUR REGION>` and `<YOUR AWS ACCOUNT>`. To use another port, database or user, set `DBPort`, `DBName` or `DBUsername` (defaults `3306`, `testdb` and `admin`; a user name may contain letters, digits, `_`, `.`, `@` and `-`). The user needs CREATE on the database `DBName` (to create it if it doesn't exist, and to create the `loadtest` table in it), and INSERT and SELECT on the table. It also needs CREATE on the database `fis_loadtest`, and INSERT, UPDATE and SELECT on its table `loadtest_lock`, which holds the lock that keeps a second load test off the DB instance. MySQL rejects a grant on a table that doesn't exist yet unless the same `GRANT` includes CREATE, so for a user other than the master user, grant these before the first run with statements like these (replace `testdb` if you set `DBName`, and `fis_user` with your user):
   ```sql
   GRANT CREATE ON testdb.* TO 'fis_user'@'%';
   GRANT CREATE, INSERT, SELECT ON testdb.loadtest TO 'fis_user'@'%';
   GRANT CREATE ON fis_loadtest.* TO 'fis_user'@'%';
   GRANT CREATE, INSERT, UPDATE, SELECT ON fis_loadtest.loadtest_lock TO 'fis_user'@'%';
   ```
   `DBHost` must be the DB instance's endpoint: before it reads the password or connects, the document checks that `DBHost` is the endpoint of a DB instance in the same account and Region that has the `FIS-Ready=True` tag, and stops if it isn't. `DBInstanceId` can stay empty, since the document takes the identifier from the first part of `DBHost`.

The template doesn't put a password in the experiment. The document's `DBPassword` parameter still exists for compatibility, but a value there is stored in the experiment template, the experiment, the experiment log, the command's parameters and the command script on the instance, so leave it empty.

We tested in us-west-2 with RDS for MySQL 8.4.11 on a Multi-AZ DB instance (not a Multi-AZ DB cluster) of class db.t3.micro, the master user and a user with only the privileges above (both with `caching_sha2_password`), and a t3.small load generator running the standard Amazon Linux 2023 AMI, SSM Agent 3.3.5390.0 and the MariaDB 10.5 client.

## Architecture Overview

This experiment uses the following components:

- **DB instance**: The Multi-AZ RDS for MySQL DB instance that receives the load and fails over
- **EC2 Load Generator Instance**: Runs the SSM document that generates the database load
- **SSM Document**: Installs the MySQL client, checks that `DBHost` is the endpoint of a DB instance with the `FIS-Ready=True` tag, reads the password from Secrets Manager, takes the DB instance's load test lock and runs the load test queries
- **FIS Experiment**: Starts the load test and, 5 minutes later, the failover

**Critical**: The EC2 instance acts as the load generator and must be able to connect to your DB instance. The SSM document runs on this instance, not on the DB instance.

## EC2 Instance Setup

Your EC2 instance must meet these requirements:

1. **Network Access**: The instance's security group allows outbound connections to the DB instance on port 3306 (or the port you set in `DBPort`), and the DB instance's security group allows inbound connections from the instance on that port. The instance also needs outbound HTTPS to Systems Manager, Secrets Manager, CloudWatch, the Amazon RDS API and, on Amazon Linux 2023, the operating system's package repositories.
2. **MySQL Client, AWS CLI and other tools**: On Amazon Linux 2023, the SSM document's first step installs whichever of the MySQL client (`mariadb105`, since Amazon Linux 2023 has no `mysql` package), `bc` and `jq` are missing. On other operating systems, install a MySQL client, `bc`, `jq`, the AWS CLI and GNU coreutils before you run the experiment. The first step stops the document, before any load, if the install fails or takes longer than 120 seconds, or if any of these tools is missing. We tested only Amazon Linux 2023 and its MariaDB 10.5 client. The standard Amazon Linux 2023 AMI, which we tested, includes the AWS CLI and GNU coreutils. The document runs the AWS CLI to check the DB instance and to read the secret, the CPU utilization and the RDS events. The packages stay installed after the experiment. To remove them, find the document's installs in `sudo dnf history list` (command line `install -y` followed by the package names; a run after a stopped install can add a second one), and undo each with `sudo dnf history undo <ID>`, without `-y`: dnf lists what it will remove and asks before it does, so check that the list has only what the document installed. A stop during the install leaves a transaction marked as failed there, which lists the packages it was installing. If dnf can't undo it, remove the packages it lists that are installed with `sudo dnf remove <packages>`, again without `-y`, and check the list before you confirm.
3. **SSM Agent**: Ensure SSM Agent 3.0.502 or later is installed, which the document's `onFailure` setting needs ([shared inputs](https://docs.aws.amazon.com/systems-manager/latest/userguide/documents-command-ssm-plugin-reference.html#shared-inputs)), and that the instance appears in Systems Manager
4. **IAM Role**: Attach an instance profile whose role has the `AmazonSSMManagedInstanceCore` policy; `rds:DescribeDBInstances` and `rds:DescribeEvents` (resource `*`), which the document uses to check the DB instance's endpoint and tag, and that a failover started and completed while the load ran; and `secretsmanager:GetSecretValue` on the secret, plus `kms:Decrypt` on its key, allowed by the key policy, if the secret uses a customer managed key. Add `cloudwatch:GetMetricStatistics` (resource `*`) if you want the load test to report the DB instance's CPU utilization; without it the document reports the CPU utilization as not available.
5. **Tagging**: Tag the instance with `FIS-Ready=True`

Test connectivity from the instance before running the experiment. On Amazon Linux 2023 the document installs the client in its first step, so install it yourself for this test (`sudo dnf install -y mariadb105`):
```bash
mysql -h your-rds-endpoint -u your-username -p -e "SELECT 1;"
```

## ⚠️ Database Impact Warning

**IMPORTANT**: This experiment will create a test table in your MySQL database:

### Tables Created:
- `loadtest` - Load testing table with auto-increment primary key
- Test database (if `DBName` parameter specifies a non-existing database)
- `fis_loadtest.loadtest_lock` - one row, the lock that lets only one load test run against the DB instance at a time, in the database `fis_loadtest`, which the document creates if it doesn't exist

### Impact:
- Tables will persist after the experiment completes
- Test data will be inserted during load testing: one row when the document checks that it can write, then, in our run to completion, about 15,600 rows in the 10-minute load, about 26 per second
- Each run adds rows to `loadtest`. The load's four queries read only the rows inserted after the run's setup, so the rows that earlier runs left in the table don't make the load heavier.
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
When no load test runs against the DB instance, you can also drop the lock's database:
```sql
DROP DATABASE IF EXISTS fis_loadtest;
```

## How it works

This experiment runs a database load test and fails over the DB instance while the load runs:

1. **Load generation**: `RunLoadTest` starts with the experiment and runs the SSM document on the load generator with `Duration` 600, `Concurrency` 25 and `TargetCPU` 80. On Amazon Linux 2023 the document installs the MySQL client, and it stops if the install fails. It then checks that `DBHost` is the endpoint of a DB instance in the account and Region with the `FIS-Ready=True` tag, reads the password from the secret, checks the connection, creates the database and the `loadtest` table if they don't exist, inserts one row and reads the table's largest id. It then takes the DB instance's load test lock, the row in `fis_loadtest.loadtest_lock`, which it holds until `Duration` plus 3 minutes from then by the DB instance's clock (UTC), and releases when it ends. If it can't release the lock, it says until when the lock is held, and fails. If another load test holds the lock, from this or another load generator and with any `DBName`, the document stops before its load. It stops if it can't do any of these. It then starts 25 workers. Each worker repeats an insert and four queries, each over a new connection with a 15-second timeout, until the 600 seconds are up. The insert turns autocommit on first, so its row commits even where the DB instance starts sessions with autocommit off. The four queries read only the rows inserted after the setup: those with an id larger than the one the setup read. Every 30 seconds the document reports the number of running workers, how many queries succeeded since the last report, the connections of `DBUsername` (every session of that user, not only the load test's) and the DB instance's CPU utilization. Reaching `TargetCPU` is only reported: the template decides when the failover starts.
2. **Warm-up**: `WaitBeforeFailover` starts at the same time and waits 5 minutes. The load starts after FIS delivers the command, the install (up to 120 seconds) and the setup (up to 150 seconds), so it normally runs for less than 5 minutes before the failover starts. If it starts after the failover, the document fails the run, as listed below.
3. **Failover**: `ForceFailover` then reboots the DB instance with failover, which makes the standby the new primary while the load test is still running.
4. **After the failover**: the workers reconnect through the DB instance endpoint, which now points to the new primary, and the load runs on until its 600 seconds are up. The document then stops those of its own background jobs that are still running, so it doesn't stop the load of another run on the same load generator. `RunLoadTest` shows as completed when the load command ends, about 10 minutes after the start, but the experiment ends only when `RunLoadTest`'s duration has passed, 25 minutes after it started.

The document fails, and with it `RunLoadTest` and the experiment, if the load didn't run as the experiment needs:
- no query has succeeded 60 seconds after the workers started;
- after that, no query has succeeded for more than 180 seconds, which is longer than the 60-120 seconds a failover typically takes ([RDS failover](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.MultiAZ.Failover.html)). That also happens if the password changes during the run, for example when Secrets Manager rotates the secret, or if the DB instance accepts no queries for that long after the failover;
- all workers stop before the 600 seconds are up;
- no query succeeded in the last 30 seconds of the load;
- after the load, the DB instance's RDS events from the start to the end of the load don't show a failover that started (RDS-EVENT-0013, `Multi-AZ instance failover started`) and then completed (RDS-EVENT-0049, `Multi-AZ instance failover completed`, or RDS-EVENT-0015, `Multi-AZ failover to standby complete`), or no query succeeded after it completed. That happens if the install and setup took longer than the wait, if the load ended before the failover completed, or if the load had stopped;
- those events show that RDS abandoned a requested failover because a failover had recently occurred (RDS-EVENT-0034). That can happen when something else failed the DB instance over shortly before, such as another experiment or a reboot with failover. The run can't tell whose failover RDS abandoned, so it fails.

If you change the timing, keep `WaitBeforeFailover`'s duration longer than 270 seconds plus the time FIS takes to deliver the command, since the install and the setup can take 270 seconds together, and at least 4 minutes shorter than `Duration`, so that the failover, which typically takes 60-120 seconds, completes while the load runs and the load runs on the new primary after it. With the template's 5-minute wait, that means a `Duration` of at least 540 seconds; below about 520 seconds, no wait meets both rules. Keep `RunLoadTest`'s duration longer than the document can run, 19 minutes: its install and load steps time out after 120 and 1,020 seconds. The template uses 25 minutes, and the experiment lasts as long as that duration. The load then ends while `RunLoadTest` runs, and stopping the experiment at any point cancels it. `Duration` accepts 1 to 780 seconds, so that the setup, the load, its last report, the failover check and the release of the lock finish before the load step times out.

Measured in our tests, with a db.t3.micro DB instance running MySQL 8.4.11 and an Amazon Linux 2023 load generator, in one run to completion and one run stopped 2 minutes after its failover:
- The load raised the DB instance's CPU utilization to 94% in the run to completion and to 77% in the stopped run, and held at most 26 load-generator sessions in each.
- RDS reported the failover complete 45 and 60 seconds after it started.
- New connections from another client, tried once per second, failed for 11 and 14 seconds, and every attempt after that succeeded.
- The load ran on the new primary after the failover, and in the run to completion it ended with the document's 600 seconds. `RunLoadTest` showed as completed 2 seconds after the load command ended, and the experiment ended 25 minutes after `RunLoadTest` started.

If two experiments run against the same DB instance at once, the document of the one that reaches the lock second, normally the one started later, finds the lock and stops at setup, so that experiment's `RunLoadTest` fails and FIS cancels its failover. The other run continues. In our test with a second experiment started 3 minutes 25 seconds after the first, the second stopped at setup 23 seconds after its document started, the first ran to completion, and the load generator held at most 30 sessions.

The experiment targets resources with the `FIS-Ready=True` tag for safety and control, and the load test loads only a DB instance that has the tag.

### What else is affected

- Every client of the DB instance, not only the load test: the failover closes every connection, new connections fail until the endpoint points to the new primary, and the load raises the CPU utilization that all clients share for as long as it runs. The load sets no limit on how long its queries run on the DB instance: a worker gives up on a query after 15 seconds, but the DB instance goes on running it. If the DB instance slows down, for example when it runs short of memory, such queries can hold sessions, and if they use up the DB instance's connections, other clients are refused.
- Every RDS DB instance and every EC2 instance in the Region that has the `FIS-Ready=True` tag, as Prerequisites describes.
- Other work on the load generator, which shares its CPU with the workers.
- Another load test against the same DB instance, from any load generator: it stops at setup while this run holds the lock, and, if this run is stopped, until the lock expires.

## Stop Conditions

The experiment does not have any specific stop conditions defined. Unless you stop it, it ends when `RunLoadTest`'s 25-minute duration has passed, or earlier if an action fails ([how an experiment ends](https://docs.aws.amazon.com/fis/latest/userguide/experiments.html)).

Stop conditions are based on an AWS CloudWatch alarm based on an operational or 
business metric requiring an immediate end of the fault injection. This 
template makes no assumptions about your application and the relevant metrics 
and does not include stop conditions by default.

If you stop the experiment while `RunLoadTest` runs, FIS cancels the load test's command, and SSM Agent ends the document's processes, including the clients of the queries in flight; a query the DB instance is still running finishes there (see What else is affected). In our tests, both before and after the failover, the load command ended within 2 seconds of the stop, and no load test process or credentials file was left on the instance. We counted the load's database sessions every 10 seconds, and the first count after the load command ended found none: 4 seconds after the stop after the failover, and 9 seconds after the stop before it. A stop during the install can leave some of the packages installed and others not, with the rpm database consistent; the next run's install step installs the rest. EC2 Instance Setup says how to find and remove them. A stop during the warm-up also cancels the failover. A stopped run can't release its load test lock, so until the lock expires, `Duration` plus 3 minutes after the run took it, a new run against the DB instance stops at setup with a message that gives the expiry. If no load test runs, you can clear it sooner with `SET autocommit=1; UPDATE fis_loadtest.loadtest_lock SET expires = UTC_TIMESTAMP() - INTERVAL 1 SECOND WHERE id = 1;` (the `SET` makes the change commit even where sessions start with autocommit off). A run that can't release its lock when it ends, for example because it can't reach the DB instance then, leaves the lock to expire, says until when, and fails. A run whose take of the lock fails, and that then can't find and release a lock of its own, says until when the lock may be held, in case the DB instance completed the take anyway, for example after the take timed out or lost its connection. A run that finds at its end that another load test took its lock while it held it (after the lock was cleared or expired), or that the lock's row was removed, fails, since another load may have run at the same time. Clearing the lock alone doesn't make the running test fail: it still releases the lock when it ends. Stopping doesn't stop or undo a failover that FIS has already started. After a failover, the former standby is the primary, in the other Availability Zone, and the experiment doesn't move it back. To move it back, reboot the DB instance with failover again, for example with `aws rds reboot-db-instance --db-instance-identifier <your DB instance> --force-failover`, which makes the connections fail again for a short time.

If the load test fails before the failover, FIS fails `RunLoadTest` and ends the experiment before the failover. That happens when the install fails or a tool is missing, when `DBHost` isn't the endpoint of a DB instance with the `FIS-Ready=True` tag, when the instance can't read the secret, when the user can't create the table or insert into and read it, when the user can't create or take the load test lock, and when another load test holds it. In our tests with a secret that didn't exist, with `DBHost` set to a DB instance without the tag, and with a user that had only CREATE, each experiment failed 33 seconds after it started and the failover was cancelled. With the untagged DB instance, the document read no secret and opened no connection.

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
