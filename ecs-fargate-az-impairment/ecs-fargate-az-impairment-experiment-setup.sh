#!/bin/bash
set -e

# ECS Fargate AZ Impairment - Manual Deployment Script
# This script deploys all required resources for the FIS experiment
#
# Usage: ./ecs-fargate-az-impairment-experiment-setup.sh [--profile <aws-profile>] [--region <aws-region>]

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --profile)
            AWS_PROFILE="$2"
            shift 2
            ;;
        --region)
            AWS_REGION="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--profile <aws-profile>] [--region <aws-region>]"
            exit 1
            ;;
    esac
done

# Set profile flag for AWS CLI commands
PROFILE_FLAG=""
if [ -n "$AWS_PROFILE" ]; then
    PROFILE_FLAG="--profile $AWS_PROFILE"
    export AWS_PROFILE
fi

echo "=============================================="
echo "ECS Fargate AZ Impairment - Manual Deployment"
echo "=============================================="

# Disable AWS CLI pager to prevent interactive prompts
export AWS_PAGER=""

# Get AWS Account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text $PROFILE_FLAG)
AWS_REGION=${AWS_REGION:-$(aws configure get region $PROFILE_FLAG)}

if [ -z "$AWS_REGION" ]; then
    echo "Error: AWS_REGION not set. Please set it via --region flag or configure AWS CLI default region."
    exit 1
fi

echo "AWS Profile: ${AWS_PROFILE:-default}"
echo "AWS Account: $AWS_ACCOUNT_ID"
echo "AWS Region: $AWS_REGION"
echo ""

# Change to script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Step 1: Create SSM Automation Documents
echo "Step 1: Creating SSM Automation Documents..."

echo "  Creating subnet automation document..."
aws ssm create-document \
  --name "ecs-fargate-az-impairment-subnet-automation" \
  --document-type "Automation" \
  --content file://ecs-fargate-az-impairment-subnet-automation.yaml \
  --document-format YAML \
  --region "$AWS_REGION" $PROFILE_FLAG >/dev/null 2>&1 || echo "  Document already exists, skipping..."

echo "  SSM Document created."
echo ""

# Step 2: Create IAM Roles
echo "Step 2: Creating IAM Roles..."

echo "  Creating FIS execution role..."
aws iam create-role \
  --role-name fis-ecs-az-impairment-role \
  --assume-role-policy-document file://fis-iam-trust-relationship.json $PROFILE_FLAG >/dev/null 2>&1 || echo "  Role already exists, skipping..."

echo "  Creating SSM automation role..."
aws iam create-role \
  --role-name ssm-ecs-az-impairment-role \
  --assume-role-policy-document file://ecs-fargate-az-impairment-ssm-trust-relationship.json $PROFILE_FLAG >/dev/null 2>&1 || echo "  Role already exists, skipping..."

echo "  IAM Roles created."
echo ""

# Step 3: Create and Attach IAM Policies
echo "Step 3: Creating and Attaching IAM Policies..."

# Create custom policy
echo "  Creating custom IAM policy..."
POLICY_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:policy/fis-ecs-az-impairment-policy"
aws iam create-policy \
  --policy-name fis-ecs-az-impairment-policy \
  --policy-document file://ecs-fargate-az-impairment-iam-policy.json $PROFILE_FLAG >/dev/null 2>&1 || echo "  Policy already exists, skipping..."

# Attach custom policy to FIS role
echo "  Attaching custom policy to FIS role..."
aws iam attach-role-policy \
  --role-name fis-ecs-az-impairment-role \
  --policy-arn "$POLICY_ARN" $PROFILE_FLAG >/dev/null 2>&1 || true

# Attach custom policy to SSM role
echo "  Attaching custom policy to SSM role..."
aws iam attach-role-policy \
  --role-name ssm-ecs-az-impairment-role \
  --policy-arn "$POLICY_ARN" $PROFILE_FLAG >/dev/null 2>&1 || true

# Attach AWS managed policies to FIS role
echo "  Attaching AWS managed policies to FIS role..."
aws iam attach-role-policy \
  --role-name fis-ecs-az-impairment-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSFaultInjectionSimulatorECSAccess $PROFILE_FLAG >/dev/null 2>&1 || true

aws iam attach-role-policy \
  --role-name fis-ecs-az-impairment-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSFaultInjectionSimulatorSSMAccess $PROFILE_FLAG >/dev/null 2>&1 || true

aws iam attach-role-policy \
  --role-name fis-ecs-az-impairment-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSFaultInjectionSimulatorNetworkAccess $PROFILE_FLAG >/dev/null 2>&1 || true

echo "  IAM Policies attached."
echo ""

# Step 4: Create FIS Experiment Template
echo "Step 4: Creating FIS Experiment Template..."

# Create a temporary file with substituted values
TEMP_TEMPLATE=$(mktemp)
sed -e "s/<YOUR AWS ACCOUNT>/${AWS_ACCOUNT_ID}/g" \
    -e "s/<YOUR REGION>/${AWS_REGION}/g" \
    -e "s/<YOUR ROLE NAME>/fis-ecs-az-impairment-role/g" \
    -e "s/<YOUR SSM ROLE NAME>/ssm-ecs-az-impairment-role/g" \
    ecs-fargate-az-impairment-template.json > "$TEMP_TEMPLATE"

echo "  Creating FIS experiment template..."
EXPERIMENT_TEMPLATE_ID=$(aws fis create-experiment-template \
  --cli-input-json file://"$TEMP_TEMPLATE" \
  --query 'experimentTemplate.id' \
  --output text \
  --region "$AWS_REGION" $PROFILE_FLAG 2>/dev/null) || {
    echo "  Warning: Could not create experiment template. You may need to update placeholder values manually."
    rm -f "$TEMP_TEMPLATE"
}

rm -f "$TEMP_TEMPLATE"

echo "  FIS Experiment Template created."
echo ""

# Summary
echo "=============================================="
echo "Deployment Complete!"
echo "=============================================="
echo ""
echo "Resources created:"
echo "  - SSM Document: ecs-fargate-az-impairment-subnet-automation"
echo "  - IAM Role: fis-ecs-az-impairment-role"
echo "  - IAM Role: ssm-ecs-az-impairment-role"
echo "  - IAM Policy: fis-ecs-az-impairment-policy"
if [ -n "$EXPERIMENT_TEMPLATE_ID" ]; then
    echo "  - FIS Experiment Template: $EXPERIMENT_TEMPLATE_ID"
fi
echo ""
echo "Next Steps:"
echo "  1. Update the FIS experiment template with your ECS cluster, service, and subnet values"
echo "  2. Tag your ECS tasks with 'FIS-Ready=True'"
echo "  3. Run the experiment: aws fis start-experiment --experiment-template-id <template-id>"
echo ""
