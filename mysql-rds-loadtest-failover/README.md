# MySQL RDS Load Test and Failover

This template creates an environment for testing MySQL RDS failover under load. It includes:

1. A VPC with public and private subnets
2. A Multi-AZ MySQL RDS instance
3. An EC2 instance with MySQL client for load testing
4. An AWS FIS experiment template for simulating failover

## Architecture

- **VPC**: Custom VPC with public and private subnets across two availability zones
- **RDS**: Multi-AZ MySQL 8.0 database in private subnets across two availability zones
- **EC2**: Amazon Linux 2 instance in a private subnet with SSM access
- **FIS**: Fault injection experiment that runs a load test and then forces an RDS failover

## Performance Characteristics

Based on extensive testing, this template demonstrates the following performance characteristics:

- **Failover Time**: ~25 seconds under high CPU load (97-98% utilization)
- **CPU Utilization**:
  - 10 concurrent connections: ~37-40% CPU utilization
  - 25 concurrent connections: ~95-98% CPU utilization (recommended for stress testing)
- **Database Availability**: Applications experience ~25 seconds of downtime during failover
- **DNS Continuity**: The endpoint DNS name remains the same during failover, providing connection continuity

## Deployment

Deploy the CloudFormation template:

```bash
aws cloudformation deploy \
  --template-file cloudformation.yaml \
  --stack-name mysql-rds-loadtest-failover \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides DBPassword=YourSecurePassword
```

## Running the Experiment

After deployment, you can run the FIS experiment:

1. Get the experiment template ID:
```bash
aws fis list-experiment-templates
```

2. Start the experiment:
```bash
aws fis start-experiment --experiment-template-id YOUR_TEMPLATE_ID
```

## How the Experiment Works

The experiment follows this workflow:

1. **Load Generation Phase**:
   - The SSM document runs a high CPU load test on the RDS instance
   - Multiple worker processes create concurrent connections (default: 25)
   - The script monitors CPU utilization until it reaches the target (default: 80%)
   - Once target CPU is reached (or timeout occurs), the script continues running in the background
   - The SSM document completes successfully, allowing FIS to proceed to the next action

2. **Failover Phase**:
   - FIS triggers a forced failover of the RDS instance
   - The standby instance becomes the new primary
   - The database endpoint DNS name remains the same
   - Applications experience ~25 seconds of downtime during the transition
   - The load test continues running during and after the failover

3. **Post-Failover Phase**:
   - The load test continues running for 5 minutes after the failover completes
   - This allows observation of how the new primary instance handles the load
   - After 5 minutes, FIS automatically stops the load test

4. **Monitoring**:
   - CloudWatch logs capture the entire experiment
   - RDS events record the failover timeline
   - CPU utilization metrics show the impact of failover

## Monitoring

Monitor the experiment using these methods:

1. **AWS FIS Console**: View experiment progress and status
2. **CloudWatch Logs**: Check detailed logs at `/aws/fis/experiment`
3. **RDS Console**: Monitor CPU utilization, connections, and failover events
4. **CloudWatch Metrics**: Track RDS metrics during the experiment:

```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/RDS \
  --metric-name CPUUtilization \
  --dimensions Name=DBInstanceIdentifier,Value=YOUR_RDS_INSTANCE_ID \
  --start-time $(date -u -d '5 minutes ago' '+%Y-%m-%dT%H:%M:%SZ') \
  --end-time $(date -u '+%Y-%m-%dT%H:%M:%SZ') \
  --period 60 \
  --statistics Average
```

5. **RDS Events**: Check for failover events:

```bash
aws rds describe-events \
  --source-identifier YOUR_RDS_INSTANCE_ID \
  --source-type db-instance \
  --start-time $(date -u -d '1 hour ago' '+%Y-%m-%dT%H:%M:%SZ')
```

## Manual Testing

You can also run manual tests:

1. **Start a high CPU load test**:
```bash
aws ssm send-command \
  --instance-ids YOUR_EC2_INSTANCE_ID \
  --document-name YOUR_SSM_DOCUMENT_NAME \
  --parameters "DBHost=YOUR_RDS_ENDPOINT,DBUsername=admin,DBPassword=YOUR_PASSWORD,DBName=testdb,Concurrency=25,Duration=600,TargetCPU=80,DBInstanceId=YOUR_RDS_INSTANCE_ID"
```

2. **Manually trigger a failover**:
```bash
aws rds reboot-db-instance \
  --db-instance-identifier YOUR_RDS_INSTANCE_ID \
  --force-failover
```

## Key Findings

- Multi-AZ failover completes in approximately 25 seconds under high CPU load
- The database endpoint DNS name remains the same during failover
- After failover, the database returns to normal operation with no read-only mode
- The t3.small instance can handle high load testing but reaches CPU saturation at 25 concurrent connections

## Cleanup

Delete the CloudFormation stack:

```bash
aws cloudformation delete-stack --stack-name mysql-rds-loadtest-failover
```

## References

- [RDS Multi-AZ Documentation](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.MultiAZ.html)
- [AWS FIS Documentation](https://docs.aws.amazon.com/fis/latest/userguide/what-is.html)
- [MySQL Performance Best Practices](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_BestPractices.MySQL.html)
