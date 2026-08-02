# AWS Fault Injection Service Experiment: EKS Auto Mode Availability Zone Impairment

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE

## Hypothesis

When an Availability Zone experiences an impairment affecting an EKS Auto Mode cluster, the workloads should continue operating with reduced capacity using pods in the remaining healthy AZs. Specifically:

- When network connectivity is disrupted in the target AZ, pods in that AZ should become unreachable
- When nodes in the target AZ are cordoned and the NodePool is patched to exclude the AZ, EKS Auto Mode should not provision new nodes in the impaired AZ
- When pods are deleted in the target AZ, EKS Auto Mode should reschedule them to healthy AZs only
- The application should remain available throughout the experiment with degraded but functional capacity
- When the NodePool is restored and nodes are uncordoned, EKS Auto Mode should automatically rebalance workloads across all AZs

## Background: Why This Is Different from Standard EKS

EKS Auto Mode manages the underlying EC2 instances on your behalf — you don't have direct access to stop or terminate the nodes. This means traditional AZ failure tests (stopping EC2 instances) won't work because:

1. You can't directly access or stop the AWS-managed EC2 instances
2. Simply deleting pods doesn't simulate the network impairment aspect of an AZ failure
3. EKS Auto Mode will immediately try to provision new nodes, potentially back in the impaired AZ

This experiment uses a "trifecta" approach (analogous to the ECS Fargate pattern) to realistically simulate an AZ failure:

1. **Network disruption** — Block all traffic at the subnet level using NACLs
2. **Node pool exclusion** — Cordon nodes and patch the NodePool to prevent scheduling in the target AZ
3. **Pod deletion** — Force-delete pods to trigger rescheduling to healthy AZs

## Prerequisites

Before running this experiment, ensure that:

1. **IAM Roles**: Create the FIS execution role and SSM automation role with the policies from the included IAM policy files.

2. **EKS Cluster Access**: The SSM automation role must have Kubernetes API access. Create an EKS Access Entry:
   ```bash
   aws eks create-access-entry \
     --principal-arn arn:aws:iam::<ACCOUNT>:role/<YOUR SSM ROLE NAME> \
     --username fis-ssm-automation \
     --cluster-name <YOUR EKS CLUSTER>

   # For FIS pod actions
   aws eks create-access-entry \
     --principal-arn arn:aws:iam::<ACCOUNT>:role/<YOUR FIS ROLE NAME> \
     --username fis-experiment \
     --cluster-name <YOUR EKS CLUSTER>
   ```

3. **Kubernetes RBAC**: Apply the RBAC configuration to your cluster:
   ```bash
   kubectl apply -f eks-automode-az-impairment-rbac.yaml
   ```
   This grants:
   - FIS pod actions: permissions to delete pods and inject ephemeral containers
   - SSM automation: permissions to cordon/uncordon nodes and patch NodePools

4. **SSM Automation Document**: Deploy the SSM automation document:
   ```bash
   aws ssm create-document \
     --name "eks-automode-az-impairment-node-automation" \
     --document-type "Automation" \
     --content file://eks-automode-az-impairment-node-automation.yaml \
     --document-format YAML
   ```

5. **Multi-AZ Deployment**: Your EKS Auto Mode cluster must have subnets in at least 2 different AZs, with workloads distributed across them.

6. **Pod Security Context**: For the `aws:eks:pod-network-packet-loss` action, target pods must have `readOnlyRootFilesystem: false` in their security context. The FIS pod container requires this to monitor fault injection status.

7. **Sufficient Capacity**: Remaining AZs must have sufficient capacity (or the ability to scale) to handle the workload during the experiment.

8. **NodePool Identification**: Identify which NodePool your workloads use (default is `general-purpose` for EKS Auto Mode built-in pools). Check with:
   ```bash
   kubectl get nodepools
   ```

## How It Works

This experiment simulates a complete AZ impairment using a sequenced approach that mirrors real-world AZ failures. Network disruption and node exclusion begin first, followed by pod deletion — ensuring pods cannot be rescheduled back into the impaired AZ.

