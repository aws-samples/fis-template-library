# AWS Fault Injection Service Experiment: Aurora PostgreSQL Cluster Load Test and Failover

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Description

This experiment runs a database load test against an Aurora PostgreSQL cluster from an EC2 instance, and fails over the cluster 5 minutes after the load test starts, while the load is still running. It tests how your database and application behave when the writer changes under load. The load test does not saturate the database: in our tests with db.t4g.medium instances, it raised the writer's CPU utilization from about 10% to about 72%.

## Hypothesis

When high CPU load occurs on an Aurora cluster followed by a subsequent failover, the system will restore normal operation with minimal disruption, and the application's functionality will remain largely unaffected. The automatic recovery process will complete within minutes, and the system's request processing capability will maintain continuity at near 100% efficiency after the failover completes.

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment and to create the resources listed below.
2. The IAM role specified in the `roleArn` field has the permissions in `aurora-postgres-cluster-loadtest-failover-iam-policy.json` and the trust policy in `fis-iam-trust-relationship.json`. Replace `<YOUR ROLE NAME>` in the template with the role's name.
3. The Aurora PostgreSQL cluster you want to target has the `FIS-Ready=True` tag and at least one reader instance, so that it can fail over.
4. The EC2 instance that generates the load has the `FIS-Ready=True` tag and meets the requirements in [EC2 Instance Setup](#ec2-instance-setup).
5. Both targets use `selectionMode` `ALL`. Every cluster of resource type `aws:rds:cluster` that has the tag in the Region fails over, and every EC2 instance that has the tag runs the load test.
6. In the same Region, you have created:
   - the SSM document `aurora-cluster-loadtest-document` from `aurora-postgres-cluster-loadtest-failover-ssm-template.json`. The template refers to the document by this name.
   - a Parameter Store `String` parameter `/aurora-cluster/endpoint` whose value is the cluster endpoint. The document reads the database host from it.
   - a Secrets Manager secret `aurora-cluster-password` whose secret string is JSON with a `password` key that holds the database user's password. The document reads the password from it at run time.
   - the database user `postgres` and the database `mydb` on the cluster. The user must be able to create tables in `mydb`.
   - the CloudWatch Logs log group `FISExperimentLogs`. The template sends the experiment log there.

   To use another host, port, database or user, set `DBHost`, `DBPort`, `DBName` or `DBUser` in the template's `documentParameters`, or change the document's defaults.

## Architecture Overview

This experiment uses the following components:

- **Aurora PostgreSQL Cluster**: The target database that receives the load and fails over
- **EC2 Load Generator Instance**: Runs the SSM document that generates the database load
- **SSM Document**: Installs the PostgreSQL client and runs the load test queries
- **FIS Experiment**: Starts the load test and, 5 minutes later, the failover

**Critical**: The EC2 instance acts as the load generator and must be able to connect to your Aurora cluster. The SSM document runs on this instance, not on the Aurora cluster.

## EC2 Instance Setup

Your EC2 instance must meet these requirements:

1. **Network Access**: The instance's security group allows outbound connections to the cluster on port 5432, and the cluster's security group allows inbound connections from the instance on port 5432. The instance also needs outbound HTTPS to Systems Manager, Secrets Manager and the operating system's package repositories.
2. **PostgreSQL Client**: The SSM document's first step installs the client with `yum` or `apt-get` on Amazon Linux, CentOS, RHEL, Ubuntu and Debian, and fails on other operating systems. Our tests used Amazon Linux 2023.
3. **SSM Agent**: Ensure SSM Agent is installed and the instance appears in Systems Manager
4. **IAM Role**: Attach an instance profile whose role has the `AmazonSSMManagedInstanceCore` policy and `secretsmanager:GetSecretValue` on the secret `aurora-cluster-password`
5. **Tagging**: Tag the instance with `FIS-Ready=True`

Test connectivity before running the experiment:
```bash
psql -h your-aurora-endpoint -U your-username -d your-database -c "SELECT 1;"
```

## ⚠️ Database Impact Warning

**IMPORTANT**: This experiment will create test tables in your Aurora PostgreSQL database:

### Tables Created:
- `load_test_users` - User records with status and timestamps
- `load_test_transactions` - Transaction records with foreign key relationships

### Impact:
- Tables will persist after the experiment completes
- No rows are inserted: the tables stay empty, and the document's `NumRecords` parameter is not used
- No existing data will be modified or deleted
- Tables use `IF NOT EXISTS` clauses to avoid conflicts
- Indexes will be created for performance testing

### Cleanup:
If you need to remove the test tables after the experiment, you can manually drop them:
```sql
DROP TABLE IF EXISTS load_test_transactions;
DROP TABLE IF EXISTS load_test_users;
```

## How it works

This experiment runs a database load test and fails over the Aurora DB cluster while the load runs:

1. **Load generation**: `RunLoadTest` starts with the experiment. It runs the SSM document on the load generator with `Duration` 600 and `Concurrency` 10. The document installs the PostgreSQL client, connects to the database, creates the tables if they don't exist, and starts 10 loops. Each loop opens a new connection, runs a query that joins the two tables, and waits 0.1 seconds. After 600 seconds the document stops the loops.
2. **Baseline**: `DelayAction` waits 5 minutes.
3. **Failover**: `FailoverCluster` then calls `FailoverDBCluster`, which promotes a reader instance to writer while the load test is still running.
4. **After the failover**: the load test keeps running against the cluster endpoint, which now points to the new writer, until its 600 seconds are up. The document doesn't record any results, because it discards the queries' output and errors. Watch your own metrics, such as the cluster's CloudWatch metrics and your application's error rate.

Measured in our tests, with db.t4g.medium instances, in the two runs that ran to completion:
- The load ran at about 220 transactions per second, and the writer's CPU utilization rose from about 10% to about 72%.
- FIS called `FailoverDBCluster` 301-302 seconds after the load started. RDS reported the failover complete 15-20 seconds later, and the cluster had one writer and one available reader again 26-27 seconds after that.
- Our test clients saw 1-7 seconds of failed requests, and no acknowledged write was lost.
- The load ended with the document's 600 seconds, 3 seconds after FIS marked the `RunLoadTest` action completed.

The experiment targets resources with the `FIS-Ready=True` tag for safety and control.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until the load test finishes, 10 minutes after the experiment starts. If you stop the experiment while the load test runs, FIS cancels the load test's command and the load stops: in our tests it stopped within 2 seconds of the stop, and no load test process was left on the instance. Stopping doesn't undo a failover that has already run.

Stop conditions are based on an AWS CloudWatch alarm based on an operational or 
business metric requiring an immediate end of the fault injection. This 
template makes no assumptions about your application and the relevant metrics 
and does not include stop conditions by default.

## Files included

- `aurora-postgres-cluster-loadtest-failover-template.json`: Main FIS experiment template
- `aurora-postgres-cluster-loadtest-failover-iam-policy.json`: Required IAM permissions
- `aurora-postgres-cluster-loadtest-failover-ssm-template.json`: SSM document for load testing
- `fis-iam-trust-relationship.json`: IAM trust policy for FIS service

## Next Steps
As you adapt this scenario to your needs, we recommend:
1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to the database operations your application runs on the targeted cluster.
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of the load and the failover.
4. Adding a stop condition tied to the alarm to automatically halt the experiment if critical thresholds are breached.
5. Testing the experiment in a non-production environment first, and checking how your application's connection handling copes with the writer change.

## Import Experiment
You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
