#!/bin/bash
# Script to clean up all resources created for the MySQL RDS load test and failover experiment

# Configuration
STACK_NAME="$1"
REGION="$2"

# Validate required parameters
if [ -z "$STACK_NAME" ]; then
  echo "Error: Stack name is required"
  echo "Usage: $0 <stack-name> [region]"
  exit 1
fi

if [ -z "$REGION" ]; then
  echo "Error: Region is required"
  echo "Usage: $0 <stack-name> <region>"
  exit 1
fi

# Function to check if a command succeeded
check_success() {
  if [ $? -ne 0 ]; then
    echo "Error: $1"
    exit 1
  fi
}

# Step 1: Find and stop any running FIS experiments
echo "Checking for running FIS experiments..."
RUNNING_EXPERIMENTS=$(aws fis list-experiments --region $REGION --query "experiments[?state.status=='running' || state.status=='pending'].id" --output text)

if [ -n "$RUNNING_EXPERIMENTS" ]; then
  echo "Found running experiments. Stopping them..."
  for EXP_ID in $RUNNING_EXPERIMENTS; do
    echo "Stopping experiment: $EXP_ID"
    aws fis stop-experiment --id $EXP_ID --region $REGION
    check_success "Failed to stop experiment $EXP_ID"
    echo "Waiting for experiment to stop..."
    aws fis wait experiment-stopped --id $EXP_ID --region $REGION
  done
else
  echo "No running experiments found."
fi

# Step 2: Find and delete FIS experiment templates related to the stack
echo "Finding FIS experiment templates..."
FIS_TEMPLATES=$(aws fis list-experiment-templates --region $REGION --query "experimentTemplates[?contains(tags.Stack, '$STACK_NAME') || contains(description, 'MySQL')].id" --output text)

if [ -n "$FIS_TEMPLATES" ]; then
  echo "Found FIS experiment templates. Deleting them..."
  for TEMPLATE_ID in $FIS_TEMPLATES; do
    echo "Deleting experiment template: $TEMPLATE_ID"
    aws fis delete-experiment-template --id $TEMPLATE_ID --region $REGION
    check_success "Failed to delete experiment template $TEMPLATE_ID"
  done
else
  echo "No FIS experiment templates found for stack $STACK_NAME."
fi

# Step 3: Delete the CloudFormation stack
echo "Deleting CloudFormation stack: $STACK_NAME"
aws cloudformation delete-stack --stack-name $STACK_NAME --region $REGION
check_success "Failed to initiate stack deletion"

echo "Waiting for stack deletion to complete..."
aws cloudformation wait stack-delete-complete --stack-name $STACK_NAME --region $REGION

if [ $? -eq 0 ]; then
  echo "Stack deletion completed successfully."
else
  echo "Stack deletion may have failed or timed out. Please check the AWS Console."
fi

echo "Cleanup completed."
echo "Note: If there were any resources that couldn't be automatically deleted, you may need to manually remove them from the AWS Console."
