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
2. The IAM roles have been created with the required permissions from `ecs-fargate-az-impairment-fis-role-iam-policy.json` (FIS execution role) and `ecs-fargate-az-impairment-ssm-automation-role-iam-policy.json` (SSM automation role).
3. The ECS cluster, **service**, and tasks all have the `FIS-Ready=True` tag. The service must be tagged directly (required by the SSM automation role policy — `ecs:DescribeServices` and `ecs:UpdateService` are conditioned on `aws:ResourceTag/FIS-Ready: True`; an untagged service causes AccessDenied at the first automation step before any subnet is removed). Tags must also propagate to tasks at launch time (`propagateTags: SERVICE` or `TASK_DEFINITION` in the service definition). You can verify with:
   ```bash
   aws ecs describe-tasks --cluster <cluster> --tasks $(aws ecs list-tasks --cluster <cluster> --service-name <service> --query 'taskArns[0]' --output text) --query 'tasks[0].tags'
   ```
4. Your ECS Fargate service is configured with multiple subnets across at least 2 different Availability Zones (minimum 2 subnets required - the experiment cannot remove the last subnet).
5. The SSM automation document (`ecs-fargate-az-impairment-subnet-automation`) has been deployed to your account.
6. Your service has sufficient capacity in remaining AZs to handle the workload during the 15-minute experiment duration.
7. **Task definition requirements for `inject-network-packet-loss`**: The `aws:ecs:task-network-packet-loss` action uses an SSM agent sidecar inside each task to inject faults. Without it, the action fails with `"At least one ECS Task is not registered as a SSM managed instance."` Your task definition must:
   - Set `pidMode: task` (required for the sidecar to access the task's network namespace)
   - Use `networkMode: awsvpc` (not `bridge`)
   - Set `enableFaultInjection: true` in the task definition
   - Disable ECS Exec (`enableExecuteCommand: false`) — it conflicts with the SSM agent registration
   - Include an SSM agent sidecar container that registers each task as a managed instance tagged with `ECS_TASK_ARN`
   - See [Use the AWS FIS aws:ecs:task actions](https://docs.aws.amazon.com/fis/latest/userguide/ecs-task-actions.html) for the full sidecar setup guide.
8. **Network connectivity for `inject-network-packet-loss`**: Tasks must be able to reach the ECS fault injection endpoint. For tasks in private subnets without NAT, add a VPC endpoint for `com.amazonaws.<region>.ecs-fault-injection`. The task security group must allow outbound HTTPS (port 443) to this endpoint.
9. **Task role and managed-instance role for fault injection**: The SSM agent sidecar authenticates with the ECS **task role** (not the execution role) to register each task as a managed instance. The **task role** needs:
   ```json
   {
     "Action": ["ssm:CreateActivation", "ssm:AddTagsToResource", "iam:PassRole"],
     "Resource": "*"
   }
   ```
   The **managed-instance role** (the role passed via the `MANAGED_INSTANCE_ROLE_NAME` environment variable, which the sidecar registers instances against) needs the `AmazonSSMManagedInstanceCore` managed policy attached, plus:
   ```json
   {
     "Action": ["ssm:DeleteActivation", "ssm:DeregisterManagedInstance"],
     "Resource": "*"
   }
   ```
   See [Use the AWS FIS aws:ecs:task actions](https://docs.aws.amazon.com/fis/latest/userguide/ecs-task-actions.html) for the full role setup.
10. You have updated all placeholder values (`<YOUR ...>`) in the experiment template with your actual resource identifiers.

## How It Works

This experiment simulates a complete Availability Zone impairment using a sequenced approach that mirrors real-world AZ failures. Network degradation begins first, followed by a hard task stop — making the failure more realistic and catastrophic than simply stopping tasks. The SSM automation document manages the subnet impairment lifecycle (remove → wait → restore) with built-in cleanup on cancel or failure:

### Experiment Flow

```
T+0     ┌─────────────────────────────────────────────────────────────────────┐
        │  inject-network-packet-loss (100% packet loss, 15 min)              │
        │  wait-before-stop (1 min delay)                                     │
        │  impair-subnet-in-az (SSM: remove subnet → wait → restore)         │
        └─────────────────────────────────────────────────────────────────────┘
                          │
T+~30s  SSM automation removes subnet from ECS service network config
        ECS can no longer reschedule tasks into the impaired AZ
                          │
T+1m                      ▼
        ┌─────────────────────────────────────────────────────────────────────┐
        │  stop-tasks-in-az (force stop all tasks in target AZ)               │
        └─────────────────────────────────────────────────────────────────────┘
        ECS reschedules stopped tasks into surviving subnets only ✓
                          │
T+15m                     ▼  Packet loss duration ends
T+17m                     ▼  SSM automation restores subnet
                          ▼  ECS rebalances tasks across AZs
```

**Why `impair-subnet-in-az` starts at T+0:** ECS does not evict running tasks when a subnet is removed from the service network config — only new task placements are blocked. If the subnet removal runs concurrently with or after the task stop, ECS can reschedule the just-stopped tasks back into the impaired AZ before the SSM automation has updated the service. Starting the SSM automation at T+0 ensures the subnet is fully removed (~30 seconds of SSM startup + API call) before `stop-tasks-in-az` fires at T+1m, giving ECS no healthy subnet to place replacements in for that AZ.

### Actions Detail

| Action | Action ID | Description | Starts | Duration |
|--------|-----------|-------------|--------|----------|
| `inject-network-packet-loss` | `aws:ecs:task-network-packet-loss` | Injects 100% packet loss for tasks in the target AZ | T+0 | 15 minutes |
| `wait-before-stop` | `aws:fis:wait` | Delay to let packet loss and subnet removal take effect before hard stop | T+0 | 1 minute |
| `impair-subnet-in-az` | `aws:ssm:start-automation-execution` | Removes subnet at T+0, waits for duration, then restores. Cleans up on cancel/failure. | T+0 | 40 min max |
| `stop-tasks-in-az` | `aws:ecs:stop-task` | Stops all ECS Fargate tasks running in the target AZ | T+1m | Immediate |

### SSM Automation Document

The experiment uses a single SSM Automation document (`ecs-fargate-az-impairment-subnet-automation`) that manages the complete fault lifecycle:

1. Validates input parameters (subnet ID format, cluster/service existence)
2. Retrieves current ECS service network configuration
3. Validates the subnet exists and is not the last one in the configuration
4. **Removes the subnet** from the ECS service network configuration
5. Waits for service stability (up to 10 minutes)
6. **Waits for the impairment duration** (configurable, default 15 minutes)
7. **Restores the subnet** to the ECS service configuration

Steps 4–6 have `onFailure` and `onCancel` routing to the restore step, ensuring the subnet is always restored even if the experiment is cancelled or encounters an error. The restore step is self-contained and idempotent — it re-discovers the current service configuration and skips the update if the subnet is already present.

## Targets

| Target Name | Resource Type | Selection Mode | Description |
|-------------|---------------|----------------|-------------|
| `ecs-tasks-for-stop` | `aws:ecs:task` | ALL | ECS tasks in the target AZ to be stopped |
| `ecs-tasks-for-packet-loss` | `aws:ecs:task` | ALL | ECS tasks in the target AZ to receive packet loss injection |

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

## Files in This Directory

| File | Description |
|------|-------------|
| `README.md` | This documentation file |
| `AWSFIS.json` | Template version marker for fis-template-library-tooling |
| `ecs-fargate-az-impairment-template.json` | FIS experiment template definition |
| `ecs-fargate-az-impairment-fis-role-iam-policy.json` | IAM policy for the FIS execution role |
| `ecs-fargate-az-impairment-ssm-automation-role-iam-policy.json` | IAM policy for the SSM automation role |
| `fis-iam-trust-relationship.json` | Trust policy for FIS service |
| `ssm-iam-trust-relationship.json` | Trust policy for SSM service |
| `ecs-fargate-az-impairment-subnet-automation.yaml` | SSM Automation document (remove, wait, restore with cleanup on cancel/failure) |
