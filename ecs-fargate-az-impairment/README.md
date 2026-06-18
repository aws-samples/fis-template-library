# AWS Fault Injection Service Experiment: ECS Fargate Availability Zone Impairment

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE

## Hypothesis

When an Availability Zone experiences an impairment affecting an ECS Fargate service, the service should continue operating with reduced capacity using tasks in the remaining healthy AZs. Specifically:

- When tasks are stopped in the target AZ, ECS should reschedule them to healthy AZs
- When the subnet is removed from the service configuration, new tasks should only launch in remaining subnets
- When network packet loss is injected, affected tasks should be detected as unhealthy
- The application should remain available throughout the experiment with degraded but functional capacity
- When the subnet is restored, the service should automatically rebalance tasks across all AZs

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment and perform ECS service updates, SSM automation executions, and EC2 network operations.
2. The IAM roles have been deployed via the CloudFormation template or manually created with the required permissions from `ecs-fargate-az-impairment-iam-policy.json`.
3. The ECS cluster and service you want to target have the `FIS-Ready=True` tag applied.
4. Your ECS Fargate service is configured with multiple subnets across at least 2 different Availability Zones (minimum 2 subnets required - the experiment cannot remove the last subnet).
5. The SSM automation documents (`ecs-fargate-az-impairment-remove-subnet-automation` and `ecs-fargate-az-impairment-add-subnet-automation`) have been deployed to your account.
6. Your service has sufficient capacity in remaining AZs to handle the workload during the 15-minute experiment duration.
7. SSM Agent connectivity is available for the automation documents to execute.
8. You have updated all placeholder values (`<YOUR ...>`) in the experiment template with your actual resource identifiers.

## How It Works

This experiment simulates a complete Availability Zone impairment by executing multiple fault injection actions in parallel, followed by automatic recovery:

### Experiment Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PARALLEL ACTIONS (Start)                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐  │
│  │  stop-tasks-in-az   │  │ remove-subnet-from- │  │ inject-network-     │  │
│  │  (aws:ecs:stop-task)│  │ service (SSM)       │  │ packet-loss         │  │
│  │  Duration: 15min    │  │ Duration: 10min max │  │ Duration: 15min     │  │
│  └─────────────────────┘  └─────────────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       restore-subnet-to-service                             │
│                    (SSM Automation - adds subnet back)                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Actions Detail

| Action | Action ID | Description | Duration |
|--------|-----------|-------------|----------|
| `stop-tasks-in-az` | `aws:ecs:stop-task` | Stops all ECS Fargate tasks running in the target AZ | 15 minutes |
| `remove-subnet-from-service` | `aws:ssm:start-automation-execution` | Removes the target subnet from the ECS service network configuration | 5 min max |
| `inject-network-packet-loss` | `aws:ecs:task-network-packet-loss` | Injects 100% packet loss for tasks in the target AZ | 15 minutes |
| `restore-subnet-to-service` | `aws:ssm:start-automation-execution` | Restores the subnet to the ECS service configuration | 5 min max |

### SSM Automation Documents

The experiment uses two custom SSM Automation documents:

**ecs-fargate-az-impairment-remove-subnet-automation**
- Validates input parameters (subnet ID format, cluster/service existence)
- Retrieves current ECS service network configuration
- Validates the subnet exists in the current configuration
- Ensures at least one subnet remains after removal
- Updates the ECS service with the new subnet configuration
- Waits for service stability (up to 10 minutes)
- Generates detailed execution report

**ecs-fargate-az-impairment-add-subnet-automation**
- Validates input parameters and subnet existence in EC2
- Validates the subnet is in the same VPC as existing subnets
- Checks if subnet already exists (skips if already present)
- Updates the ECS service to include the restored subnet
- Waits for service stability
- Generates detailed execution report

## Targets

| Target Name | Resource Type | Selection Mode | Description |
|-------------|---------------|----------------|-------------|
| `ecs-tasks-in-target-az` | `aws:ecs:task` | ALL | All ECS tasks in the specified cluster/service within the target AZ |

### Target Requirements
- Tasks must have the `FIS-Ready=True` tag
- Tasks must be running in the specified ECS cluster and service
- Tasks must be in the target Availability Zone

