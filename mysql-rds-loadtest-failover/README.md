# MySQL RDS Load Test and Failover

This template creates an environment for testing MySQL RDS failover under load. It includes:

1. A VPC with public and private subnets
2. A MySQL RDS instance
3. An EC2 instance with MySQL client for load testing
4. An AWS FIS experiment template for simulating failover

## Architecture

- **VPC**: Custom VPC with public and private subnets across two availability zones
- **RDS**: MySQL 8.0 database in a private subnet
- **EC2**: Amazon Linux 2 instance in a private subnet with SSM access
- **FIS**: Fault injection experiment that runs a load test and then forces an RDS failover

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

## Monitoring

Monitor the experiment in the AWS FIS console or through CloudWatch Logs at `/aws/fis/experiment`.

## Cleanup

Delete the CloudFormation stack:

```bash
aws cloudformation delete-stack --stack-name mysql-rds-loadtest-failover
```
