#!/bin/bash

# Set variables
STACK_NAME="postgres-aurora-loadtest-v2"
REGION="us-east-2"
LOG_GROUP_NAME="/aws/fis/postgres-aurora-loadtest"
EXPERIMENT_TEMPLATE_FILE="fis-experiment-aurora.json"
RETENTION_DAYS=30

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

# Get FIS Experiment Role ARN
FIS_ROLE_ARN=$(aws iam get-role --role-name FISExperimentRoleAurora --query "Role.Arn" --output text)

if [ -z "$FIS_ROLE_ARN" ]; then
  echo "Error: Could not find FIS Experiment Role ARN"
  exit 1
fi

echo "FIS Role ARN: $FIS_ROLE_ARN"

# Create CloudWatch Log Group if it doesn't exist
aws logs describe-log-groups --log-group-name-prefix $LOG_GROUP_NAME --region $REGION --query "logGroups[?logGroupName=='$LOG_GROUP_NAME']" --output text > /dev/null 2>&1
if [ $? -ne 0 ]; then
  echo "Creating CloudWatch Log Group: $LOG_GROUP_NAME"
  aws logs create-log-group --log-group-name $LOG_GROUP_NAME --region $REGION
  aws logs put-retention-policy --log-group-name $LOG_GROUP_NAME --retention-in-days $RETENTION_DAYS --region $REGION
else
  echo "CloudWatch Log Group $LOG_GROUP_NAME already exists"
fi

# Get Log Group ARN - Construct it with the correct format
LOG_GROUP_ARN="arn:aws:logs:$REGION:$(aws sts get-caller-identity --query Account --output text):log-group:$LOG_GROUP_NAME:*"

echo "Log Group ARN: $LOG_GROUP_ARN"

# Update the experiment template with the actual ARNs
TMP_TEMPLATE=$(mktemp)
cat $EXPERIMENT_TEMPLATE_FILE | \
  jq --arg cluster "$AURORA_CLUSTER_ARN" '.targets.cluster.resourceArns = [$cluster]' | \
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
