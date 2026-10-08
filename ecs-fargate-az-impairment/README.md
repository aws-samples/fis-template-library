# AWS Fault Injection Service Experiment: ECS Fargate Availability Zone Impairment

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

> **Looking for the operator-response drill instead?** This template injects the AZ fault only and makes **no control-plane changes** to your ECS service. If you want to test whether your team/automation correctly detects the impairment and evacuates the AZ (removing the subnet, forcing a redeploy into healthy AZs), see the companion template: [`ecs-fargate-az-evacuation`](../ecs-fargate-az-evacuation/README.md).

## Hypothesis

When an Availability Zone experiences a network impairment affecting an ECS Fargate service, the service should detect degraded health in the affected AZ and continue operating with reduced capacity using tasks in the remaining healthy AZs. Specifically:

- When network connectivity to/from the target AZ is disrupted, tasks in that AZ should be detected as unreachable/unhealthy (via health checks, target group, or application-level signals).
- When network packet loss is injected, affected tasks should be detected as unhealthy.
- When tasks are stopped in the target AZ, ECS reschedules them to satisfy `desiredCount`.
- **This template makes no change to the ECS service's network configuration.** Because the impaired subnet remains a valid placement target for the ECS scheduler, replacement tasks may be scheduled back into the impaired AZ during the experiment window. This is expected and is part of what the experiment measures — it surfaces whether your detection signals (alarms, health checks, dashboards) correctly flag the AZ as degraded even while ECS keeps placing tasks there. If your goal is to prevent replacements from landing in the bad AZ, run the [`ecs-fargate-az-evacuation`](../ecs-fargate-az-evacuation/README.md) template instead, which removes the subnet as part of the drill.
- The application should remain available throughout the experiment with degraded but functional capacity.
- All injected faults are automatically reverted at the end of their configured duration; no manual cleanup or restoration step is required.

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment and perform ECS task actions and EC2 network ACL operations.
2. The IAM role specified in the `roleArn` field has been created with the required permissions from `ecs-fargate-az-impairment-iam-policy.json`.
3. The ECS cluster, service, and tasks all have the `FIS-Ready=True` tag, and it propagates to tasks at launch time (`propagateTags: SERVICE` or `TASK_DEFINITION` in the service definition). You can verify with:
   ```bash
   aws ecs describe-tasks --cluster <cluster> --tasks $(aws ecs list-tasks --cluster <cluster> --service-name <service> --query 'taskArns[0]' --output text) --query 'tasks[0].tags'
   ```
