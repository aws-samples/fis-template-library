#!/bin/bash
# Script to create FIS experiment template using CloudFormation stack outputs

# Configuration
STACK_NAME="$1"
REGION="$2"
PASSWORD="$3"

# Default values if not provided
if [ -z "$STACK_NAME" ]; then
  STACK_NAME="mysql-rds-loadtest-failover-v2"
  echo "Using default stack name: $STACK_NAME"
fi

if [ -z "$REGION" ]; then
  REGION="us-east-2"
  echo "Using default region: $REGION"
fi

if [ -z "$PASSWORD" ]; then
  echo "Error: DB password is required"
  echo "Usage: $0 [stack-name] [region] <db-password>"
  exit 1
fi

echo "Retrieving CloudFormation stack outputs..."

# Get stack outputs
STACK_OUTPUTS=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --region $REGION --query "Stacks[0].Outputs" --output json)

if [ $? -ne 0 ]; then
  echo "Error: Failed to retrieve stack outputs"
  exit 1
fi

# Extract values from stack outputs
EC2_INSTANCE_ID=$(echo $STACK_OUTPUTS | jq -r '.[] | select(.OutputKey=="EC2InstanceId") | .OutputValue')
RDS_ENDPOINT=$(echo $STACK_OUTPUTS | jq -r '.[] | select(.OutputKey=="RDSEndpoint") | .OutputValue')
SSM_DOCUMENT_NAME=$(echo $STACK_OUTPUTS | jq -r '.[] | select(.OutputKey=="SSMDocumentName") | .OutputValue')

# Extract RDS instance ID from endpoint
RDS_INSTANCE_ID=$(echo $RDS_ENDPOINT | cut -d'.' -f1)

# Get account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query "Account" --output text --region $REGION)

# Get EC2 instance ARN
EC2_INSTANCE_ARN="arn:aws:ec2:$REGION:$ACCOUNT_ID:instance/$EC2_INSTANCE_ID"

# Get RDS instance ARN
RDS_INSTANCE_ARN="arn:aws:rds:$REGION:$ACCOUNT_ID:db:$RDS_INSTANCE_ID"

# Get SSM document ARN
SSM_DOCUMENT_ARN="arn:aws:ssm:$REGION:$ACCOUNT_ID:document/$SSM_DOCUMENT_NAME"

# Find FIS role ARN by listing all roles and finding the one with the stack name prefix
# This avoids hardcoding the role name format
echo "Finding FIS role..."
FIS_ROLES=$(aws iam list-roles --query "Roles[?contains(RoleName, '${STACK_NAME}') && contains(RoleName, 'FISExperimentRole')].{Name:RoleName,Arn:Arn}" --output json --region $REGION)
FIS_ROLE_ARN=$(echo $FIS_ROLES | jq -r '.[0].Arn')

if [ -z "$FIS_ROLE_ARN" ] || [ "$FIS_ROLE_ARN" == "null" ]; then
  echo "Error: Could not find FIS role for stack $STACK_NAME"
  exit 1
fi

echo "Retrieved resource information:"
echo "EC2 Instance ID: $EC2_INSTANCE_ID"
echo "EC2 Instance ARN: $EC2_INSTANCE_ARN"
echo "RDS Endpoint: $RDS_ENDPOINT"
echo "RDS Instance ID: $RDS_INSTANCE_ID"
echo "RDS Instance ARN: $RDS_INSTANCE_ARN"
echo "SSM Document Name: $SSM_DOCUMENT_NAME"
echo "SSM Document ARN: $SSM_DOCUMENT_ARN"
echo "FIS Role ARN: $FIS_ROLE_ARN"