### Experiment Flow

```
T+0     ┌─────────────────────────────────────────────────────────────────────┐
        │  FIS: disrupt-az-network (NACL blocks all traffic, 15 min)          │
        │  FIS: cordon-and-exclude-az (triggers SSM automation)               │
        └─────────────────────────────────────────────────────────────────────┘
                          │
        SSM Automation:   │
                          ▼
T+~4s   ┌─ CordonNodesInAZ ──────────────────────────────────────────────────┐
        │  Mark all nodes in target AZ as unschedulable                       │
        └─────────────────────────────────────────────────────────────────────┘
                          │
T+~34s  ┌─ PatchNodePoolExcludeAZ ───────────────────────────────────────────┐
        │  Remove target AZ from NodePool zone requirements                   │
        │  EKS Auto Mode cannot provision new nodes in impaired AZ            │
        └─────────────────────────────────────────────────────────────────────┘
                          │
T+~38s  ┌─ DeletePodsInAZ ───────────────────────────────────────────────────┐
        │  Delete all non-system pods on nodes in target AZ                   │
        │  gracePeriodSeconds=0 (instant kill, simulates sudden AZ death)     │
        │  Kubernetes reschedules to healthy AZs only ✓                       │
        └─────────────────────────────────────────────────────────────────────┘
                          │
T+38s → T+15m             ▼  WaitForDuration (impairment period)
                          │
T+15m                     ▼
        ┌─ RestoreNodePool ──────────────────────────────────────────────────┐
        │  Re-add target AZ to NodePool zone requirements                     │
        │  Uncordon all nodes in target AZ                                    │
        └─────────────────────────────────────────────────────────────────────┘
                          │
T+15m                     ▼  FIS restores NACLs (network connectivity returns)
                          ▼  EKS Auto Mode rebalances workloads across all AZs
```

**Why the 2-minute wait before pod deletion:** The SSM automation needs ~30-60 seconds to cordon nodes and patch the NodePool. The additional buffer ensures that by the time pods are deleted, EKS Auto Mode has no option to reschedule them in the impaired AZ. After running 10 test iterations of the SSM automation, we measured the control plane time (cordon + NodePool patch) at approximately 38 seconds consistently. We recommend calibrating this for your specific cluster by running the SSM automation standalone 10 times and using the max observed time + 30 seconds buffer.

### Actions Detail

| Action | Action ID | Description | Starts |
|--------|-----------|-------------|--------|
| `disrupt-az-network` | `aws:network:disrupt-connectivity` | Blocks all ingress/egress traffic on subnets in the target AZ via NACLs | T+0 |
| `cordon-and-exclude-az` | `aws:ssm:start-automation-execution` | Triggers the SSM automation that performs all K8s operations (cordon, patch, delete pods, wait, restore) | T+0 |

### SSM Automation Document

The experiment uses a single SSM Automation document (`eks-automode-az-impairment-node-automation`) that manages the complete EKS-specific fault lifecycle:

1. **Validates** input parameters (AZ format, cluster existence)
2. **Cordons nodes** in the target AZ (~4s) — prevents pod scheduling on existing nodes
3. **Patches the NodePool** to exclude the target AZ (~30s) — prevents EKS Auto Mode from provisioning new nodes there
4. **Deletes all non-system pods** on nodes in the target AZ (instant, `gracePeriodSeconds=0`) — simulates sudden pod death
5. **Waits** for the impairment duration (configurable, default 15 minutes)
6. **Restores the NodePool** to original configuration (re-includes the target AZ)
7. **Uncordons nodes** in the target AZ

Steps 2-4 have `onFailure` and `onCancel` routing to the restore step, ensuring the NodePool is always restored and nodes are always uncordoned even if the experiment is cancelled or encounters an error.

### Key Difference from ECS Pattern

