#!/bin/bash

# Default values - use generic defaults that can be overridden
STACK_NAME=${1:-"postgres-rds-loadtest"}
REGION=${2:-$(aws configure get region || echo "us-east-2")}

echo "Starting cleanup for stack: $STACK_NAME in region: $REGION"

# Step 1: Find and delete all FIS experiment templates related to PostgreSQL experiments
echo "Finding and deleting FIS experiment templates..."
EXPERIMENT_TEMPLATES=$(aws fis list-experiment-templates --region $REGION --query "experimentTemplates[?contains(tags.Name, 'PostgreSQL')].id" --output text)

if [ -n "$EXPERIMENT_TEMPLATES" ]; then
  for TEMPLATE_ID in $EXPERIMENT_TEMPLATES; do
    echo "Deleting FIS experiment template: $TEMPLATE_ID"
    aws fis delete-experiment-template --id $TEMPLATE_ID --region $REGION
  done
else
  echo "No FIS experiment templates found."
fi

# Step 2: Find and delete CloudWatch Log Groups related to PostgreSQL experiments
echo "Finding and deleting CloudWatch Log Groups..."
LOG_GROUPS=$(aws logs describe-log-groups --log-group-name-prefix "/aws/fis/postgres" --region $REGION --query "logGroups[*].logGroupName" --output text)

if [ -n "$LOG_GROUPS" ]; then
  for LOG_GROUP in $LOG_GROUPS; do
    echo "Deleting CloudWatch Log Group: $LOG_GROUP"
    aws logs delete-log-group --log-group-name $LOG_GROUP --region $REGION
  done
else
  echo "No CloudWatch Log Groups found with prefix '/aws/fis/postgres'."
fi

# Step 3: Delete the CloudFormation stack
echo "Deleting CloudFormation stack: $STACK_NAME"
aws cloudformation delete-stack --stack-name $STACK_NAME --region $REGION

echo "Waiting for stack deletion to complete..."
aws cloudformation wait stack-delete-complete --stack-name $STACK_NAME --region $REGION

if [ $? -eq 0 ]; then
  echo "Stack deletion completed successfully."
else
  echo "Stack deletion may have failed or is still in progress. Please check the AWS CloudFormation console."
fi

echo "Cleanup process completed."
echo "Note: If you have any running FIS experiments, you may need to stop them manually using:"
echo "aws fis stop-experiment --id <experiment-id> --region $REGION"
