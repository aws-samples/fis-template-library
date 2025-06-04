#!/bin/bash

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --region)
      REGION="$2"
      shift 2
      ;;
    --stack-name)
      STACK_NAME="$2"
      shift 2
      ;;
    --help)
      echo "Usage: $0 --stack-name <stack-name> --region <region>"
      echo "Example: $0 --stack-name aurora-fis-test-v1 --region us-west-2"
      exit 0
      ;;
    *)
      shift
      ;;
  esac
done

# Check if required parameters are provided
if [ -z "$STACK_NAME" ]; then
  echo "Error: Stack name is required"
  echo "Usage: $0 --stack-name <stack-name> --region <region>"
  exit 1
fi

# Default to current region if not specified
if [ -z "$REGION" ]; then
  REGION=$(aws configure get region)
  if [ -z "$REGION" ]; then
    echo "Error: Region not specified and not found in AWS CLI configuration"
    echo "Usage: $0 --stack-name <stack-name> --region <region>"
    exit 1
  fi
  echo "Using region from AWS CLI configuration: $REGION"
fi

echo "Cleaning up resources for stack: $STACK_NAME in region: $REGION"

# Find and delete all FIS experiment templates related to this stack
echo "Finding FIS experiment templates..."
# Use the stack name as part of the query to find related templates
TEMPLATE_IDS=$(aws fis list-experiment-templates --region $REGION --query "experimentTemplates[?contains(to_string(tags), '$STACK_NAME')].id" --output text)

if [ -n "$TEMPLATE_IDS" ]; then
  for TEMPLATE_ID in $TEMPLATE_IDS; do
    echo "Deleting FIS experiment template: $TEMPLATE_ID"
    aws fis delete-experiment-template --id $TEMPLATE_ID --region $REGION
  done
else
  echo "No FIS experiment templates found related to stack: $STACK_NAME"
fi

# Find and delete all CloudWatch Log Groups created by the experiment
echo "Finding CloudWatch Log Groups..."
# Use the stack name as part of the log group prefix
LOG_GROUPS=$(aws logs describe-log-groups --log-group-name-prefix "/aws/fis/postgres-aurora-loadtest" --region $REGION --query "logGroups[*].logGroupName" --output text)

if [ -n "$LOG_GROUPS" ]; then
  for LOG_GROUP in $LOG_GROUPS; do
    echo "Deleting CloudWatch Log Group: $LOG_GROUP"
    aws logs delete-log-group --log-group-name $LOG_GROUP --region $REGION
  done
else
  echo "No CloudWatch Log Groups found with prefix: /aws/fis/postgres-aurora-loadtest"
fi

# Delete the CloudFormation stack
echo "Deleting CloudFormation stack: $STACK_NAME"
aws cloudformation delete-stack --stack-name $STACK_NAME --region $REGION

echo "Waiting for stack deletion to complete..."
aws cloudformation wait stack-delete-complete --stack-name $STACK_NAME --region $REGION

if [ $? -eq 0 ]; then
  echo "Stack deletion completed successfully."
else
  echo "Stack deletion may still be in progress. Check the AWS Console for status."
fi

echo "Cleanup completed!"
