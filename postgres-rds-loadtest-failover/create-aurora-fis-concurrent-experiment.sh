#!/bin/bash

# Default values
STACK_NAME=${1:-"postgres-rds-loadtest"}
REGION=${2:-$(aws configure get region || echo "us-east-2")}
RANDOM_STRING=${3:-$(openssl rand -hex 4)}
LOG_GROUP_NAME="/aws/fis/postgres-aurora-loadtest-$RANDOM_STRING"
EXPERIMENT_TEMPLATE_FILE="fis-experiment-aurora-loadtest-concurrent.json"
RETENTION_DAYS=30
FIS_ROLE_NAME="FISExperimentRoleAurora"

# Display configuration
echo "Configuration:"
echo "  Stack Name: $STACK_NAME"
echo "  Region: $REGION"
echo "  Log Group: $LOG_GROUP_NAME"
echo "  FIS Role Name: $FIS_ROLE_NAME"

# Get EC2 Instance ARN
EC2_INSTANCE_ID=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --region $REGION \
  --query "Stacks[0].Outputs[?OutputKey=='EC2InstanceId'].OutputValue" \
  --output text)

if [ -z "$EC2_INSTANCE_ID" ]; then
  echo "Error: Could not find EC2 Instance ID"
  exit 1
fi

echo "EC2 Instance ID: $EC2_INSTANCE_ID"

# Get EC2 Instance ARN
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
EC2_INSTANCE_ARN="arn:aws:ec2:$REGION:$ACCOUNT_ID:instance/$EC2_INSTANCE_ID"

echo "EC2 Instance ARN: $EC2_INSTANCE_ARN"

# Get Aurora Cluster ARN
AURORA_CLUSTER_ARN=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --region $REGION \
  --query "Stacks[0].Outputs[?OutputKey=='AuroraClusterEndpoint'].OutputValue" \
  --output text | xargs -I {} aws rds describe-db-clusters \
  --region $REGION \
  --query "DBClusters[?Endpoint=='{}'].DBClusterArn" \
  --output text)

if [ -z "$AURORA_CLUSTER_ARN" ]; then
  echo "Error: Could not find Aurora Cluster ARN"
  exit 1
fi

echo "Aurora Cluster ARN: $AURORA_CLUSTER_ARN"

# Get SSM Document ARN
SSM_DOCUMENT_NAME=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --region $REGION \
  --query "Stacks[0].Outputs[?OutputKey=='SSMDocumentName'].OutputValue" \
  --output text)

if [ -z "$SSM_DOCUMENT_NAME" ]; then
  echo "Error: Could not find SSM Document Name"
  exit 1
fi

SSM_DOCUMENT_ARN="arn:aws:ssm:$REGION:$ACCOUNT_ID:document/$SSM_DOCUMENT_NAME"
echo "SSM Document ARN: $SSM_DOCUMENT_ARN"

# Get FIS Experiment Role ARN
FIS_ROLE_ARN=$(aws iam get-role --role-name $FIS_ROLE_NAME --query "Role.Arn" --output text)

if [ -z "$FIS_ROLE_ARN" ]; then
  echo "Error: Could not find FIS Experiment Role ARN"
  exit 1
fi

echo "FIS Role ARN: $FIS_ROLE_ARN"

# Create CloudWatch Log Group if it doesn't exist
if ! aws logs describe-log-groups --log-group-name-prefix $LOG_GROUP_NAME --region $REGION --query "logGroups[?logGroupName=='$LOG_GROUP_NAME']" --output text > /dev/null 2>&1; then
  echo "Creating CloudWatch Log Group: $LOG_GROUP_NAME"
  aws logs create-log-group --log-group-name $LOG_GROUP_NAME --region $REGION
  aws logs put-retention-policy --log-group-name $LOG_GROUP_NAME --retention-in-days $RETENTION_DAYS --region $REGION
else
  echo "CloudWatch Log Group $LOG_GROUP_NAME already exists"
fi

# Get Log Group ARN - Construct it with the correct format
LOG_GROUP_ARN="arn:aws:logs:$REGION:$ACCOUNT_ID:log-group:$LOG_GROUP_NAME:*"

echo "Log Group ARN: $LOG_GROUP_ARN"

# Update the experiment template with the actual ARNs
TMP_TEMPLATE=$(mktemp)
cat $EXPERIMENT_TEMPLATE_FILE | \
  jq --arg cluster "$AURORA_CLUSTER_ARN" '.targets.cluster.resourceArns = [$cluster]' | \
  jq --arg ec2 "$EC2_INSTANCE_ARN" '.targets.EC2Instance.resourceArns = [$ec2]' | \
  jq --arg ssm "$SSM_DOCUMENT_ARN" '.actions.RunLoadTest.parameters.documentArn = $ssm' | \
  jq --arg role "$FIS_ROLE_ARN" '.roleArn = $role' | \
  jq --arg log "$LOG_GROUP_ARN" '.logConfiguration.cloudWatchLogsConfiguration.logGroupArn = $log' > $TMP_TEMPLATE

# Create the experiment template
TEMPLATE_ID=$(aws fis create-experiment-template \
  --cli-input-json file://$TMP_TEMPLATE \
  --region $REGION \
  --query "experimentTemplate.id" \
  --output text)

if [ -z "$TEMPLATE_ID" ]; then
  echo "Error: Failed to create experiment template"
  exit 1
fi

echo "Created FIS Experiment Template: $TEMPLATE_ID"

# Clean up temporary file
rm $TMP_TEMPLATE

# Start the experiment
EXPERIMENT_ID=$(aws fis start-experiment \
  --experiment-template-id $TEMPLATE_ID \
  --region $REGION \
  --query "experiment.id" \
  --output text)

if [ -z "$EXPERIMENT_ID" ]; then
  echo "Error: Failed to start experiment"
  exit 1
fi

echo "Started FIS Experiment: $EXPERIMENT_ID"
echo "You can monitor the experiment with:"
echo "aws fis get-experiment --id $EXPERIMENT_ID --region $REGION"
echo "aws logs get-log-events --log-group-name $LOG_GROUP_NAME --log-stream-name $EXPERIMENT_ID --region $REGION"
