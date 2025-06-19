# EXAMPLE DEPLOYMENT SCRIPT - FOR REFERENCE ONLY
# This is an example script showing how you might deploy the infrastructure
# Copy and customize this for your specific environment and requirements
# DO NOT run this script directly - it's meant as a template for your own deployment

# Configuration - Modify these values for your environment
STACK_NAME="mysql-loadtest-infrastructure"
REGION="us-east-1"

# Prompt for database password securely
echo "Enter database password (minimum 8 characters, no spaces, '/', '@', or '\"'):"
read -s DB_PASSWORD

if [ ${#DB_PASSWORD} -lt 8 ]; then
    echo "Error: Password must be at least 8 characters long"
    exit 1
fi

echo "Deploying infrastructure stack: $STACK_NAME in region: $REGION"

# Deploy CloudFormation stack
aws cloudformation create-stack \
    --stack-name "$STACK_NAME" \
    --template-body file://cloudformation-infrastructure.yaml \
    --parameters \
        ParameterKey=DBPassword,ParameterValue="$DB_PASSWORD" \
    --capabilities CAPABILITY_IAM \
    --region "$REGION" \
    --tags \
        Key=Purpose,Value=FIS-Testing

if [ $? -eq 0 ]; then
    echo "Stack creation initiated successfully!"
    echo "Monitor progress with: aws cloudformation describe-stacks --stack-name $STACK_NAME --region $REGION"
    echo ""
    echo "After stack creation completes, deploy the SSM document:"
    echo "aws ssm create-document --name 'MySQL-LoadTest-Document' --document-type 'Command' --content file://mysql-loadtest-ssm-document.json --region $REGION"
else
    echo "Error: Failed to create stack"
    exit 1
fi

echo ""
echo "Next steps:"
echo "1. Wait for stack creation to complete"
echo "2. Deploy the SSM document using the command above"
echo "3. Update your FIS experiment template with the correct resource tags"
echo "4. Test the load generation script before running the FIS experiment"
