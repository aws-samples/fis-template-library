# PostgreSQL RDS and Aurora Load Test and Failover Experiment

This repository contains templates and scripts for running AWS Fault Injection Simulator (FIS) experiments on PostgreSQL databases, both for RDS instances and Aurora clusters. These experiments help test database resilience and application behavior during failover scenarios.

## RDS PostgreSQL Experiment

### Setup Steps

1. Deploy the CloudFormation stack for RDS PostgreSQL:
   ```bash
   aws cloudformation deploy \
     --template-file cloudformation.yaml \
     --stack-name postgres-rds-loadtest \
     --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
     --region us-east-2 \
     --parameter-overrides DBUsername=postgres DBPassword=Password123!
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
     --template-file cloudformation-aurora.yaml \
     --stack-name postgres-rds-loadtest \
     --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
     --region us-east-2 \
     --parameter-overrides DBUsername=postgres DBPassword=Password123!
   ```

2. The IAM role for FIS experiments with Aurora is automatically created by the CloudFormation template with the name `FISExperimentRoleAurora`.

### Aurora Failover-Only Experiment

3. Run the Aurora failover-only experiment:
   ```bash
   # Run the experiment with default stack name
   ./create-aurora-fis-experiment.sh
   
   # Or specify a custom stack name and region
   ./create-aurora-fis-experiment.sh my-stack-name us-west-2
   ```

### Aurora Load Test with Concurrent Failover Experiment

3. For a more realistic test that includes a failover during the load test:
   ```bash
   # Run the experiment with default stack name
   ./create-aurora-fis-concurrent-experiment.sh
   
   # Or specify a custom stack name and region
   ./create-aurora-fis-concurrent-experiment.sh my-stack-name us-west-2
   
   # Alternative: Use the simplified script that creates the log group first
   ./run-experiment.sh
   ```

### Experiment Details

The Aurora PostgreSQL experiments come in two variants:

1. **Failover-Only Experiment**:
   - Initiates a failover on the Aurora PostgreSQL cluster
   - Tests application resilience during database failover
   - Logs all experiment activities to CloudWatch

2. **Load Test with Concurrent Failover Experiment**:
   - Runs a load test on the Aurora PostgreSQL database for 10 minutes
   - Generates significant database traffic with 10 concurrent connections
   - Initiates a failover 5 minutes into the load test (halfway through)
   - Tests application resilience during database failover under load
   - Logs all experiment activities to CloudWatch

## Monitoring Experiments

You can monitor the experiments with the following commands:

```bash
# For RDS experiment
aws fis get-experiment --id <experiment-id> --region <region>
aws logs get-log-events --log-group-name /aws/fis/postgres-rds-loadtest --log-stream-name <experiment-id> --region <region>

# For Aurora experiment (replace with your actual log group name)
aws fis get-experiment --id <experiment-id> --region <region>
aws logs get-log-events --log-group-name /aws/fis/postgres-aurora-loadtest-<random-string> --log-stream-name <experiment-id> --region <region>
```

The experiment scripts will output the exact commands to use for monitoring.

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

## File Structure

- `cloudformation.yaml` - CloudFormation template for RDS PostgreSQL setup
- `cloudformation-aurora.yaml` - CloudFormation template for Aurora PostgreSQL setup with fixed SSM document
- `fis-experiment.json` - FIS experiment template for RDS load test
- `fis-experiment-aurora.json` - FIS experiment template for Aurora failover
- `fis-experiment-aurora-loadtest.json` - FIS experiment template for Aurora load test and failover
- `fis-experiment-aurora-loadtest-concurrent.json` - FIS experiment template for Aurora load test with concurrent failover
- `create-rds-fis-experiment.sh` - Script to create and run RDS experiment
- `create-aurora-fis-experiment.sh` - Script to create and run Aurora failover experiment
- `create-aurora-fis-loadtest-experiment.sh` - Script to create and run Aurora load test and failover experiment
- `create-aurora-fis-concurrent-experiment.sh` - Script to create and run Aurora load test with concurrent failover
- `run-experiment.sh` - Simplified script that creates the log group first and runs the Aurora load test with concurrent failover
- `cleanup.sh` - Script to clean up all resources created by the experiments
- `ssm-loadtest-shell-script.yaml` - SSM document template for load testing

## Troubleshooting

### Common Issues

1. **Connection Timeout**: If you encounter connection timeouts between the EC2 instance and the Aurora cluster:
   - Ensure the Aurora security group allows traffic from the EC2 security group
   - Add a rule to allow PostgreSQL traffic (port 5432) from the entire VPC CIDR range
   - Verify the Aurora cluster is using the correct port (5432 for PostgreSQL)

2. **SQL Syntax Errors**: If you see SQL syntax errors in the load test:
   - Check the `execute_sql_return` function to ensure it properly trims whitespace from results
   - Verify the user ID retrieval in the insert operations function
   - Add error handling for transaction inserts

3. **SSM Document Issues**: If the SSM document fails to execute:
   - Update the SSM document to use direct PostgreSQL installation instead of amazon-linux-extras
   - Ensure the SSM document has the correct permissions

## Cleanup

After you've completed your experiments, you can clean up all the resources to avoid unnecessary AWS charges:

```bash
# Run the cleanup script with default stack name
./cleanup.sh

# Or specify a custom stack name and region
./cleanup.sh my-stack-name us-west-2
```

The cleanup script will:
1. Delete all FIS experiment templates related to PostgreSQL experiments
2. Delete all CloudWatch Log Groups with the prefix "/aws/fis/postgres"
3. Delete the CloudFormation stack and all its resources

Note: If you have any running FIS experiments, you may need to stop them manually:
```bash
aws fis stop-experiment --id <experiment-id> --region <region>
```

## Additional Resources

- [AWS Fault Injection Simulator Documentation](https://docs.aws.amazon.com/fis/latest/userguide/what-is.html)
- [Amazon RDS Documentation](https://docs.aws.amazon.com/rds/index.html)
- [Amazon Aurora Documentation](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_AuroraOverview.html)
