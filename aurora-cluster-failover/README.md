# AWS Fault Injection Service Experiment: Aurora Cluster CPU Overload and Failover

This experiment template simulates CPU overload on an Aurora PostgreSQL cluster and then initiates a failover.

## Description

This experiment deploys an Aurora PostgreSQL cluster with a CloudFormation template, generates CPU load using an SSM document, and then initiates a cluster failover.

## Hypothesis

High CPU load on an Aurora cluster will cause degraded performance, and a subsequent failover will restore normal operation.

## Prerequisites

1. AWS CLI installed and configured with appropriate permissions
2. An IAM role named `FISExperimentRoleAurora` with the following permissions:
   - AWSFaultInjectionSimulatorSSMAccess
   - CloudWatchFullAccess
   - AmazonRDSFullAccess

## Setup and Execution Steps

### 1. Deploy the Infrastructure

Deploy the CloudFormation template to create the required infrastructure:

```bash
# Replace REGION with your desired AWS region (e.g., us-east-2, us-west-2, etc.)
export REGION="us-east-2"

aws cloudformation create-stack \
  --stack-name postgres-test-stack \
  --template-body file://cloudformation-aurora.yaml \
  --parameters ParameterKey=DBUsername,ParameterValue=postgres \
               ParameterKey=DBPassword,ParameterValue=YourSecurePassword \
  --capabilities CAPABILITY_NAMED_IAM \
  --region $REGION
```

This template creates:
- A VPC with public and private subnets
- An EC2 instance with SSM access
- An Aurora PostgreSQL cluster with two instances
- An SSM document for load testing
- The required IAM role for FIS experiments

### 2. Run the Experiment

Execute the experiment using the provided script:

```bash
chmod +x run-experiment.sh
./run-experiment.sh --region $REGION
```

The script will:
1. Create a CloudWatch Log Group for experiment logs
2. Retrieve resource ARNs from the CloudFormation stack
3. Update the FIS experiment template with the correct ARNs
4. Create and start the FIS experiment

### 3. Monitor the Experiment

Monitor the experiment using:

```bash
# Get experiment status
aws fis get-experiment --id <EXPERIMENT_ID> --region $REGION

# View experiment logs
aws logs get-log-events --log-group-name <LOG_GROUP_NAME> --log-stream-name <EXPERIMENT_ID> --region $REGION
```

## How it works

1. The experiment first runs a 5-minute delay action
2. It executes an SSM document on the EC2 instance to generate load on the Aurora cluster
3. After the delay, it initiates a failover for the Aurora cluster
4. The load test continues running to observe the impact of the failover

## Files in this Project

- `cloudformation-aurora.yaml`: CloudFormation template for infrastructure
- `fis-experiment-aurora-loadtest-concurrent.json`: FIS experiment template
- `ssm-loadtest-shell-script.yaml`: SSM document content for load testing
- `run-experiment.sh`: Script to deploy and run the experiment
- `cleanup.sh`: Script to clean up all resources created by this experiment

## Cleanup

After you've completed the experiment, you can clean up all the resources using the provided cleanup script:

```bash
chmod +x cleanup.sh
./cleanup.sh --stack-name <STACK_NAME> --region <REGION>
```

For example:
```bash
./cleanup.sh --stack-name postgres-test-stack --region us-east-2
```

The cleanup script will:
1. Delete any FIS experiment templates related to the stack
2. Delete CloudWatch Log Groups created by the experiment
3. Delete the CloudFormation stack and all its resources

## Next Steps

1. Customize the experiment parameters in `fis-experiment-aurora-loadtest-concurrent.json`
2. Modify the load test parameters in the script (duration, concurrency)
3. Add CloudWatch alarms as stop conditions
4. Create a CloudWatch dashboard to visualize the experiment's effects