| Aspect | ECS Fargate | EKS Auto Mode |
|--------|-------------|---------------|
| Scheduling control | Remove subnet from service network config | Cordon nodes + patch NodePool requirements |
| Network disruption | `aws:ecs:task-network-packet-loss` | `aws:network:disrupt-connectivity` (subnet-level NACL) |
| Workload termination | `aws:ecs:stop-task` (FIS action, AZ-filterable) | K8s API pod delete via SSM automation (see below) |
| Restore mechanism | Re-add subnet to service config | Remove zone exclusion from NodePool + uncordon nodes |

### Why Pod Deletion Is in the SSM Automation (Not a Separate FIS Action)

The ECS experiment uses `aws:ecs:stop-task` as a separate FIS action because ECS tasks have native AZ metadata that FIS can filter on (resource tags + `AvailabilityZone` path filter).

EKS pods do not have native AZ filtering in FIS. The `aws:eks:pod-delete` action targets pods by **namespace + label selector** only — there is no way to filter to a specific AZ. This means:

- You can't say "delete only pods in ap-southeast-2a" using FIS's pod-delete action
- If you target all pods by label, you'd delete pods in healthy AZs too
- The `emptyTargetResolutionMode: skip` causes the action to silently do nothing when no AZ-specific targets resolve

The solution: the SSM automation handles pod deletion directly via the Kubernetes API. After cordoning nodes and patching the NodePool, it lists pods running on nodes in the target AZ and deletes them with `gracePeriodSeconds=0` (simulating sudden death, same as ECS stop-task). This gives precise AZ-scoped pod termination without requiring FIS to support AZ filtering for EKS pods.

## Targets

| Target Name | Resource Type | Selection Mode | Description |
|-------------|---------------|----------------|-------------|
| `subnets-in-target-az` | `aws:ec2:subnet` | ALL | VPC subnets in the target AZ to disrupt network connectivity |
| `eks-pods-in-target-az` | `aws:eks:pod` | ALL | Pods to delete in the target AZ |
| `eks-pods-for-packet-loss` | `aws:eks:pod` | ALL | Pods to inject packet loss in the target AZ |

### Target Requirements
- Pods must be identifiable via label selectors (e.g., `app=myapp,topology.kubernetes.io/zone=<AZ>`)
- Pods must have `readOnlyRootFilesystem: false` for packet loss injection
- The FIS service account must have RBAC access to the target namespace

## Parameters to Configure

Before running the experiment, update these placeholder values:

| Placeholder | Description |
|-------------|-------------|
| `<YOUR AWS ACCOUNT>` | Your 12-digit AWS account ID |
| `<YOUR REGION>` | AWS region where resources are deployed (e.g., `ap-southeast-2`) |
| `<YOUR FIS ROLE NAME>` | FIS execution IAM role name |
| `<YOUR SSM ROLE NAME>` | SSM automation IAM role name |
| `<YOUR EKS CLUSTER>` | Name of your EKS cluster |
| `<YOUR TARGET AZ>` | Availability Zone to impair (e.g., `ap-southeast-2a`) |
| `<YOUR SUBNET ID IN TARGET AZ>` | Subnet ID(s) in the target AZ |
| `<YOUR NODEPOOL NAME>` | EKS Auto Mode NodePool name (default: `general-purpose`) |
| `<YOUR K8S SERVICE ACCOUNT>` | Kubernetes service account for FIS (default: `fis-experiment-sa`) |
| `<YOUR NAMESPACE>` | Kubernetes namespace where target pods run |
| `<YOUR POD LABEL SELECTOR>` | Label selector for target pods (e.g., `app=myapp`) |
| `<YOUR CONTAINER NAME>` | Container name within the pod to target |

## Targeting Pods in a Specific AZ

FIS EKS pod actions use label selectors, not AZ filters directly. To target pods in a specific AZ, you have two options:

### Option 1: Use Pod Topology Labels (Recommended)

If your pods have topology labels (many frameworks add these automatically):
```yaml
selectorType: labelSelector
selectorValue: "app=myapp,topology.kubernetes.io/zone=ap-southeast-2a"
```

### Option 2: Use a Topology Spread Constraint + Custom Labels

Add a mutating webhook or init container that labels pods with their AZ, or use the Kubernetes Downward API to expose node topology labels.

