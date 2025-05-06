#!/bin/bash

# Get the AWS region
AWS_REGION=${AWS_REGION:-us-east-2}
echo "Using AWS Region: $AWS_REGION"

# Get the stack name from command line or use default
STACK_NAME=${1:-postgres-rds-loadtest-v3}
echo "Using CloudFormation stack: $STACK_NAME"

# Create a CloudWatch log group for FIS experiment logs
LOG_GROUP_NAME="/aws/fis/postgres-rds-loadtest"
echo "Creating CloudWatch log group: $LOG_GROUP_NAME"

# Check if log group already exists
LOG_GROUP_EXISTS=$(aws logs describe-log-groups --log-group-name-prefix $LOG_GROUP_NAME --region $AWS_REGION --query "logGroups[?logGroupName=='$LOG_GROUP_NAME'].logGroupName" --output text)

if [ -z "$LOG_GROUP_EXISTS" ]; then
  echo "Creating new log group..."
  aws logs create-log-group --log-group-name $LOG_GROUP_NAME --region $AWS_REGION
  # Set retention policy to 30 days to manage costs
  aws logs put-retention-policy --log-group-name $LOG_GROUP_NAME --retention-in-days 30 --region $AWS_REGION
  echo "Log group created with 30-day retention policy"
else
  echo "Log group already exists, using existing log group"
fi

# Get the log group ARN
LOG_GROUP_ARN=$(aws logs describe-log-groups --log-group-name-prefix $LOG_GROUP_NAME --region $AWS_REGION --query "logGroups[?logGroupName=='$LOG_GROUP_NAME'].arn" --output text)
echo "Log Group ARN: $LOG_GROUP_ARN"

# Get the EC2 instance ID from CloudFormation outputs
EC2_INSTANCE_ID=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --region $AWS_REGION --query "Stacks[0].Outputs[?OutputKey=='EC2InstanceId'].OutputValue" --output text)
if [ -z "$EC2_INSTANCE_ID" ]; then
  echo "Error: Could not find EC2 instance ID in stack outputs"
  exit 1
fi
echo "Found EC2 Instance ID: $EC2_INSTANCE_ID"

# Get the SSM document name from CloudFormation outputs
SSM_DOCUMENT_NAME=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --region $AWS_REGION --query "Stacks[0].Outputs[?OutputKey=='SSMDocumentName'].OutputValue" --output text)
if [ -z "$SSM_DOCUMENT_NAME" ]; then
  echo "Error: Could not find SSM document name in stack outputs"
  exit 1
fi
echo "Found SSM Document Name: $SSM_DOCUMENT_NAME"

# Get the AWS account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
if [ -z "$AWS_ACCOUNT_ID" ]; then
  echo "Error: Could not determine AWS account ID"
  exit 1
fi
echo "Using AWS Account ID: $AWS_ACCOUNT_ID"

# Construct the ARNs
EC2_INSTANCE_ARN="arn:aws:ec2:$AWS_REGION:$AWS_ACCOUNT_ID:instance/$EC2_INSTANCE_ID"
SSM_DOCUMENT_ARN="arn:aws:ssm:$AWS_REGION:$AWS_ACCOUNT_ID:document/$SSM_DOCUMENT_NAME"
FIS_ROLE_ARN="arn:aws:iam::$AWS_ACCOUNT_ID:role/FISExperimentRole"

echo "EC2 Instance ARN: $EC2_INSTANCE_ARN"
echo "SSM Document ARN: $SSM_DOCUMENT_ARN"
echo "FIS Role ARN: $FIS_ROLE_ARN"

# Update the FIS role to allow CloudWatch Logs permissions
echo "Updating FIS role with CloudWatch Logs permissions..."

# Create a policy document for CloudWatch Logs permissions
POLICY_DOCUMENT='{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogStreams"
      ],
      "Resource": ["'$LOG_GROUP_ARN'", "'$LOG_GROUP_ARN':*"]
    }
  ]
}'

# Create a temporary file for the policy document
POLICY_FILE=$(mktemp)
echo $POLICY_DOCUMENT > $POLICY_FILE

# Create or update the inline policy
aws iam put-role-policy \
  --role-name FISExperimentRole \
  --policy-name FISCloudWatchLogsPolicy \
  --policy-document file://$POLICY_FILE \
  --region $AWS_REGION

echo "FIS role updated with CloudWatch Logs permissions"

# Create a temporary file with the FIS experiment template with logging
TMP_FILE=$(mktemp)
cat > $TMP_FILE << EOF
{
  "description": "PostgreSQL RDS Load Test and Failover Experiment",
  "targets": {
    "EC2Instance": {
      "resourceType": "aws:ec2:instance",
      "resourceArns": [
        "$EC2_INSTANCE_ARN"
      ],
      "selectionMode": "ALL"
    }
  },
  "actions": {
    "RunLoadTest": {
      "actionId": "aws:ssm:send-command",
      "parameters": {
        "documentArn": "$SSM_DOCUMENT_ARN",
        "documentParameters": "{\"Duration\":\"300\",\"Concurrency\":\"10\"}",
        "duration": "PT10M"
      },
      "targets": {
        "Instances": "EC2Instance"
      }
    }
  },
  "stopConditions": [
    {
      "source": "none"
    }
  ],
  "roleArn": "$FIS_ROLE_ARN",
  "tags": {
    "Name": "PostgreSQL-RDS-LoadTest-Failover"
  },
  "logConfiguration": {
    "logSchemaVersion": 1,
    "cloudWatchLogsConfiguration": {
      "logGroupArn": "$LOG_GROUP_ARN"
    }
  }
}
EOF

echo "Creating FIS experiment template..."
EXPERIMENT_TEMPLATE_ID=$(aws fis create-experiment-template --cli-input-json file://$TMP_FILE --region $AWS_REGION --query 'experimentTemplate.id' --output text)

if [ -z "$EXPERIMENT_TEMPLATE_ID" ]; then
  echo "Error: Failed to create FIS experiment template"
  cat $TMP_FILE
  exit 1
fi

echo "FIS experiment template created successfully with ID: $EXPERIMENT_TEMPLATE_ID"

# Clean up temporary files
rm $TMP_FILE
rm $POLICY_FILE

echo "To start the experiment, run:"
echo "aws fis start-experiment --experiment-template-id $EXPERIMENT_TEMPLATE_ID --region $AWS_REGION"
echo ""
echo "To view experiment logs, visit the CloudWatch console or run:"
echo "aws logs get-log-events --log-group-name $LOG_GROUP_NAME --log-stream-name <experiment-id> --region $AWS_REGION"
