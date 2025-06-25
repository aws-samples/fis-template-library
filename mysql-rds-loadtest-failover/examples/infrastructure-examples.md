# Infrastructure Examples for MySQL RDS Load Test and Failover

This directory contains example infrastructure templates that you can customize to create the necessary resources for running the MySQL RDS Load Test and Failover FIS experiment.

## Overview

The FIS experiment requires:
1. **Multi-AZ MySQL RDS instance** with proper tags for targeting
2. **EC2 instance** for running load tests with proper tags for targeting
3. **SSM Document** for executing the load test script
4. **Proper networking** and security groups for connectivity
5. **IAM roles and policies** for permissions

## Files in this Directory

### `cloudformation-infrastructure.yaml`
A complete CloudFormation template that creates:
- VPC with public and private subnets across multiple AZs
- Multi-AZ MySQL RDS instance with FIS tags
- EC2 instance for load testing with FIS tags
- Security groups and VPC endpoints for SSM connectivity
- IAM roles for EC2 instances

**Key Features:**
- All resources are properly tagged with `FIS-Ready=True`
- Multi-AZ RDS deployment for failover testing
- Private subnet deployment with VPC endpoints for security
- Customizable parameters for different environments

### `mysql-loadtest-ssm-document.json`
An SSM document that:
- Installs MySQL client on the EC2 instance
- Creates database tables for load testing
- Runs configurable concurrent load against the MySQL database
- Monitors CPU utilization and adjusts load accordingly
- Continues running in background during failover testing

**Key Features:**
- Configurable concurrency and target CPU utilization
- Automatic database setup and table creation
- CloudWatch integration for CPU monitoring
- Graceful handling of connection failures during failover

## Customization Guide

### 1. Tagging Strategy
The example uses this tag for FIS targeting:
```yaml
# For both RDS instances and EC2 instances
FIS-Ready: "True"
```

**Customize for your environment:**
- Ensure the `FIS-Ready=True` tag is applied to all resources you want to target
- Add additional tags for organizational purposes (but FIS targeting uses only FIS-Ready)
- Ensure tags match those specified in your FIS experiment template

### 2. Database Configuration
**Parameters to customize:**
- `DBName`: Database name (default: testdb)
- `DBUsername`: Admin username (default: admin)
- `DBPassword`: Admin password (required, secure input)
- Instance class and storage based on your load testing needs

### 3. Load Testing Configuration
**SSM Document parameters:**
- `Concurrency`: Number of concurrent connections (default: 25)
- `TargetCPU`: Target CPU utilization percentage (default: 80)
- `Duration`: Maximum test duration in seconds (default: 600)

### 4. Network Configuration
**VPC and Subnet customization:**
- Modify CIDR blocks to fit your network architecture
- Adjust availability zones based on your region
- Configure additional security group rules as needed

### `deploy-infrastructure.sh`
An example deployment script showing how you might automate the infrastructure deployment:
- Shows parameter handling and secure password input
- Demonstrates CloudFormation deployment with proper tags
- Includes post-deployment steps for SSM document creation
- **Note: This is a reference example only - copy and customize for your needs**

## Deployment Instructions

### Option 1: CloudFormation Console
1. Navigate to AWS CloudFormation console
2. Create new stack using `cloudformation-infrastructure.yaml`
3. Provide required parameters (especially DBPassword)
4. Deploy and wait for completion

### Option 2: AWS CLI
```bash
aws cloudformation create-stack \
  --stack-name mysql-loadtest-infrastructure \
  --template-body file://cloudformation-infrastructure.yaml \
  --parameters ParameterKey=DBPassword,ParameterValue=YourSecurePassword123 \
  --capabilities CAPABILITY_IAM \
  --region us-east-1
```

### Option 3: Deploy SSM Document Separately
```bash
aws ssm create-document \
  --name "MySQL-LoadTest-Document" \
  --document-type "Command" \
  --content file://mysql-loadtest-ssm-document.json \
  --region us-east-1
```

## Integration with FIS Experiment

After deploying the infrastructure:

1. **Update FIS Template**: Ensure your FIS experiment template references:
   - Correct SSM document ARN: `arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:document/MySQL-LoadTest-Document`
   - Proper resource tags that match your deployed infrastructure

2. **Verify Connectivity**: Test that your EC2 instance can connect to the RDS instance:
   ```bash
   mysql -h <rds-endpoint> -u admin -p<password> -e "SELECT VERSION();"
   ```

3. **Test Load Script**: Run the SSM document manually to verify load generation works:
   ```bash
   aws ssm send-command \
     --document-name "MySQL-LoadTest-Document" \
     --targets "Key=tag:FIS-Application,Values=MySQL-LoadTest" \
     --parameters DBHost=<rds-endpoint>,DBPassword=<password>
   ```

## Security Considerations

- **Database Password**: Use AWS Secrets Manager or Parameter Store for production
- **Network Security**: Deploy in private subnets with VPC endpoints
- **IAM Permissions**: Follow principle of least privilege
- **Encryption**: Enable encryption at rest and in transit for production workloads

## Cost Optimization

- **Instance Sizing**: Start with smaller instances (t3.small) for testing
- **Storage**: Use gp2 storage for cost-effective testing
- **Cleanup**: Remember to delete resources after testing to avoid ongoing charges

## Troubleshooting

### Common Issues:
1. **SSM Connectivity**: Ensure VPC endpoints are configured for private subnets
2. **Database Connectivity**: Verify security group rules allow MySQL traffic (port 3306)
3. **Load Test Failures**: Check CloudWatch logs for SSM command execution details
4. **FIS Targeting**: Verify resource tags exactly match FIS experiment template

### Useful Commands:
```bash
# Check SSM agent status
aws ssm describe-instance-information

# View SSM command execution
aws ssm get-command-invocation --command-id <command-id> --instance-id <instance-id>

# Monitor RDS CPU utilization
aws cloudwatch get-metric-statistics \
  --namespace AWS/RDS \
  --metric-name CPUUtilization \
  --dimensions Name=DBInstanceIdentifier,Value=<db-instance-id> \
  --start-time 2023-01-01T00:00:00Z \
  --end-time 2023-01-01T01:00:00Z \
  --period 300 \
  --statistics Average
```

## Next Steps

1. **Customize the templates** for your specific environment and requirements
2. **Deploy the infrastructure** using your preferred method
3. **Test the load generation** to ensure it works with your setup
4. **Run the FIS experiment** to validate your database failover capabilities
5. **Monitor and analyze** the results to improve your resilience posture
