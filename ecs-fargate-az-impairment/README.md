# AWS Fault Injection Service Experiment: ECS Fargate Availability Zone Impairment

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

If the ECS tasks running in the target Availability Zone get 100% egress packet loss for a minute and are then stopped, while the target Availability Zone's subnets are cut off from the other Availability Zones for 15 minutes, the share of failed requests that your service's clients see should not exceed `<YOUR ERROR THRESHOLD>` in any minute of the experiment, and your alarms or dashboards should flag the target Availability Zone as impaired within `<YOUR DETECTION TIME>` of the start.

- **What to measure.** The failed-request rate on the path your users take, for example `HTTPCode_ELB_5XX_Count` plus `HTTPCode_Target_5XX_Count` divided by `RequestCount` for an Application Load Balancer, or the error rate a client in another Availability Zone logs. Look at the target Availability Zone's tasks as well as the total, because a total can hide tasks that answer nothing.
- **What proves it false.** The failed-request rate goes above your threshold in any minute, or nothing flags the target Availability Zone within your detection time.
- **What the target needs for the fault to matter.** The service runs tasks in at least two Availability Zones, has enough capacity outside the target Availability Zone to carry the load, and its clients reach it across Availability Zones. The network fault only denies traffic between subnets in different Availability Zones of the same VPC (see [What else is affected](#what-else-is-affected)). A client, or a load balancer node, in the target Availability Zone itself can still reach the tasks there, so with that path the hypothesis can hold even though nothing detected the impairment. Behind a load balancer, the target group must also keep each target in service while the packet loss lasts, 1 minute by default. The load balancer takes a target out of service after the unhealthy threshold of failed health checks in a row, one health-check interval apart ([target group health checks](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/target-group-health-checks.html)): about the interval times the threshold after the loss starts, and as little as one interval sooner. If that is shorter than the packet loss, ECS replaces the targets during it, and FIS can report packet loss that ECS cut short (see [What else is affected](#what-else-is-affected)). A target group that slow wasn't tested.
- **What ECS does.** ECS replaces the stopped tasks to keep `desiredCount`. The impaired subnet stays a valid placement target, so replacements can start in the target Availability Zone. They get no packet loss (only the tasks running at the start do), but the network fault cuts them off from the other Availability Zones until it ends. Behind a load balancer, ECS can start the replacements during the first minute, while the targets fail their health checks: in the test, 28 to 71 seconds after the start. If you want replacements kept out of the impaired AZ, run [`ecs-fargate-az-evacuation`](../ecs-fargate-az-evacuation/README.md) instead.
- **What the test saw.** In the runs with the shipped durations that put packet loss on targets behind the load balancer, other than second runs started during a first one, a client in another Availability Zone, sending 5 requests a second through an internal Application Load Balancer with 2-second timeouts, saw 8 to 24 failed requests of about 300 in the first minute, while the packet loss lasted. In the minutes after, it saw none, except 9 to 12 failed requests in the second minute of four of those runs. In one of them, the load balancer was still sending requests to a replacement that ECS had started in the target Availability Zone, which the network fault had cut off at T+1m. The target group checked health every 5 seconds and took a target out of service after 2 failed checks.

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment and perform ECS task actions and EC2 network ACL operations.
2. The IAM role specified in the `roleArn` field has been created with the permissions in `ecs-fargate-az-impairment-iam-policy.json` and the trust policy in `fis-iam-trust-relationship.json`, with the placeholders in both filled in.
3. The ECS tasks you want to target have the `FIS-Ready=True` tag. The simplest way is to tag the service and set `propagateTags: SERVICE` (or tag the task definition and set `propagateTags: TASK_DEFINITION`), so every task gets the tag at launch. You can check one task with:
   ```bash
   aws ecs describe-tasks --cluster <cluster> --include TAGS --tasks $(aws ecs list-tasks --cluster <cluster> --service-name <service> --query 'taskArns[0]' --output text) --query 'tasks[0].tags'
   ```
4. The subnet(s) in the target Availability Zone have the `FIS-Ready=True` tag. Keep the tag on them until the experiment has ended: the role can put the subnet's original network ACL back only while the subnet has the tag. All the tagged subnets in the target Availability Zone must be in one VPC. In the test, with tagged subnets in two VPCs, `disrupt-az-connectivity` failed at T+73 seconds ("Target subnets must belong to the same VPC."), after the packet loss had run and the tasks had been stopped, and no network ACL changed; the target preview in [What else is affected](#what-else-is-affected) selected the subnets in both VPCs and gave no warning. List the tagged subnets in the Availability Zone with their VPCs:
   ```bash
   aws ec2 describe-subnets --filters Name=tag:FIS-Ready,Values=True Name=availability-zone,Values=<YOUR TARGET AZ> --query 'Subnets[].{subnet:SubnetId,vpc:VpcId}'
   ```
5. At the start of the experiment, the target Availability Zone has at least one `FIS-Ready=True` subnet and at least one running `FIS-Ready=True` task. If either is missing, the experiment fails before it changes anything. Tagged subnets in more than one VPC (Prerequisite 4), and a network ACL without room for FIS's deny entries (Prerequisite 6), fail it later, at T+1m, after the packet loss and the task stop.
6. **Network ACL limits of `disrupt-az-connectivity`.** The [actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html#disrupt-connectivity) says that with a scope other than `all`, "the maximum number of entries in network ACLs is 20", and that with `availability-zone` "the maximum number of subnets that can be targeted in a VPC is 30". In the test, FIS's copy of a subnet's network ACL held the original's entries plus, in each direction, one deny entry for each of the VPC's subnets in another Availability Zone. FIS refused the network fault when a direction's count from the first command below, which includes the default `*` entry, plus those deny entries came to more than 20, and ran it when they came to exactly 20. So for each target subnet, each direction's count plus the number of the VPC's subnets in other Availability Zones must be 20 or less, and no VPC may have more than 30 `FIS-Ready=True` subnets in the target Availability Zone. FIS checks the entries only when `disrupt-az-connectivity` starts: over the limit, the experiment failed at T+72 seconds, after the packet loss and the task stop, with `QuotaExceededFailure` ("The maximum number of Single Network ACL entries has been reached. Max: 20"), and no network ACL changed. Count a subnet's entries in each direction, and the VPC's subnets in other Availability Zones, with:
   ```bash
   aws ec2 describe-network-acls --filters Name=association.subnet-id,Values=<subnet-id> --query 'NetworkAcls[0].{inbound:length(Entries[?Egress==`false`]),outbound:length(Entries[?Egress==`true`])}'
   aws ec2 describe-subnets --filters Name=vpc-id,Values=<vpc-id> --query "length(Subnets[?AvailabilityZone!='<YOUR TARGET AZ>'])"
   ```
   The limit was tested for inbound entries, in a VPC with two subnets in other Availability Zones and an account quota of 20 rules per network ACL. A network ACL with only the default entries is safest.
7. Your ECS service uses subnets in at least two Availability Zones, and has enough capacity outside the target Availability Zone to carry the load for the 16 minutes of the experiment.
8. **Task definition requirements for `inject-network-packet-loss`.** The `aws:ecs:task-network-packet-loss` action runs the AWS-owned SSM document `AWSFIS-Run-Network-Packet-Loss-ECS` through an SSM Agent sidecar container in each task, so each task must be registered as an SSM managed instance. Your task definition must:
   - Set `pidMode: task`.
   - Set `enableFaultInjection: true`.
   - Not enable ECS Exec (`enableExecuteCommand: false` on the service).
   - Include the SSM Agent sidecar container from the FIS guide, which registers each task as a managed instance tagged with `ECS_TASK_ARN` and `FAULT_INJECTION_SIDECAR=true`. The IAM policy lets the FIS role send commands only to managed instances with the `FAULT_INJECTION_SIDECAR=true` tag.
   - Use a sidecar image that already has the packet-loss document's dependencies. The [actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html#task-network-packet-loss) lists atd, curl-minimal, dig, jq and lsof; in the test, the document itself checked for `setsid`, `curl`, `dig`, `jq`, `lsof` and `pgrep`. These are the tools, not package names. The template sets `installDependencies` to `false`, so a cold install can't use up the 1-minute packet-loss window. The FIS guide says its non-root SSM Agent image "has the required fault injection dependencies pre-installed" ([Use the AWS FIS aws:ecs:task actions](https://docs.aws.amazon.com/fis/latest/userguide/ecs-task-actions.html)); its image URIs are under [non-root container images](https://docs.aws.amazon.com/fis/latest/userguide/ecs-task-actions.html#ecs-task-container-images). The guide's root image script installs packages with `dnf`. If you use it on an Amazon Linux 2023 base, add `at curl-minimal bind-utils jq lsof` to its `dnf install` command: the [Amazon Linux 2023 package list](https://docs.aws.amazon.com/linux/al2023/release-notes/all-packages-AL2023.12.html) has packages with these names and none named `atd` or `dig`, and the Fedora [`at`](https://packages.fedoraproject.org/pkgs/at/at/fedora-rawhide.html) and [`bind-utils`](https://packages.fedoraproject.org/pkgs/bind/bind-utils/fedora-rawhide.html) packages ship `atd` and `dig`. Check the base with `cat /etc/os-release` in the image, and use your distribution's package names on any other base. The guide's script starts with `set -e`, so if `dnf` fails on a name it can't find, the sidecar stops before it registers the task. In the test, the root image on Amazon Linux 2023 with these packages added had every dependency. Without them the packet-loss document failed with "Missing dependencies detected with InstallDependencies set to false", and the experiment failed before any network ACL changed or any task was stopped. At the time of the test the guide's non-root image URIs for `ap-southeast-1` and `ap-southeast-2` didn't resolve (`CannotPullContainerError ... not found`). The FIS non-root image from the ECR Public Gallery, `public.ecr.aws/aws-fis/aws-fis-ssm-agent-non-root:latest`, ran in `ap-southeast-1`, and every first command found its dependencies installed. With the non-root image, give the task role the grants for its cleanup in Prerequisite 10.
   - Run on a platform whose Amazon ECS agent is version 1.88.0 or later: "Amazon ECS Agent `version 1.88.0+` is required to use the fault injection endpoints" ([fault injection endpoints](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fault-injection-endpoints.html)). On Fargate the agent comes with the platform version, and the ECS documentation doesn't say which platform version carries 1.88.0; the tested platform version is in Tested configuration below. ECS on EC2 capacity isn't tested.
   - See [Use the AWS FIS aws:ecs:task actions](https://docs.aws.amazon.com/fis/latest/userguide/ecs-task-actions.html) for the full sidecar setup.
9. **Every target task registered and online at the start.** FIS maps each target task to the managed instance whose `ECS_TASK_ARN` tag holds the task's ARN ([Use the AWS FIS aws:ecs:task actions](https://docs.aws.amazon.com/fis/latest/userguide/ecs-task-actions.html)). The guide's root-image script registers a task only after it has run `dnf upgrade`, `dnf install`, `create-activation` and `amazon-ssm-agent -register`, so with that script a task is `RUNNING`, and can be selected, for a while before it has a managed instance. (The FIS non-root image registered each of three new tasks 8 to 17 seconds before the task was `RUNNING`.) A sidecar container that crashed (it is `essential: false`) can leave a registered managed instance that is no longer online. If a target task has no managed instance when the experiment starts, FIS fails `inject-network-packet-loss`, and with it the experiment, before any command is sent ("At least one ECS Task is not registered as a SSM managed instance"): the documentation doesn't say so, but the test showed it for two root-image tasks that were `RUNNING` but not yet registered, one of them started 7 seconds before the experiment, and for a task whose sidecar never registered; none of these runs stopped a task or changed a network ACL. If a target task's managed instance is registered but offline, FIS sends it the commands anyway, and they can't be delivered: in the test that target never lost a packet, and the action and the experiment ended `completed`. So start the experiment only when every running `FIS-Ready=True` task in the target Availability Zone has an online managed instance, for example not right after a deployment, a scale-out or an earlier run of this experiment. Check it, for each cluster that has tagged tasks (up to 100 running tasks per cluster, the `DescribeTasks` limit), with:
   ```bash
   CLUSTER=<cluster>; AZ=<YOUR TARGET AZ>
   for t in $(aws ecs describe-tasks --cluster "$CLUSTER" --include TAGS \
       --tasks $(aws ecs list-tasks --cluster "$CLUSTER" --desired-status RUNNING --query 'taskArns' --output text) \
       --query "tasks[?availabilityZone=='$AZ' && lastStatus=='RUNNING' && tags[?key=='FIS-Ready' && value=='True']].taskArn" --output text); do
     echo "$t $(aws ssm describe-instance-information --filters "Key=tag:ECS_TASK_ARN,Values=$t" --query "length(InstanceInformationList[?PingStatus=='Online'])" --output text)"
   done
   ```
   Every line must end in `1`. A line that ends in `0` is a task FIS would select with no online managed instance: wait for its sidecar to register, or stop that task, and check again. No line at all means the cluster has no running tagged task in the Availability Zone. The check lists tasks whose desired status is `RUNNING`, but FIS selects by last status, so it can also select a task that ECS has begun to stop, which the check doesn't list: don't start the experiment while ECS is stopping tasks in the Availability Zone. After the run, check that each task got the packet loss as [How It Works](#how-it-works) step 2 describes.
10. **Task role and managed-instance role for fault injection.** The SSM Agent sidecar uses the ECS **task role** (not the execution role) to register each task as a managed instance. The **task role** needs:
   ```json
   [
     {
       "Effect": "Allow",
       "Action": ["ssm:CreateActivation", "ssm:AddTagsToResource"],
       "Resource": "*"
     },
     {
       "Effect": "Allow",
       "Action": "iam:PassRole",
       "Resource": "arn:aws:iam::<YOUR AWS ACCOUNT>:role/<YOUR MANAGED INSTANCE ROLE NAME>",
       "Condition": {
         "StringEquals": {
           "iam:PassedToService": "ssm.amazonaws.com"
         }
       }
     }
   ]
   ```
   `ssm:CreateActivation` has no resource type in the [Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_awssystemsmanager.html), so it can only be granted on `*`. The FIS guide doesn't say which resource the sidecar's `ssm:AddTagsToResource` call is authorized against, so this README doesn't narrow it, and code that runs in the task can tag SSM resources in the account, including the sidecars' managed instances: by rewriting a managed instance's `ECS_TASK_ARN` tag, it can make FIS send the packet loss to a task FIS didn't select.
   The **managed-instance role** (the role named in the sidecar's `MANAGED_INSTANCE_ROLE_NAME` environment variable) needs the `AmazonSSMManagedInstanceCore` managed policy attached, plus:
   ```json
   {
     "Effect": "Allow",
     "Action": ["ssm:DeleteActivation", "ssm:DeregisterManagedInstance"],
     "Resource": "*"
   }
   ```
   This is the FIS guide's grant. With the guide's root-image script, the sidecar made these two calls when its task stopped, and in the test no managed instance or activation was left. The Service Authorization Reference lists `managed-instance` as the resource of `ssm:DeregisterManagedInstance`, with the `ssm:resourceTag/tag-key` condition key, so it could be limited to managed instances tagged `FAULT_INJECTION_SIDECAR=true`; that narrower grant isn't tested on this role, so this README doesn't give it here. `ssm:DeleteActivation` has no resource type there.
   **With the FIS non-root image**, the sidecar's stop handler runs `aws ssm delete-activation` and `aws ssm deregister-managed-instance` as the image's `ssmagent` user, with the **task role**, so the task role also needs:
   ```json
   [
     {
       "Effect": "Allow",
       "Action": "ssm:DeleteActivation",
       "Resource": "*"
     },
     {
       "Effect": "Allow",
       "Action": "ssm:DeregisterManagedInstance",
       "Resource": "arn:aws:ssm:<YOUR REGION>:<YOUR AWS ACCOUNT>:managed-instance/*",
       "Condition": {
         "StringEquals": {
           "ssm:resourceTag/FAULT_INJECTION_SIDECAR": "true"
         }
       }
     }
   ]
   ```
   `ssm:DeleteActivation` has no resource type, so it can only be granted on `*`: code that runs in the task can delete any activation in the account. With `ssm:AddTagsToResource` on `*`, it can also tag any managed instance `FAULT_INJECTION_SIDECAR=true` and deregister it. In the test, with these two grants, the sidecars of the stopped tasks deregistered their managed instances and deleted their activations, and nothing was left. Without them, both calls were denied for every task whose non-root sidecar was still running when the task stopped: each such task left its managed instance, `Online` at first and later `ConnectionLost`, and its activation. To remove them, list the sidecars' managed instances with their activations and read each one's task. For each task that has stopped (`describe-tasks` prints `STOPPED`, or nothing once ECS no longer returns the task), deregister the managed instance and delete its activation:
   ```bash
   aws ssm describe-instance-information --filters Key=tag:FAULT_INJECTION_SIDECAR,Values=true --query 'InstanceInformationList[].[InstanceId,ActivationId,PingStatus]' --output text
   aws ssm list-tags-for-resource --resource-type ManagedInstance --resource-id <mi-ID> --query "TagList[?Key=='ECS_TASK_ARN'].Value" --output text
   aws ecs describe-tasks --cluster <cluster> --tasks <task ARN> --query 'tasks[].lastStatus' --output text
   aws ssm deregister-managed-instance --instance-id <mi-ID>
   aws ssm delete-activation --activation-id <activation-ID>
   ```
   See [Use the AWS FIS aws:ecs:task actions](https://docs.aws.amazon.com/fis/latest/userguide/ecs-task-actions.html) for the full role setup.
11. The target subnets hold only resources you are willing to cut off from the other Availability Zones (see [What else is affected](#what-else-is-affected)). A subnet dedicated to the service under test is safest.
12. You have updated all placeholder values (`<YOUR ...>`) in the experiment template, the IAM policy, the trust policy and the task role policy.
13. Tested configuration: `ap-southeast-2`, `ap-southeast-1`, `ca-central-1` and `ap-northeast-1`; Fargate platform version `LATEST`, which resolved to `1.4.0`; services behind an internal Application Load Balancer (up to three target tasks per run) whose target group checked health every 5 seconds and took a target out of service after 2 failed checks, with the service's `availabilityZoneRebalancing` `ENABLED` except in the run with `maximumPercent` 100. Sidecars: the root SSM Agent image `public.ecr.aws/amazon-ssm-agent/amazon-ssm-agent:latest` on Amazon Linux 2023 with the packages above in three Regions, and the FIS non-root image from the ECR Public Gallery in `ap-southeast-1`. In `eu-west-2`, with the same load balancer settings: a normal run with the non-root image and the task-role grants in Prerequisite 10, the removal commands in Prerequisite 10 for a stopped task whose role had only the FIS guide's grants, and a run with the root image and the packages above, started while a new task had no managed instance yet. Where the test recorded the SSM Agent version, it was 3.3.5700.0.

## How It Works

This experiment simulates an Availability Zone network impairment with network faults and task stops only. It makes **no call that changes the ECS service** (no `UpdateService`, no network configuration change), so the ECS scheduler behaves as it would during a real, undeclared AZ network event.

### Experiment Flow

```
T+0     ┌─────────────────────────────────────────────────────────────────────┐
        │  inject-network-packet-loss (100% egress packet loss, 1 min)        │
        │  wait-before-stop (1 min)                                           │
        └─────────────────────────────────────────────────────────────────────┘
        Behind a load balancer the targets fail their health checks, and
        ECS may start replacements, and stop targets, before T+1m.
                          │
T+1m                      ▼  inject-network-packet-loss and wait-before-stop end
        ┌─────────────────────────────────────────────────────────────────────┐
        │  stop-tasks-in-az (stop the tasks that were running at T+0)         │
        │  disrupt-az-connectivity (deny intra-VPC traffic to/from other AZs, │
        │                           15 min)                                   │
        └─────────────────────────────────────────────────────────────────────┘
        ECS starts replacement tasks to satisfy desiredCount, if it hasn't
        already. The impaired subnet is still a valid placement target, so
        replacements can start in the target AZ. They get no packet loss;
        disrupt-az-connectivity alone cuts them off from the other AZs.
                          │
T+16m                     ▼  disrupt-az-connectivity ends: FIS puts the subnet's
                             original network ACL back and deletes its copy
```

Step by step:

1. **Target selection.** At the start, FIS picks every subnet with the `FIS-Ready=True` tag in the target Availability Zone, in any VPC, and every task with the `FIS-Ready=True` tag that is in the target Availability Zone and has `LastStatus` `RUNNING`, in any cluster in the account and Region. FIS keeps these targets for the whole experiment ([Targets for AWS FIS](https://docs.aws.amazon.com/fis/latest/userguide/targets.html)), so tasks that start later are never targets. If any of the three targets is empty, the experiment fails before any action starts (`emptyTargetResolutionMode: fail`). FIS finds subnets in more than one VPC, and a network ACL without room for its entries, only when `disrupt-az-connectivity` starts (Prerequisites 4 and 6).
2. **`inject-network-packet-loss`** (T+0 to T+1m). FIS runs `AWSFIS-Run-Network-Packet-Loss-ECS` through each target task's SSM Agent sidecar, which uses the ECS fault injection endpoints to drop 100% of the task's egress IPv4 packets ([actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html#task-network-packet-loss)), except to the ECS agent endpoint `169.254.170.2` and the IP addresses of the Region's SSM endpoints. The document passes those as `SourcesToFilter`, the destinations "protected from the fault" ([fault injection endpoints](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fault-injection-endpoints.html)); in the test, the first command's output listed them on every target where it started the packet loss. It runs before the network fault, so the command reaches the sidecar over the task's normal network paths, and with `installDependencies` `false` it installs nothing first. It takes some time for the SSM document to start, so the packet loss lasts up to 1 minute, less the start time ([limitations](https://docs.aws.amazon.com/fis/latest/userguide/ecs-task-actions.html#ecs-task-limitations)). FIS uses the action's duration as the document's duration too, and sets the action to Completed if the document is still running when the duration ends ([SSM documents with FIS](https://docs.aws.amazon.com/fis/latest/userguide/actions-ssm-agent.html)). So the action can end Completed for a target that got no packet loss, or less than the minute: in the test, a target whose sidecar was offline never lost a packet, and targets that ECS stopped early lost less (see [What else is affected](#what-else-is-affected)), while the action ended `completed`. And if one target's command fails, FIS fails the action and the experiment without cancelling the command on the other targets: in one test run, another target's packet loss went on for 27 to 42 seconds after the experiment had ended (15-second probes), until the document's minute ran out. To see which tasks got the packet loss, check after the run. List the run's commands and take the first one, the earliest `requested`; list the managed instances it went to; and read each one's fault step:
   ```bash
   aws ssm list-commands --filters key=DocumentName,value=arn:aws:ssm:<YOUR REGION>::document/AWSFIS-Run-Network-Packet-Loss-ECS key=InvokedAfter,value=<experiment start time, e.g. 2026-01-31T10:00:00Z> --query 'Commands[].{id:CommandId,requested:RequestedDateTime,status:Status,targets:TargetCount}'
   aws ssm list-command-invocations --command-id <first command ID> --details --query 'CommandInvocations[].{instance:InstanceId,status:Status,detail:StatusDetails}'
   aws ssm get-command-invocation --command-id <first command ID> --instance-id <mi-ID> --plugin-name FaultInjection --query 'StandardOutputContent' --output text
   ```
   FIS sends the document by its ARN, so a filter on the name alone finds nothing. While the action runs, FIS sends a new command to the same tasks about every 20 seconds: three with the 1-minute duration, and nine with 3 minutes in the test. Only the first starts the packet loss; the later ones extend its heartbeat. A target got packet loss when its output from the first command has `Enabling fault injection` followed by `{"Status":"running"}#200`, the ECS agent's answer that the fault started. In the test, a start that the ECS agent refused printed `Enabling fault injection` followed by an error ending in `#400`. A target task with no invocation of the first command, or whose output lacks those two lines, got no packet loss, whatever the action's state says. The commands' statuses don't tell: in the test, the fault step of first commands that started the packet loss ended `Cancelled`, `Failed` or `Success`, and the offline sidecar's command ended `Failed` with no output. Without `--plugin-name`, `get-command-invocation` returns no output, because the document has two steps.
3. **`wait-before-stop`** (T+0 to T+1m) holds `stop-tasks-in-az` and `disrupt-az-connectivity` back for 1 minute.
4. **`stop-tasks-in-az`** (from T+1m) calls `StopTask` on each target task. ECS then starts replacements wherever its placement puts them, including the target Availability Zone, if it hasn't started them already (see [What else is affected](#what-else-is-affected)). `StopTask` also returned OK on targets that ECS had stopped already, so the action completes either way. The experiment does not stop, fault or watch the replacements.
5. **`disrupt-az-connectivity`** (T+1m to T+16m). FIS copies each target subnet's network ACL, tags the copy `managedByFIS=true`, adds deny rules for intra-VPC traffic to and from subnets in other Availability Zones, and associates the copy with the subnet. When the 15 minutes end, or the experiment is stopped, FIS associates the original network ACL again and deletes the copy ([actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html#disrupt-connectivity)).

FIS stops the targets as soon as the wait ends, so the packet loss lasts as long as `wait-before-stop`, unless ECS stops a target first: behind a load balancer, the packet loss fails the targets' health checks, and ECS replaces tasks that fail them (see [What else is affected](#what-else-is-affected)). If you change one duration, change the other to match, within the limit in [Next Steps](#next-steps) 6. FIS picks the targets once, at the start, so a longer packet-loss action would keep running after its targets are stopped, and would never reach their replacements.

What the experiment doesn't check: that your service has tasks in more than one Availability Zone, that the remaining capacity is enough, that replacements start or where, and that clients notice anything. Those are what you measure. Nor does it check that each target got the packet loss for the whole minute: step 2 and [What else is affected](#what-else-is-affected) say how to check that after the run.

### Actions Detail

| Action | Action ID | Description | Starts | Duration |
|--------|-----------|-------------|--------|----------|
| `inject-network-packet-loss` | `aws:ecs:task-network-packet-loss` | 100% egress packet loss into the `FIS-Ready` tasks running in the target AZ at T+0, except to the ECS agent and SSM endpoints. | T+0 | 1 minute |
| `wait-before-stop` | `aws:fis:wait` | Holds the task stop and the network fault back while packet loss is active. | T+0 | 1 minute |
| `stop-tasks-in-az` | `aws:ecs:stop-task` | Stops the tasks that were running in the target AZ at T+0. | T+1m | One `StopTask` call per task |
| `disrupt-az-connectivity` | `aws:network:disrupt-connectivity` | Denies intra-VPC traffic between the target AZ's `FIS-Ready` subnets and subnets in other AZs. FIS puts the original network ACL back at the end. | T+1m | 15 minutes |

The whole experiment takes about 16 minutes: the 1-minute wait, then `disrupt-az-connectivity`. Test runs that went to the end took 16.23 to 16.28 minutes.

### What else is affected

- **Everything in the target subnets.** `disrupt-az-connectivity` changes the subnet's network ACL, so it denies traffic to and from other Availability Zones for every network interface in the subnet, tagged or not: other services' tasks, databases, Lambda functions in the VPC, interface VPC endpoints and NAT gateways that live there. Use subnets that hold only the service under test, and preview the targets first with `aws fis start-experiment --experiment-template-id <id> --experiment-options actionsMode=skip-all`, then list what the preview selected with `aws fis list-experiment-resolved-targets --experiment-id <preview experiment ID>`. The preview didn't warn about tagged subnets in two VPCs (Prerequisite 4).
- **Every tagged subnet and task in the Availability Zone.** The targets select by tag and Availability Zone only, not by cluster, service or VPC. Any `FIS-Ready=True` subnet in the target Availability Zone, in any VPC of the account and Region, is selected, and any running `FIS-Ready=True` task in that Availability Zone, in any cluster, gets packet loss and is stopped. If the selected subnets are in more than one VPC, the network fault fails at T+1m, after the tasks have had the packet loss and been stopped (Prerequisite 4).
- **Paths that cross Availability Zones.** In the test, FIS's deny entries named the address ranges of the VPC's subnets in other Availability Zones, so only traffic to and from an address in one of those subnets is denied. If the target subnets reach AWS services through interface endpoints whose network interfaces are in another Availability Zone, tasks there, including replacements, lose those paths (not tested). Traffic to addresses outside the VPC isn't denied, even through a NAT gateway in another Availability Zone: in the test, two replacements in a private subnet whose NAT gateway was in another Availability Zone pulled their images and registered with SSM through it while the network fault lasted. Traffic inside the target Availability Zone, and traffic to and from outside the VPC through an internet gateway, is not denied either.
- **Other clients of the stopped tasks.** The packet loss drops the target tasks' egress IPv4 traffic to every destination but the ECS agent endpoint and the Region's SSM endpoints, so every client of those tasks, in any Availability Zone, gets no IPv4 answers while the packet loss lasts, up to the first minute less the document's start time. IPv6 traffic isn't impaired by this action.
- **CloudFormation and other infrastructure as code.** The network ACL association changes outside your stack, so a stack that manages it shows drift during the run ([drift detection](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-cfn-stack-drift.html)), and a stack update to the subnet's network ACL association during the run can conflict with FIS's restore.
- **Other network faults on the same tasks.** ECS allows "either one network latency fault or one network packet loss fault" at a time and rejects the second request with `409` ([fault injection endpoints](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fault-injection-endpoints.html)), and FIS says `aws:ecs:task-network-blackhole-port`, `aws:ecs:task-network-latency` and `aws:ecs:task-network-packet-loss` "cannot run in parallel" ([limitations](https://docs.aws.amazon.com/fis/latest/userguide/ecs-task-actions.html#ecs-task-limitations)). Don't run another of these on the target tasks during the first minute.
- **Another run on the same subnet.** Don't start this experiment, or another network ACL experiment on the same subnet, while one is running. In two tests, a second run started 3 minutes into the first failed at its network fault ("There is already a running experiment targeting the same subnets"), and the first run's fault ran its full time. Before it failed, though, the second run put packet loss on the first run's replacement task in the Availability Zone and stopped it. A second run started 24 seconds into the first, while the first run's packet loss was on, selected the same tasks, but its own command never started a fault: its heartbeat commands failed ("Fault is not running. Heartbeat failed."), and FIS still reported its packet-loss action `completed`. Its `StopTask` calls returned OK on the tasks the first run had just stopped, and it then failed at its network fault. Probes every second showed the first run's packet loss unchanged, and its network fault ran its full time.
- **Load balancer health checks and ECS replacements.** While the packet loss drops a task's traffic, its load balancer health checks fail. Once the target group takes a task out of service, ECS starts a replacement and stops the unhealthy task when the replacement is healthy, or stops it first if the service's `maximumPercent` leaves no room ([Amazon ECS services](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs_services.html)). Either can come before FIS's own task stop at T+1m (see "What the target needs" in the [Hypothesis](#hypothesis)). In the test the target group took a task out of service after 2 failed checks 5 seconds apart, and ECS started replacements 28 to 71 seconds after the start, some in the target Availability Zone, where the network fault then cut them off.
  - With `maximumPercent` 200, ECS's default, ECS stopped one target or both itself 4 to 11 seconds before FIS did in four runs with the 1-minute packet loss, and stopped both targets about 120 and 139 seconds after the start of a run with a 3-minute packet loss. FIS's `StopTask` then returned OK on the tasks ECS had stopped, and FIS reported the packet-loss action `completed` each time, for packet loss that ECS had cut short.
  - With `maximumPercent` 100, ECS stopped a target 28 seconds after the start of a run with a 5-minute packet loss, without waiting for a replacement. FIS's later heartbeat commands, each sent to every target's managed instance, failed, so the other target's packet loss ended ("Fault expiring due to age of last heartbeat.") between T+109 and T+124 seconds, by 15-second probes, and FIS failed the action and the experiment at 2.6 minutes, before the task stop and the network fault. ECS refuses `maximumPercent` 100 while the service's `availabilityZoneRebalancing` is `ENABLED` ("Availability Zone Rebalancing does not support maximumPercent <= 100 % as deployment configuration").
  - Once the unhealthy tasks are replaced, ECS stops tasks until the count is back to `desiredCount`, keeping the Availability Zones as balanced as it can ([replica scheduling strategy](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs_service-options.html#service_scheduler_replica)), and not only the ones it started: after stops in the first minute, it stopped two tasks in other Availability Zones in one run, and one replacement and one of the original targets in another.
  - To see how each target stopped, read its stop code and reason after the run:
    ```bash
    aws ecs describe-tasks --cluster <cluster> --tasks <task ARN> --query 'tasks[].{stopCode:stopCode,reason:stoppedReason,stoppingAt:stoppingAt}'
    ```
    ECS's stops show `ServiceSchedulerInitiated` and "Task failed ELB health checks", and FIS's show "Task stopped by AWS FIS". A target whose `stoppingAt` is before `stop-tasks-in-az` started got less than the minute of packet loss.

## Targets

| Target Name | Resource Type | Selection Mode | Description |
|-------------|---------------|----------------|-------------|
| `subnet-in-az` | `aws:ec2:subnet` | ALL | Every `FIS-Ready=True` subnet in the target AZ |
| `ecs-tasks-for-stop` | `aws:ecs:task` | ALL | Every running `FIS-Ready=True` task in the target AZ, to be stopped |
| `ecs-tasks-for-packet-loss` | `aws:ecs:task` | ALL | The same tasks, to receive packet loss |

### Target Requirements
- Subnets and tasks must have the `FIS-Ready=True` tag and be in the target Availability Zone, and the tagged subnets in that Availability Zone must all be in one VPC.
- At least one of each must exist at the start, or the experiment fails before it changes anything.

> **Note on the `LastStatus=RUNNING` task filter:** both task targets filter on
> `LastStatus=RUNNING` as well as the Availability Zone. ECS returns stopped
> tasks for a while
> ([DescribeTasks](https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_DescribeTasks.html)),
> and in the test a stopped task kept its tags, `FIS-Ready=True` included, in
> ECS and in the tagging API for at least 15 minutes. FIS's target lookup
> returned such a task in the target Availability Zone, and only this filter
> kept it out. Without the filter, a task that an earlier run stopped could be
> selected again, and the packet-loss command can't run on a stopped task.

## Parameters to Configure

Before running the experiment, update these placeholder values:

| Placeholder | Where | Description |
|-------------|-------|-------------|
| `<YOUR AWS ACCOUNT>` | template, IAM policy, trust policy, task role policy (Prerequisite 10) | Your 12-digit AWS account ID |
| `<YOUR REGION>` | IAM policy, trust policy, task role policy for the non-root image (Prerequisite 10) | AWS Region where the resources are |
| `<YOUR ROLE NAME>` | template | FIS experiment role name |
| `<YOUR TARGET AZ>` | template (three places) | Availability Zone to impair |
| `<YOUR MANAGED INSTANCE ROLE NAME>` | task role policy (Prerequisite 10) | The role in the sidecar's `MANAGED_INSTANCE_ROLE_NAME` |
| `<YOUR ERROR THRESHOLD>` | Hypothesis | Highest failed-request share per minute you accept |
| `<YOUR DETECTION TIME>` | Hypothesis | Longest time you accept until an alarm flags the target AZ |

> Targeting is by the `FIS-Ready=True` tag and Availability Zone only. There is
> no ECS cluster or service field to configure. Put the tag only on the subnets
> and tasks you intend to fault, and see [What else is affected](#what-else-is-affected)
> for everything else the network fault reaches.

## Stop Conditions

The experiment does not have any specific stop conditions defined by default. It will continue to run until manually stopped or until all actions complete, about 16 minutes after the start.

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

What a stop does, by phase:

- **In the first minute** (packet loss active, network fault not started, tasks not stopped by FIS): FIS cancels the packet-loss command, and `stop-tasks-in-az` and `disrupt-az-connectivity` never run, so FIS stops no task and no network ACL changes. The cancel reaches the sidecar, because the document keeps the SSM endpoints reachable, but the packet loss outlasts it: the document's rollback watchdog, a separate process that the first command starts, ends the packet loss once the command has stopped. In the test, after stops 30 seconds into the run, the first command ended `Cancelled` on every target within about a second of FIS's cancel, and the watchdog called the ECS fault `stop` endpoint 40 seconds after the packet loss had started, about 24 seconds after the stop was requested. ECS may still stop tasks, the targets included, if their health checks failed during the packet loss (see [What else is affected](#what-else-is-affected)). A stop before FIS sends the command changes nothing: in the test, a stop 0.15 seconds in left every action `cancelled`.
- **Just after the first minute** (between the end of `wait-before-stop` and the start of the network fault): FIS can still start both later actions. In the test, after a stop requested 0.4 seconds after the wait ended, FIS stopped the target 0.3 seconds after the request and associated its network ACL copy with the subnet 1.5 to 2.5 seconds after it, then put the original back about 2 seconds later. Nothing was left.
- **After the first minute** (network fault active, tasks already stopped): FIS puts each subnet's original network ACL back and deletes its copy. In the test this happened within 2 seconds of the stop request, including for a stop 2.5 seconds before the network fault's scheduled end.

A stop doesn't bring back the stopped tasks or move their replacements: ECS has already replaced them, wherever it placed them. A stopped experiment can't be resumed ([stop an experiment](https://docs.aws.amazon.com/fis/latest/userguide/stop-experiment.html)); start a new one.

**Restore by hand.** If a subnet is still associated with a network ACL tagged `managedByFIS=true` after the experiment has ended, for example because its `FIS-Ready` tag was removed during the run, put the original back yourself. In the test, removing the tag during the run made the restore fail and the experiment end `failed` ("FIS-managed Network ACLs changed while the action was running"), without naming the subnet or saying that FIS's copy was still associated. In one such run FIS put the original back on its own 74 seconds after the tag was added again; in another, the commands below, run while the tag was still off, put it back. To find every FIS copy that is left, with its VPC and the subnets associated with it, run:

```bash
aws ec2 describe-network-acls --filters Name=tag:managedByFIS,Values=true --query 'NetworkAcls[].{acl:NetworkAclId,vpc:VpcId,tags:Tags,subnets:Associations[].SubnetId}'
```

The copy's `aws:fis:experimentId` tag names the experiment that made it. Note each target subnet's network ACL before the run:

```bash
aws ec2 describe-network-acls --filters Name=association.subnet-id,Values=<subnet-id> --query 'NetworkAcls[].NetworkAclId' --output text
```

After the run, find the association and the FIS copy, associate the original again, and delete the copy:

```bash
aws ec2 describe-network-acls --filters Name=association.subnet-id,Values=<subnet-id> --query 'NetworkAcls[].{acl:NetworkAclId,tags:Tags,assoc:Associations[?SubnetId==`<subnet-id>`].NetworkAclAssociationId}'
aws ec2 replace-network-acl-association --association-id <association-id> --network-acl-id <original-network-acl-id>
aws ec2 delete-network-acl --network-acl-id <managedByFIS-network-acl-id>
```

Delete only a network ACL that has the `managedByFIS=true` tag and no subnet associated.

**A stop condition** tied to an alarm stops the experiment as a manual stop does, with the same effect in each phase: after the first minute it ends the network fault; in the first minute it cancels the packet-loss command and keeps FIS from stopping the tasks or changing the network ACL, and the document's watchdog ends the packet loss later (in the test, 22 seconds after the experiment ended). It can't bring back tasks already stopped. To check that your alarm stops the experiment, set it to `ALARM` during a run with `aws cloudwatch set-alarm-state --alarm-name <alarm> --state-value ALARM --state-reason "FIS stop condition test"` ([SetAlarmState](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_SetAlarmState.html)), and confirm the experiment ends `stopped`. In the test it ended `stopped` ("Experiment halted by stop condition.") 2.6 and 2.9 seconds after the command.

### Recommended Metrics for Stop Conditions

Consider creating CloudWatch alarms for these metrics:

- **ECS Service Metrics**
  - `CPUUtilization` - Alert if remaining tasks are overloaded
  - `MemoryUtilization` - Alert if memory pressure increases
  - `RunningTaskCount` (Container Insights) - Alert if task count drops below minimum threshold

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

1. Reviewing the tag names you use to ensure they fit your specific use case. The default tag is `FIS-Ready=True`. The template's `resourceTags` on all three targets and the IAM policy's conditions on `ecs:StopTask` and on the subnet for `ec2:ReplaceNetworkAclAssociation` name this tag, so change them with it.
2. Identifying business metrics tied to your ECS Fargate service health (request latency, error rates, task health, throughput).
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of AZ impairment on service availability.
4. Adding a stop condition tied to the alarm to automatically halt the experiment if critical thresholds are breached, and testing it as [Stop Conditions](#stop-conditions) describes.
5. Running the experiment in a non-production environment first. Before a second run, wait until every task in the target Availability Zone, including the replacements of the first run, has an online managed instance (Prerequisite 9): a task FIS selects without one fails the run at its start, and an offline one gets no packet loss. Confirm with your own service that replacement tasks placed in the impaired AZ are seen as unreachable by your health checks and alarms, and that no network ACL tagged `managedByFIS=true` is left associated with the subnet afterwards ([Restore by hand](#stop-conditions) gives a command that lists them).
6. Adjusting the length of the network fault (the `duration` of `disrupt-az-connectivity`, 15 minutes by default) to your recovery time objectives. In the test, a 30-minute network fault ran its full length and was restored. To change how long the tasks get packet loss before they are stopped and the network fault starts, change the `duration` of both `inject-network-packet-loss` and `wait-before-stop`, to the same value, and keep it shorter than the time your target group takes to take a target out of service (see "What the target needs" in the [Hypothesis](#hypothesis)). Otherwise ECS replaces the targets during the packet loss. In the test, with a target group that took about 10 seconds, a 3-minute packet loss ended `completed` although ECS had stopped both targets about 2 minutes in, and a 5-minute packet loss, with the service's `maximumPercent` at 100, failed the experiment at 2.6 minutes, before the task stop and the network fault.
7. Once you've validated detection behavior with this template, consider running [`ecs-fargate-az-evacuation`](../ecs-fargate-az-evacuation/README.md) to test whether your operational response (automated or manual) correctly evacuates the AZ.
8. Documenting the expected behavior and actual results to build a runbook for real AZ failures.
9. Gradually increasing the scope of the experiment (for example, a longer network fault or more services) as confidence grows, checking Prerequisite 9 before each run.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).

## Files in This Directory

| File | Description |
|------|-------------|
| `README.md` | This documentation file |
| `AWSFIS.json` | Template version marker for fis-template-library-tooling |
| `ecs-fargate-az-impairment-template.json` | FIS experiment template definition |
| `ecs-fargate-az-impairment-iam-policy.json` | IAM policy for the FIS experiment role |
| `fis-iam-trust-relationship.json` | Trust policy for the FIS experiment role |
