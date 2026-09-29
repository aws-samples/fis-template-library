# AWS Fault Injection Service Experiment: ECS Fargate Availability Zone Evacuation

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE

> **Looking for the fault-only experiment instead?** This template deliberately makes a **control-plane change** (it removes the impaired AZ's subnet from your ECS service) to drill the evacuation response, and that change forces a full rolling redeployment of the service — by design, see the Hypothesis below. If you only want to inject the AZ fault and observe detection behavior without any control-plane change, see the companion template: [`ecs-fargate-az-impairment`](../ecs-fargate-az-impairment/README.md).

## Hypothesis

This experiment drills the **operator's (or automation's) response** to a detected AZ impairment, not just the fault itself. It answers: "once we decide to evacuate the AZ, does the system converge correctly and safely?"

**The redeploy is expected and is what this experiment measures — it is not a side effect to avoid.** Removing the subnet from the ECS service's network configuration triggers ECS to start a new rolling deployment, which cycles every task in the service (not only those in the impaired AZ) onto the updated network configuration. Specifically, we expect:

- After the fault is injected and a detection delay elapses, removing the impaired AZ's subnet causes ECS to start a new service deployment.
- **All tasks — including those already running in healthy AZs — are cycled as part of this deployment**, because the network configuration for the service changed. This is normal ECS deployment behavior, not a bug in the evacuation step.
- Within **X minutes** of the subnet removal (target: within the deployment's configured `minimumHealthyPercent`/`maximumPercent` rollout window — set your own target and verify it empirically), all running tasks are located in the remaining healthy AZs.
- Throughout the evacuation, the service does not breach its configured `minimumHealthyPercent` (i.e., you never drop below the minimum number of healthy tasks), and no SLO/business-metric alarms fire.
- When the evacuation window ends, the subnet is automatically restored and the service naturally rebalances tasks back across all AZs on its next deployment.

If your goal is only to inject the fault and check detection without forcing this redeploy, use [`ecs-fargate-az-impairment`](../ecs-fargate-az-impairment/README.md) instead.

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment and perform ECS task actions, ECS service updates, SSM automation executions, and EC2 network operations.
2. The IAM roles have been created with the required permissions from `ecs-fargate-az-evacuation-fis-role-iam-policy.json` (FIS execution role) and `ecs-fargate-az-evacuation-ssm-automation-role-iam-policy.json` (SSM automation role).
3. The ECS cluster, **service**, and tasks all have the `FIS-Ready=True` tag. The service must be tagged directly (required by the SSM automation role policy — `ecs:DescribeServices` and `ecs:UpdateService` are conditioned on `aws:ResourceTag/FIS-Ready: True`; an untagged service causes AccessDenied at the first automation step before any subnet is removed). Tags must also propagate to tasks at launch time (`propagateTags: SERVICE` or `TASK_DEFINITION` in the service definition). You can verify with:
   ```bash
   aws ecs describe-tasks --cluster <cluster> --tasks $(aws ecs list-tasks --cluster <cluster> --service-name <service> --query 'taskArns[0]' --output text) --query 'tasks[0].tags'
   ```
4. The subnet(s) in the target Availability Zone have the `FIS-Ready=True` tag (required by the `aws:network:disrupt-connectivity` target).
5. Your ECS Fargate service is configured with multiple subnets across at least 2 different Availability Zones (minimum 2 subnets required — the automation cannot remove the last subnet).
6. The SSM automation document (`ecs-fargate-az-evacuation-subnet-automation`) has been deployed to your account.
7. Your service has sufficient capacity in remaining AZs to absorb the full-service redeploy, not just the tasks from the impaired AZ, during the ~20-minute experiment duration.
8. **Task definition requirements for `inject-network-packet-loss`**: see the [`ecs-fargate-az-impairment` prerequisites](../ecs-fargate-az-impairment/README.md#prerequisites) for the SSM sidecar, task role, and managed-instance role setup — identical requirements apply here.
9. You have updated all placeholder values (`<YOUR ...>`) in the experiment template with your actual resource identifiers.

## How It Works

This experiment sequences two distinct phases: **inject the fault**, then — after a detection delay — **evacuate the AZ**. This mirrors a real incident: the impairment happens first and is detected over some interval, then someone (or some automation) makes the call to evacuate.

### Experiment Flow

```
T+0     ┌─────────────────────────────────────────────────────────────────────┐
        │  disrupt-az-connectivity (deny intra-VPC traffic to/from other AZs) │
        │  inject-network-packet-loss (100% packet loss, 20 min)              │
        │  wait-before-stop (1 min delay)                                     │
        └─────────────────────────────────────────────────────────────────────┘
                          │
T+1m                      ▼
        ┌─────────────────────────────────────────────────────────────────────┐
        │  stop-tasks-in-az (force stop all tasks in target AZ)               │
        └─────────────────────────────────────────────────────────────────────┘
        ECS reschedules replacements. Since the subnet has not been removed
        yet, replacements CAN still land back in the impaired AZ — the fault
        (packet loss + connectivity disruption) keeps them observably degraded.
                          │
T+1m                      ▼
        ┌─────────────────────────────────────────────────────────────────────┐
        │  wait-for-detection (default 4 min — simulates alarm/operator      │
        │  detection + decision time; tune to your real detection SLA)       │
        └─────────────────────────────────────────────────────────────────────┘
                          │
T+5m                      ▼
        ┌─────────────────────────────────────────────────────────────────────┐
        │  evacuate-subnet-in-az (SSM: remove subnet → wait → restore)       │
        └─────────────────────────────────────────────────────────────────────┘
        Removing the subnet triggers a new ECS service deployment, which
        cycles ALL tasks (every AZ), not only those in the impaired AZ — this
        is expected. Measure: does every task end up in a healthy AZ within
        your target window, without breaching minimumHealthyPercent or firing
        SLO alarms?
                          │
T+20m                     ▼  Packet loss and connectivity disruption end
T+~20m                    ▼  Evacuation window ends, SSM automation restores
                             the subnet; service naturally rebalances on its
                             next deployment
```

### Actions Detail

| Action | Action ID | Description | Starts | Duration |
|--------|-----------|-------------|--------|----------|
| `disrupt-az-connectivity` | `aws:network:disrupt-connectivity` | Denies intra-VPC traffic to/from the target AZ's subnet | T+0 | 20 minutes |
| `inject-network-packet-loss` | `aws:ecs:task-network-packet-loss` | Injects 100% packet loss for tasks in the target AZ | T+0 | 20 minutes |
| `wait-before-stop` | `aws:fis:wait` | Delay to let the fault take effect before hard stop | T+0 | 1 minute |
| `stop-tasks-in-az` | `aws:ecs:stop-task` | Stops all ECS Fargate tasks running in the target AZ | T+1m | Immediate |
| `wait-for-detection` | `aws:fis:wait` | Simulated detection/decision delay before evacuation begins | T+1m | 4 minutes (default — tune to your SLA) |
| `evacuate-subnet-in-az` | `aws:ssm:start-automation-execution` | Removes the subnet at T+5m, forcing evacuation; restores it after the evacuation window. Handles cleanup on cancel/failure. | T+5m | 40 min max |

### SSM Automation Document

The experiment uses a single SSM Automation document (`ecs-fargate-az-evacuation-subnet-automation`) that manages the complete evacuation lifecycle:

1. Validates input parameters (subnet ID format, cluster/service existence)
2. Retrieves current ECS service network configuration
3. Validates the subnet exists and is not the last one in the configuration
4. **Removes the subnet** from the ECS service network configuration — this is the evacuation trigger
5. Waits for service stability (up to 10 minutes) — this is where the full-service redeploy plays out
6. **Waits for the evacuation duration** (configurable, default 15 minutes)
7. **Restores the subnet** to the ECS service configuration

Steps 4–6 have `onFailure` and `onCancel` routing to the restore step, ensuring the subnet is always restored even if the experiment is cancelled or encounters an error. The restore step is self-contained and idempotent — it re-discovers the current service configuration and skips the update if the subnet is already present.

## Targets

| Target Name | Resource Type | Selection Mode | Description |
|-------------|---------------|----------------|-------------|
| `subnet-in-az` | `aws:ec2:subnet` | ALL | Subnet(s) in the target AZ to disrupt connectivity for |
| `ecs-tasks-for-stop` | `aws:ecs:task` | ALL | ECS tasks in the target AZ to be stopped |
| `ecs-tasks-for-packet-loss` | `aws:ecs:task` | ALL | ECS tasks in the target AZ to receive packet loss injection |

### Target Requirements
- Subnets and tasks must have the `FIS-Ready=True` tag
- Tasks must be running in the specified ECS cluster and service
- Subnets and tasks must be in the target Availability Zone

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
| `<YOUR SUBNET ID>` | Subnet ID to remove/restore during evacuation |
| `<YOUR TARGET AZ>` | Availability Zone to impair and evacuate |

## Stop Conditions

The experiment does not have any specific stop conditions defined by default. It will continue to run until manually stopped or until all actions complete successfully (approximately 20-25 minutes total).

> **Note:** The experiment uses `emptyTargetResolutionMode: "skip"` because tasks may not exist in the target Availability Zone if the service hasn't scheduled tasks there yet. This prevents the experiment from failing when no tasks match the AZ filter at the time of execution.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

### Recommended Metrics for Stop Conditions

Consider creating CloudWatch alarms for these metrics:

- **ECS Service Metrics**
  - `CPUUtilization` - Alert if remaining tasks are overloaded
  - `MemoryUtilization` - Alert if memory pressure increases
  - `RunningTaskCount` - Alert if task count drops below minimum threshold
  - **Deployment-in-progress alerts** — since the evacuation itself forces a rolling deployment, consider alarming on deployment duration or rollback events, not just steady-state metrics.

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
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of AZ evacuation on service availability.
4. Adding a stop condition tied to the alarm to automatically halt the experiment if critical thresholds are breached.
5. **Running a real end-to-end test in a non-production environment before trusting this template's documented behavior.** Confirm with your own service: how long the forced redeploy actually takes to converge, whether `minimumHealthyPercent`/`maximumPercent` on your deployment configuration are set to values that keep you within SLO during the evacuation, and that the subnet is reliably restored (and the service rebalances) at the end of the evacuation window.
6. Tuning `wait-for-detection` to match your actual alerting/operator response SLA, and setting a concrete "X minutes" target for full evacuation based on your service's deployment configuration.
7. Adjusting the experiment duration and evacuation window based on your testing requirements and recovery time objectives.
8. Documenting the expected behavior and actual results to build a runbook for real AZ evacuations.
9. Gradually increasing the scope of the experiment (e.g., longer duration, multiple services) as confidence grows.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).

## Files in This Directory

| File | Description |
|------|-------------|
| `README.md` | This documentation file |
| `AWSFIS.json` | Template version marker for fis-template-library-tooling |
| `ecs-fargate-az-evacuation-template.json` | FIS experiment template definition |
| `ecs-fargate-az-evacuation-fis-role-iam-policy.json` | IAM policy for the FIS execution role |
| `ecs-fargate-az-evacuation-ssm-automation-role-iam-policy.json` | IAM policy for the SSM automation role |
| `fis-iam-trust-relationship.json` | Trust policy for FIS service |
| `ssm-iam-trust-relationship.json` | Trust policy for SSM service |
| `ecs-fargate-az-evacuation-subnet-automation.yaml` | SSM Automation document (remove, wait, restore with cleanup on cancel/failure) |
