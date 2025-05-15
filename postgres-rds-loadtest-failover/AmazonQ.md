# PostgreSQL RDS and Aurora Load Test and Failover Experiment Deployment

## Deployment Summary

I've successfully deployed the Aurora PostgreSQL load test with concurrent failover experiment in your AWS account in the us-east-2 region. Here's a summary of what was accomplished:

### 1. CloudFormation Stack Deployment
- Successfully deployed the CloudFormation stack `postgres-test-v7` using the `cloudformation-aurora.yaml` template
- The stack created:
  - Aurora PostgreSQL cluster with primary and replica instances
  - EC2 instance for load testing
  - Required IAM roles and security groups
  - SSM document for running the load test

### 2. FIS Experiment Creation and Execution
- Created a new FIS experiment template for concurrent load testing and failover
- Created a CloudWatch Log Group for experiment logging: `/aws/fis/postgres-aurora-loadtest-6b88b0da`
- Started the FIS experiment with ID: `EXP4rStgSNW7f1xVG`

### 3. Experiment Details
The experiment is currently running with the following actions:
- **RunLoadTest**: Executing a load test on the PostgreSQL database with 10 concurrent connections for 10 minutes
- **DelayAction**: Waiting for 5 minutes before initiating the failover
- **failover**: Will initiate a failover on the Aurora PostgreSQL cluster after the delay

## Monitoring the Experiment

You can monitor the experiment with the following commands:

```bash
# Check experiment status
aws fis get-experiment --id EXP4rStgSNW7f1xVG --region us-east-2

# Check experiment logs
aws logs get-log-events --log-group-name /aws/fis/postgres-aurora-loadtest-6b88b0da --log-stream-name EXP4rStgSNW7f1xVG --region us-east-2
```

## Aurora Cluster Information

- **Cluster Endpoint**: postgres-test-v7-auroracluster-yib1fwswpgjw.cluster-cq4gaxax0zru.us-east-2.rds.amazonaws.com
- **Reader Endpoint**: postgres-test-v7-auroracluster-yib1fwswpgjw.cluster-ro-cq4gaxax0zru.us-east-2.rds.amazonaws.com
- **Port**: 5432
- **Database Name**: mydb
- **Master Username**: postgres

## Experiment Workflow

1. The load test is currently running on the EC2 instance, generating significant database traffic with 10 concurrent connections
2. After 5 minutes, the failover action will be triggered
3. The Aurora cluster will perform a failover, promoting the replica to primary
4. The load test will continue running for the remaining 5 minutes
5. The experiment will complete after a total of 10 minutes

This experiment tests the application's resilience during database failover under load, which is a critical aspect of ensuring high availability for your database applications.