### Option 3: Target All Pods (Simpler)

Target all pods with the app label across all AZs. The network disruption and NodePool exclusion handle the AZ-specific failure — pods in healthy AZs continue working normally despite the packet loss action (which only affects reachability, not pod lifecycle):
```yaml
selectorType: labelSelector
selectorValue: "app=myapp"
```

## Fine-Tuning the Wait Duration

The 2-minute wait before pod deletion is a conservative default. Your cluster may need more or less time depending on:

- **Cluster size**: More nodes = longer cordon time
- **Control plane load**: Busy clusters may take longer for NodePool patches to propagate
- **SSM execution overhead**: First-time execution may be slower

To calibrate:
1. Run the SSM automation document standalone 10 times
2. Measure the time from start to "nodes cordoned + NodePool patched"
3. Set `wait-before-pod-delete` to the P95 duration + 30 seconds buffer

## Stop Conditions

The experiment does not include stop conditions by default. It will continue until all actions complete (approximately 30-45 minutes total).

### Recommended Metrics for Stop Conditions

Consider creating CloudWatch alarms for:

- **EKS Cluster Metrics**
  - Node count per AZ
  - Pod scheduling failures

- **Application Metrics**
  - Request latency (P99, P95)
  - Error rate (5xx responses)
  - Request throughput

- **Container Insights Metrics** (if enabled)
  - `pod_cpu_utilization`
  - `pod_memory_utilization`
  - `node_cpu_utilization` in remaining AZs

- **Load Balancer Metrics** (if applicable)
  - `TargetResponseTime`
  - `HTTPCode_Target_5XX_Count`
  - `UnHealthyHostCount`

## Recovery Behavior

After the experiment completes:

1. **Network**: FIS automatically restores the original NACLs (built into `aws:network:disrupt-connectivity`)
2. **NodePool**: SSM automation restores the original zone requirements
3. **Nodes**: SSM automation uncordons nodes in the target AZ
4. **Pods**: EKS Auto Mode will **not** automatically rebalance pods back to the restored AZ — pods stay where they landed during the failover

**To trigger rebalancing after the experiment:**

```bash
kubectl rollout restart deployment/<your-deployment-name>
```

This cycles the pods, and the scheduler will spread them across all AZs again (prompting EKS Auto Mode to provision a node in the restored AZ if needed). In production, this is the equivalent of a post-incident rebalancing step.

Recovery time depends on:
- Control plane operations to provision new nodes (if needed)
- Pod startup time
- Health check grace periods
- Load balancer target registration

## Next Steps

1. Review and customize the RBAC configuration for your specific namespaces and workloads.
2. Identify business metrics tied to your EKS workload health.
3. Create CloudWatch alarms and add them as stop conditions.
4. **Test in a non-production environment first** to validate automation behavior and timing.
5. Fine-tune the wait duration based on your cluster's SSM execution time.
6. Document expected vs actual behavior to build an AZ failure runbook.
7. Gradually increase scope (longer duration, multiple services/namespaces).

## Import Experiment

You can import the JSON experiment template into your AWS account via CLI or AWS CDK. For step by step instructions, [click here](https://github.com/aws-samples/fis-template-library-tooling).

## Files in This Directory

| File | Description |
|------|-------------|
| `README.md` | This documentation file |
| `AWSFIS.json` | Template version marker for fis-template-library-tooling |
| `eks-automode-az-impairment-template.json` | FIS experiment template definition |
| `eks-automode-az-impairment-node-automation.yaml` | SSM Automation document (cordon, patch NodePool, wait, restore) |
| `eks-automode-az-impairment-fis-role-iam-policy.json` | IAM policy for the FIS execution role |
| `eks-automode-az-impairment-ssm-automation-role-iam-policy.json` | IAM policy for the SSM automation role |
| `eks-automode-az-impairment-rbac.yaml` | Kubernetes RBAC for FIS and SSM automation |
| `fis-iam-trust-relationship.json` | Trust policy for FIS service |
| `ssm-iam-trust-relationship.json` | Trust policy for SSM service |
