# PostgreSQL RDS and Aurora Load Test and Failover Experiment

This repository contains templates and scripts for running AWS Fault Injection Simulator (FIS) experiments on PostgreSQL databases, both for RDS instances and Aurora clusters. These experiments help test database resilience and application behavior during failover scenarios.

## RDS PostgreSQL Experiment

### Setup Steps

1. Deploy the CloudFormation stack for RDS PostgreSQL:
   ```bash
   aws cloudformation deploy \
     --template-file postgres-rds-loadtest.yaml \
     --stack-name postgres-rds-loadtest-v3 \
     --capabilities CAPABILITY_IAM \
     --region us-east-2
   ```

2. Create a CloudWatch Log Group for FIS experiment logging:
   ```bash
   aws logs create-log-group --log-group-name /aws/fis/postgres-rds-loadtest --region us-east-2
   aws logs put-retention-policy --log-group-name /aws/fis/postgres-rds-loadtest --retention-in-days 30 --region us-east-2
   ```

3. Create and run the FIS experiment using the provided script:
   ```bash
   ./create-rds-fis-experiment.sh
   ```

### Experiment Details

The RDS PostgreSQL experiment:
- Runs a load test on the PostgreSQL database
- Generates significant database traffic with 10 concurrent connections
- Executes for 10 minutes
- Uses an EC2 instance to generate the load
- Logs all experiment activities to CloudWatch

## Aurora PostgreSQL Experiment

### Setup Steps

1. Deploy the CloudFormation stack for Aurora PostgreSQL:
   ```bash
   aws cloudformation deploy \
     --template-file postgres-aurora-loadtest.yaml \
     --stack-name postgres-aurora-loadtest-v2 \
     --capabilities CAPABILITY_IAM \
     --region us-east-2
   ```

2. Create an IAM role for FIS experiments with Aurora:
   ```bash
   aws iam create-role --role-name FISExperimentRoleAurora \
     --assume-role-policy-document '{
       "Version": "2012-10-17",
       "Statement": [
         {
           "Effect": "Allow",
           "Principal": {
             "Service": "fis.amazonaws.com"
           },
           "Action": "sts:AssumeRole"
         }
       ]
     }'
   
   aws iam attach-role-policy --role-name FISExperimentRoleAurora \
     --policy-arn arn:aws:iam::aws:policy/service-role/AWSFaultInjectionSimulatorRDSAccess
   ```

3. Create a CloudWatch Log Group for Aurora FIS experiment logging:
   ```bash
   aws logs create-log-group --log-group-name /aws/fis/postgres-aurora-loadtest --region us-east-2
   aws logs put-retention-policy --log-group-name /aws/fis/postgres-aurora-loadtest --retention-in-days 30 --region us-east-2
   ```

4. Create the FIS experiment template file (fis-experiment-aurora.json):
   ```json
   {
     "description": "Aurora PostgreSQL Failover Test",
     "targets": {
       "cluster": {
         "resourceType": "aws:rds:cluster",
         "resourceArns": [],
         "selectionMode": "ALL"
       }
     },
     "actions": {
       "failover": {
         "actionId": "aws:rds:failover-db-cluster",
         "parameters": {},
         "targets": {
           "Clusters": "cluster"
         }
       }
     },
     "stopConditions": [
       {
         "source": "none"
       }
     ],
     "roleArn": "",
     "tags": {
       "Name": "Aurora-PostgreSQL-Failover-Test"
     },
     "logConfiguration": {
       "logSchemaVersion": 2,
       "cloudWatchLogsConfiguration": {
         "logGroupArn": ""
       }
     }
   }
   ```

5. Create and run the Aurora FIS experiment using the provided script:
   ```bash
   ./create-aurora-fis-experiment.sh
   ```

### Experiment Details

The Aurora PostgreSQL experiment:
- Initiates a failover on the Aurora PostgreSQL cluster
- Tests application resilience during database failover
- Logs all experiment activities to CloudWatch

## Monitoring Experiments

You can monitor the experiments with the following commands:

```bash
# For RDS experiment
aws fis get-experiment --id <experiment-id> --region us-east-2
aws logs get-log-events --log-group-name /aws/fis/postgres-rds-loadtest --log-stream-name <experiment-id> --region us-east-2

# For Aurora experiment
aws fis get-experiment --id <experiment-id> --region us-east-2
aws logs get-log-events --log-group-name /aws/fis/postgres-aurora-loadtest --log-stream-name <experiment-id> --region us-east-2
```

## Load Testing Scripts

The repository includes scripts for running load tests on PostgreSQL databases:

```bash
# PostgreSQL load test
pgbench -i -s 50 your_database_name
pgbench -c 10 -j 2 -t 1000 your_database_name

# CPU-intensive query
psql -c "WITH RECURSIVE fibonacci(n, fib_n, next_fib_n) AS (
    SELECT 1, 0::numeric, 1::numeric
    UNION ALL
    SELECT n + 1, next_fib_n, fib_n + next_fib_n
    FROM fibonacci
    WHERE n < 1000000
)
SELECT n, fib_n FROM fibonacci;"
```

## Additional Resources

- [AWS Fault Injection Simulator Documentation](https://docs.aws.amazon.com/fis/latest/userguide/what-is.html)
- [Amazon RDS Documentation](https://docs.aws.amazon.com/rds/index.html)
- [Amazon Aurora Documentation](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_AuroraOverview.html)
