# Aurora Cluster Failover Infrastructure Examples

This directory contains example infrastructure templates and deployment scripts to help you set up the necessary resources for the Aurora Cluster CPU Overload and Failover experiment.

## Files

- `cloudformation-infrastructure.yaml`: CloudFormation template that creates a VPC, EC2 instance, and Aurora PostgreSQL cluster
- `deploy-infrastructure.sh`: Example deployment script for the CloudFormation template

## CloudFormation Template Overview

The `cloudformation-infrastructure.yaml` template creates:

1. **VPC Infrastructure**:
   - VPC with public and private subnets across two Availability Zones
   - Internet Gateway and NAT Gateway for connectivity
   - Route tables and security groups

2. **Aurora PostgreSQL Cluster**:
   - Multi-AZ Aurora PostgreSQL cluster with writer and reader instances
   - Configured with the `FIS-Ready=True` tag for experiment targeting
   - Database subnet group for proper network isolation

3. **EC2 Instance**:
   - Amazon Linux 2 instance with SSM agent
   - Tagged with `FIS-Ready=True` for experiment targeting
   - Configured to connect to the Aurora cluster

## Prerequisites

Before deploying the infrastructure:

1. Ensure you have appropriate AWS CLI credentials configured
2. Have the necessary IAM permissions to create VPC, EC2, and RDS resources
3. Choose a unique stack name and database password

## Deployment

### Using the deployment script:

```bash
chmod +x deploy-infrastructure.sh
./deploy-infrastructure.sh
```

### Manual deployment:

```bash
aws cloudformation create-stack \
  --stack-name aurora-fis-experiment \
  --template-body file://cloudformation-infrastructure.yaml \
  --parameters ParameterKey=DBUsername,ParameterValue=postgres \
               ParameterKey=DBPassword,ParameterValue=YourSecurePassword123 \
  --capabilities CAPABILITY_IAM
```

## Important Notes

1. **Tagging**: The template automatically applies the `FIS-Ready=True` tag to resources that will be targeted by the FIS experiment.

2. **Security**: The template creates security groups that allow:
   - EC2 instance to connect to Aurora cluster on port 5432
   - SSM access for the EC2 instance
   - Outbound internet access for package installation

3. **Costs**: Running this infrastructure will incur AWS charges. Remember to clean up resources when not needed.

4. **Customization**: You may need to modify the template based on your specific requirements:
   - Instance types and sizes
   - Database configuration
   - Network CIDR blocks
   - Security group rules

## Cleanup

To avoid ongoing charges, delete the CloudFormation stack when you're done:

```bash
aws cloudformation delete-stack --stack-name aurora-fis-experiment
```

## SSM Document Deployment

After deploying the infrastructure, you'll need to create the SSM document for the load test:

```bash
aws ssm create-document \
  --name "aurora-cluster-loadtest-document" \
  --document-type "Command" \
  --content file://../aurora-cluster-failover-ssm-template.json
```

## Monitoring Setup

Consider setting up CloudWatch monitoring:

1. Create CloudWatch alarms for Aurora cluster metrics (CPU, connections, etc.)
2. Set up a CloudWatch dashboard to visualize experiment effects
3. Configure SNS notifications for critical alerts

## Troubleshooting

Common issues and solutions:

1. **Connection Issues**: Ensure security groups allow traffic between EC2 and Aurora
2. **SSM Access**: Verify the EC2 instance has the SSM agent installed and proper IAM role
3. **Database Access**: Check that the database is accessible and credentials are correct