# Create FIS experiment template
echo "Creating FIS experiment template..."
EXPERIMENT_TEMPLATE_RESULT=$(aws fis create-experiment-template --cli-input-json "{
  \"description\": \"MySQL RDS Load Test and Failover Experiment\",
  \"targets\": {
    \"EC2Instance\": {
      \"resourceType\": \"aws:ec2:instance\",
      \"resourceArns\": [
        \"$EC2_INSTANCE_ARN\"
      ],
      \"selectionMode\": \"ALL\"
    },
    \"DBInstances\": {
      \"resourceType\": \"aws:rds:db\",
      \"resourceArns\": [
        \"$RDS_INSTANCE_ARN\"
      ],
      \"selectionMode\": \"ALL\"
    }
  },
  \"actions\": {
    \"RunLoadTest\": {
      \"actionId\": \"aws:ssm:send-command\",
      \"description\": \"Run MySQL high CPU load test until target CPU utilization is reached\",
      \"parameters\": {
        \"documentArn\": \"$SSM_DOCUMENT_ARN\",
        \"documentParameters\": \"{\\\"Duration\\\":\\\"600\\\",\\\"Concurrency\\\":\\\"25\\\",\\\"DBHost\\\":\\\"$RDS_ENDPOINT\\\",\\\"DBName\\\":\\\"testdb\\\",\\\"DBUsername\\\":\\\"admin\\\",\\\"DBPassword\\\":\\\"$PASSWORD\\\",\\\"TargetCPU\\\":\\\"80\\\",\\\"DBInstanceId\\\":\\\"$RDS_INSTANCE_ID\\\"}\",
        \"duration\": \"PT15M\"
      },
      \"targets\": {
        \"Instances\": \"EC2Instance\"
      }
    },
    \"ForceFailover\": {
      \"actionId\": \"aws:rds:reboot-db-instances\",
      \"description\": \"Force a failover by rebooting the primary instance with failover\",
      \"parameters\": {
        \"forceFailover\": \"true\"
      },
      \"targets\": {
        \"DBInstances\": \"DBInstances\"
      },
      \"startAfter\": [
        \"RunLoadTest\"
      ]
    },
    \"StopLoadTest\": {
      \"actionId\": \"aws:ssm:send-command\",
      \"description\": \"Stop the load test after failover completes\",
      \"parameters\": {
        \"documentArn\": \"arn:aws:ssm:$REGION::document/AWS-RunShellScript\",
        \"documentParameters\": \"{\\\"commands\\\":[\\\"pkill -f \\\\\\\"run_worker\\\\\\\"\\\",\\\"echo \\\\\\\"Load test stopped\\\\\\\"\\\"]}\",
        \"duration\": \"PT1M\"
      },
      \"targets\": {
        \"Instances\": \"EC2Instance\"
      },
      \"startAfter\": [
        \"ForceFailover\"
      ]
    }
  },
  \"stopConditions\": [
    {
      \"source\": \"none\"
    }
  ],
  \"roleArn\": \"$FIS_ROLE_ARN\",
  \"logConfiguration\": {
    \"logSchemaVersion\": 2,
    \"cloudWatchLogsConfiguration\": {
      \"logGroupArn\": \"arn:aws:logs:$REGION:$ACCOUNT_ID:log-group:/aws/fis/experiment:*\"
    }
  },
  \"tags\": {
    \"Name\": \"MySQL-RDS-LoadTest-Failover\",
    \"Environment\": \"Test\",
    \"Application\": \"RDS-Failover-Testing\",
    \"Stack\": \"$STACK_NAME\"
  }
}" --region $REGION)

if [ $? -ne 0 ]; then
  echo "Error: Failed to create experiment template"
  exit 1
fi

# Extract experiment template ID
EXPERIMENT_TEMPLATE_ID=$(echo $EXPERIMENT_TEMPLATE_RESULT | jq -r '.experimentTemplate.id')
echo "Successfully created experiment template with ID: $EXPERIMENT_TEMPLATE_ID"

echo ""
echo "To run the experiment, use the following command:"
echo "aws fis start-experiment --experiment-template-id $EXPERIMENT_TEMPLATE_ID --region $REGION"