## Parameters to Configure

Before running the experiment, update these placeholder values:

| Placeholder | Description |
|-------------|-------------|
| `<YOUR AWS ACCOUNT>` | Your 12-digit AWS account ID |
| `<YOUR REGION>` | AWS region where resources are deployed |
| `<YOUR ROLE NAME>` | FIS execution IAM role name |
| `<YOUR SSM ROLE NAME>` | SSM automation IAM role name |
| `<YOUR ECS CLUSTER>` | Name of your ECS cluster |
| `<YOUR ECS SERVICE>` | Name of your ECS service |
| `<YOUR SUBNET ID>` | Subnet ID to remove/restore |
| `<YOUR TARGET AZ>` | Availability Zone to impair |

## Stop Conditions

The experiment does not have any specific stop conditions defined by default. It will continue to run until manually stopped or until all actions complete successfully (approximately 30-45 minutes total).

> **Note:** The experiment uses `emptyTargetResolutionMode: "skip"` because tasks may not exist in the target Availability Zone if the service hasn't scheduled tasks there yet. This prevents the experiment from failing when no tasks match the AZ filter at the time of execution.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

### Recommended Metrics for Stop Conditions

Consider creating CloudWatch alarms for these metrics:

- **ECS Service Metrics**
  - `CPUUtilization` - Alert if remaining tasks are overloaded
  - `MemoryUtilization` - Alert if memory pressure increases
  - `RunningTaskCount` - Alert if task count drops below minimum threshold

- **Application Metrics**
  - Request latency (P99, P95)
  - Error rate (5xx responses)
  - Request throughput

- **Load Balancer Metrics** (if applicable)
  - `TargetResponseTime`
  - `HTTPCode_Target_5XX_Count`
  - `UnHealthyHostCount`

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case. The default tag is `FIS-Ready=True`.
2. Identifying business metrics tied to your ECS Fargate service health (request latency, error rates, task health, throughput).
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of AZ impairment on service availability.
4. Adding a stop condition tied to the alarm to automatically halt the experiment if critical thresholds are breached.
5. Testing in a non-production environment first to validate the automation behavior before running against production services.
6. Adjusting the experiment duration (default 15 minutes) based on your testing requirements and recovery time objectives.
7. Running the experiment in a non-production environment first to understand the impact on your specific application.
8. Documenting the expected behavior and actual results to build a runbook for real AZ failures.
9. Gradually increasing the scope of the experiment (e.g., longer duration, multiple services) as confidence grows.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).

## Deployment

### Option 1: CloudFormation (Recommended)

Deploy all resources including SSM documents, IAM roles, and FIS experiment template:

```bash
aws cloudformation deploy \
  --template-file fis-ecs-fargate-az-impairment-cloudformation-template.yaml \
  --stack-name ecs-fargate-az-impairment \
  --capabilities CAPABILITY_NAMED_IAM
```

After deployment, update the experiment template in the FIS console with your actual parameter values.

### Option 2: Manual Deployment

```bash
./ecs-fargate-az-impairment-experiment-setup.sh
```

> **Note:** Before running the above command, update all placeholder values (`<YOUR ...>`) in `ecs-fargate-az-impairment-template.json` with your actual resource identifiers. Alternatively you can update the experiment template in the Console later.

## Files in This Directory

| File | Description |
|------|-------------|
| `README.md` | This documentation file |
| `AWSFIS.json` | Template version marker for fis-template-library-tooling |
| `ecs-fargate-az-impairment-template.json` | FIS experiment template definition |
| `ecs-fargate-az-impairment-iam-policy.json` | IAM policy for FIS and SSM execution |
| `fis-iam-trust-relationship.json` | Trust policy for FIS service |
| `ecs-fargate-az-impairment-ssm-trust-relationship.json` | Trust policy for SSM service |
| `ecs-fargate-az-impairment-remove-subnet-automation.yaml` | SSM Automation document to remove subnet |
| `ecs-fargate-az-impairment-add-subnet-automation.yaml` | SSM Automation document to add subnet |
| `fis-ecs-fargate-az-impairment-cloudformation-template.yaml` | CloudFormation template for full deployment |
| `ecs-fargate-az-impairment-experiment-setup.sh` | Manual deployment script |