4. The subnet(s) in the target Availability Zone have the `FIS-Ready=True` tag (required by the `aws:network:disrupt-connectivity` target).
5. Your ECS Fargate service is configured with multiple subnets across at least 2 different Availability Zones.
6. Your service has sufficient capacity in remaining AZs to handle the workload during the 15-minute experiment duration.
7. **Task definition requirements for `inject-network-packet-loss`**: The `aws:ecs:task-network-packet-loss` action uses an SSM agent sidecar inside each task to inject faults. Without it, the action fails with `"At least one ECS Task is not registered as a SSM managed instance."` Your task definition must:
   - Set `pidMode: task` (required for the sidecar to access the task's network namespace)
   - Use `networkMode: awsvpc` (not `bridge`)
   - Set `enableFaultInjection: true` in the task definition
   - Disable ECS Exec (`enableExecuteCommand: false`) — it conflicts with the SSM agent registration
   - Include an SSM agent sidecar container that registers each task as a managed instance tagged with `ECS_TASK_ARN`
   - See [Use the AWS FIS aws:ecs:task actions](https://docs.aws.amazon.com/fis/latest/userguide/ecs-task-actions.html) for the full sidecar setup guide.
8. **Task role and managed-instance role for fault injection**: The SSM agent sidecar authenticates with the ECS **task role** (not the execution role) to register each task as a managed instance. The **task role** needs:
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
9. You have updated all placeholder values (`<YOUR ...>`) in the experiment template with your actual resource identifiers.

## How It Works

This experiment simulates an Availability Zone network impairment using **only data-plane / network-layer faults**. It makes **no API calls against the ECS service** (no `UpdateService`, no network configuration changes) — the ECS scheduler behaves exactly as it would during a real, undeclared AZ network event.

### Experiment Flow

```
T+0     ┌─────────────────────────────────────────────────────────────────────┐
        │  disrupt-az-connectivity (deny intra-VPC traffic to/from other AZs) │
        │  inject-network-packet-loss (100% packet loss, 15 min)              │
        │  wait-before-stop (1 min delay)                                     │
        └─────────────────────────────────────────────────────────────────────┘
                          │
T+1m                      ▼
        ┌─────────────────────────────────────────────────────────────────────┐
        │  stop-tasks-in-az (force stop all tasks in target AZ)               │
        └─────────────────────────────────────────────────────────────────────┘
        ECS immediately tries to satisfy desiredCount. The impaired subnet is
        still a valid placement target, so replacement tasks CAN be scheduled
        back into the bad AZ — this is expected. What you're measuring is
        whether those replacements are then detected as degraded (via
        `disrupt-az-connectivity` and packet loss) rather than whether ECS
        avoids the AZ altogether.
                          │
T+15m                     ▼  Packet loss duration ends
T+15m                     ▼  disrupt-az-connectivity duration ends, FIS restores
                             the subnet's original network ACL association automatically
```

**Why `disrupt-az-connectivity` runs for the full 15 minutes:** `aws:network:disrupt-connectivity` (`scope: availability-zone`) works by temporarily cloning the subnet's network ACL, adding deny rules for intra-VPC traffic to/from other AZs, and associating the clone with the subnet — a purely network-layer, non-invasive fault. FIS automatically restores the original network ACL association when the action's duration elapses; no cleanup step is required. This is what makes any task placed in that AZ (old or freshly replaced) observably unreachable from the rest of the VPC for the duration of the experiment, independent of whatever ECS does with task placement.

### Actions Detail

| Action | Action ID | Description | Starts | Duration |
|--------|-----------|-------------|--------|----------|
| `disrupt-az-connectivity` | `aws:network:disrupt-connectivity` | Denies intra-VPC traffic to/from the target AZ's subnet, simulating an AZ network partition. Auto-restored by FIS at the end of duration. | T+0 | 15 minutes |
| `inject-network-packet-loss` | `aws:ecs:task-network-packet-loss` | Injects 100% packet loss for tasks in the target AZ | T+0 | 15 minutes |
| `wait-before-stop` | `aws:fis:wait` | Delay to let the network disruption and packet loss take effect before hard stop | T+0 | 1 minute |
| `stop-tasks-in-az` | `aws:ecs:stop-task` | Stops all ECS Fargate tasks running in the target AZ | T+1m | Immediate |

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

> **Note on the `LastStatus=RUNNING` task filter:** both task targets filter on
> `LastStatus=RUNNING` in addition to the Availability Zone. This is required for
> reliability: ECS keeps STOPPED tasks queryable (and tagged `FIS-Ready=True`) for
> up to ~1 hour after they stop, and FIS resolves `aws:ecs:task` targets from the
> tagging API + `DescribeTasks`. Without the `LastStatus` filter, tasks stopped by
> a previous experiment run are still matched by tag + AZ, and the
> `aws:ecs:task-network-packet-loss` action then fails its SSM-managed-instance
> validation against those dead tasks' sidecars
> (`"At least one ECS Task is not registered as a SSM managed instance"`). The
> filter scopes resolution to live tasks so repeated runs stay reliable.

## Parameters to Configure

Before running the experiment, update these placeholder values:

| Placeholder | Description |
|-------------|-------------|
| `<YOUR AWS ACCOUNT>` | Your 12-digit AWS account ID |
| `<YOUR REGION>` | AWS region where resources are deployed |
| `<YOUR ROLE NAME>` | FIS execution IAM role name |
| `<YOUR TARGET AZ>` | Availability Zone to impair |

> Targeting is by the `FIS-Ready=True` tag and Availability Zone only -- there is
> no explicit ECS cluster/service field to configure. Ensure the tag is applied
> (and propagated to tasks) only on the cluster/service/subnets you intend to
> target; see Prerequisites above.

## Stop Conditions

The experiment does not have any specific stop conditions defined by default. It will continue to run until manually stopped or until all actions complete successfully (approximately 15-16 minutes total).

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

> **Note:** The experiment uses `emptyTargetResolutionMode: "skip"` because tasks may not exist in the target Availability Zone if the service hasn't scheduled tasks there yet. This prevents the experiment from failing when no tasks match the AZ filter at the time of execution.

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
5. **Running a real end-to-end test in a non-production environment before trusting this template's documented behavior.** Confirm with your own service that: replacement tasks placed in the impaired AZ during the window are actually observed as unreachable by your health checks/alarms, and that packet loss + connectivity disruption are both cleanly reverted at T+15m with no lingering network ACL association.
6. Adjusting the experiment duration (default 15 minutes) based on your testing requirements and recovery time objectives.
7. Once you've validated detection behavior with this template, consider running [`ecs-fargate-az-evacuation`](../ecs-fargate-az-evacuation/README.md) to test whether your operational response (automated or manual) correctly evacuates the AZ.
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
| `ecs-fargate-az-impairment-iam-policy.json` | IAM policy for the FIS execution role |
| `fis-iam-trust-relationship.json` | Trust policy for FIS service |
