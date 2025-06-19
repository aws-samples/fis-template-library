#!/bin/bash

# Aurora Cluster Failover Infrastructure Deployment Script
# This script deploys the CloudFormation template for the FIS experiment

set -e

# Configuration
STACK_NAME="aurora-fis-experiment"
TEMPLATE_FILE="cloudformation-infrastructure.yaml"
REGION="us-east-1"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if AWS CLI is installed and configured
check_aws_cli() {
    if ! command -v aws &> /dev/null; then
        print_error "AWS CLI is not installed. Please install it first."
        exit 1
    fi
    
    if ! aws sts get-caller-identity &> /dev/null; then
        print_error "AWS CLI is not configured. Please run 'aws configure' first."
        exit 1
    fi
}

# Function to get user input
get_user_input() {
    echo "Please provide the following information:"
    
    read -p "Stack name (default: $STACK_NAME): " input_stack_name
    STACK_NAME=${input_stack_name:-$STACK_NAME}
    
    read -p "AWS Region (default: $REGION): " input_region
    REGION=${input_region:-$REGION}
    
    read -p "Database username (default: postgres): " db_username
    db_username=${db_username:-postgres}
    
    while true; do
        read -s -p "Database password (min 8 characters): " db_password
        echo
        if [[ ${#db_password} -ge 8 ]]; then
            break
        else
            print_error "Password must be at least 8 characters long."
        fi
    done
    
    read -p "Database instance class (default: db.t3.medium): " db_instance_class
    db_instance_class=${db_instance_class:-db.t3.medium}
}

# Function to deploy the CloudFormation stack
deploy_stack() {
    print_status "Deploying CloudFormation stack: $STACK_NAME"
    
    aws cloudformation create-stack \
        --stack-name "$STACK_NAME" \
        --template-body "file://$TEMPLATE_FILE" \
        --parameters \
            ParameterKey=DBUsername,ParameterValue="$db_username" \
            ParameterKey=DBPassword,ParameterValue="$db_password" \
            ParameterKey=DBInstanceClass,ParameterValue="$db_instance_class" \
        --capabilities CAPABILITY_IAM \
        --region "$REGION"
    
    print_status "Stack creation initiated. Waiting for completion..."
    
    aws cloudformation wait stack-create-complete \
        --stack-name "$STACK_NAME" \
        --region "$REGION"
    
    if [ $? -eq 0 ]; then
        print_status "Stack deployed successfully!"
    else
        print_error "Stack deployment failed. Check the CloudFormation console for details."
        exit 1
    fi
}

# Function to display stack outputs
display_outputs() {
    print_status "Stack outputs:"
    aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$REGION" \
        --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
        --output table
}

# Function to create SSM document
create_ssm_document() {
    print_status "Creating SSM document for load testing..."
    
    if aws ssm describe-document --name "aurora-cluster-loadtest-document" --region "$REGION" &> /dev/null; then
        print_warning "SSM document already exists. Skipping creation."
    else
        aws ssm create-document \
            --name "aurora-cluster-loadtest-document" \
            --document-type "Command" \
            --content "file://../aurora-cluster-failover-ssm-template.json" \
            --region "$REGION"
        
        print_status "SSM document created successfully!"
    fi
}

# Function to display next steps
display_next_steps() {
    echo
    print_status "Deployment completed successfully!"
    echo
    echo "Next steps:"
    echo "1. Create the FIS IAM role using the provided policy documents"
    echo "2. Import the FIS experiment template into your account"
    echo "3. Set up CloudWatch monitoring and alarms"
    echo "4. Test the experiment in a controlled environment"
    echo
    echo "To clean up resources later, run:"
    echo "aws cloudformation delete-stack --stack-name $STACK_NAME --region $REGION"
}

# Main execution
main() {
    print_status "Aurora Cluster Failover Infrastructure Deployment"
    echo "=================================================="
    
    check_aws_cli
    get_user_input
    
    echo
    print_status "Configuration summary:"
    echo "Stack name: $STACK_NAME"
    echo "Region: $REGION"
    echo "Database username: $db_username"
    echo "Database instance class: $db_instance_class"
    echo
    
    read -p "Proceed with deployment? (y/N): " confirm
    if [[ $confirm != [yY] ]]; then
        print_warning "Deployment cancelled."
        exit 0
    fi
    
    deploy_stack
    display_outputs
    create_ssm_document
    display_next_steps
}

# Run main function
main "$@"
