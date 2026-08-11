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

### Important: use a custom NodePool, not a built-in one

AWS documents that [the built-in `general-purpose` and `system` NodePools cannot be modified](https://aws.amazon.com/blogs/containers/maximizing-value-with-amazon-eks-auto-mode-strategies-for-visibility-control-and-optimization/). The Kubernetes API *accepts* a patch to them, but EKS Auto Mode reconciles the built-in NodePool back to its managed configuration.

In validation testing against `general-purpose`, the zone exclusion was applied successfully and was still in place two minutes in, but had been reverted roughly four minutes into a fifteen-minute impairment — while Auto Mode was actively provisioning replacement nodes. Once reverted, nothing stops Auto Mode from launching nodes in the "impaired" AZ again, so the impairment silently ends early and the experiment still reports success.

**Point `NodePoolName` at a custom NodePool that you own.** A custom NodePool is not reconciled by EKS, so the exclusion holds for the full duration. Verify the exclusion survives the whole window before trusting results:

```bash
# Should keep showing the target AZ excluded for the full impairment duration.
watch -n 30 "kubectl get nodepool <YOUR NODEPOOL NAME> -o json \
  | jq '.spec.template.spec.requirements[] | select(.key==\"topology.kubernetes.io/zone\")'"
```

Note that the NACL network disruption (`disrupt-az-network`) is unaffected by this and runs for its full duration regardless.

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

8. **NodePool Identification**: Identify which NodePool your workloads use:
   ```bash
   kubectl get nodepools
   ```
   This must be a **custom NodePool**, not the built-in `general-purpose` or `system` pools — see [Important: use a custom NodePool](#important-use-a-custom-nodepool-not-a-built-in-one) above. Built-in pools are reconciled by EKS and the AZ exclusion will be silently reverted mid-experiment.

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

**Why pods are deleted only after the NodePool is patched:** The ordering inside the SSM automation is what makes the impairment stick. Cordoning marks existing nodes in the target AZ unschedulable and the NodePool patch stops EKS Auto Mode from provisioning replacements there. Only then are pods deleted, so Kubernetes has no placement option left in the impaired AZ. If pods were deleted first, they could be rescheduled straight back into the AZ before the exclusion took effect.

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

The template defines only this one FIS target. Pod termination is handled by the SSM automation via the Kubernetes API rather than by a FIS `aws:eks:pod` target — see [Why Pod Deletion Is in the SSM Automation](#why-pod-deletion-is-in-the-ssm-automation-not-a-separate-fis-action) above.

### Target Requirements
- The subnet must be in the AZ named by the automation's `TargetAZ` parameter, so the network disruption and the Kubernetes-level impairment affect the same AZ
- Nodes must carry the standard `topology.kubernetes.io/zone` label (EKS applies this automatically) — the automation uses it to find nodes and pods in the target AZ
- The SSM automation role must have Kubernetes API access via an EKS Access Entry plus the RBAC in `eks-automode-az-impairment-rbac.yaml`

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
| `<YOUR NODEPOOL NAME>` | Name of a **custom** EKS Auto Mode NodePool (not `general-purpose` or `system`) |

## How Pods in the Target AZ Are Selected

No pod label selector configuration is required. The SSM automation resolves the target pods itself:

1. Lists nodes matching `topology.kubernetes.io/zone=<TargetAZ>`
2. For each of those nodes, lists pods via `fieldSelector=spec.nodeName=<node>`
3. Deletes each pod with `gracePeriodSeconds=0`, skipping the `kube-system`, `kube-node-lease`, and `kube-public` namespaces

This means **all non-system pods on nodes in the target AZ are deleted**, across every namespace. If you need to limit the blast radius to specific workloads, add a namespace or label filter to the `DeletePodsInAZ` step in `eks-automode-az-impairment-node-automation.yaml`.

## Fine-Tuning the Wait Duration

The automation deletes pods immediately after cordoning nodes and patching the NodePool, so no separate wait action is needed. If your cluster's control plane is slow enough that pods get rescheduled into the impaired AZ before the NodePool patch propagates, insert an `aws:sleep` step between `PatchNodePoolExcludeAZ` and `DeletePodsInAZ`. Timing depends on:

- **Cluster size**: More nodes = longer cordon time
- **Control plane load**: Busy clusters may take longer for NodePool patches to propagate
- **SSM execution overhead**: First-time execution may be slower

To calibrate:
1. Run the SSM automation document standalone 10 times
2. Measure the time from start to "nodes cordoned + NodePool patched"
3. Size the added `aws:sleep` step at the P95 duration + 30 seconds buffer

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
3. **Nodes**: SSM automation uncordons nodes in the target AZ — note that if EKS Auto Mode terminated a drained node during the impairment, there may be no node left in that AZ to uncordon, and `UncordonedNodes` will be empty. This is expected.
4. **Pods**: EKS Auto Mode will **not** automatically rebalance pods back to the restored AZ — pods stay where they landed during the failover

**To trigger rebalancing after the experiment:**

```bash
kubectl rollout restart deployment/<your-deployment-name>
```

This cycles the pods so the scheduler can place them across all AZs again. Whether they actually spread back depends on your pod resource requests and topology constraints: if the surviving AZ's nodes have enough headroom to hold every replica, the scheduler has no reason to spread and Auto Mode will not provision a node in the restored AZ. A hard `topologySpreadConstraints` entry (`whenUnsatisfiable: DoNotSchedule`) combined with requests large enough that one node cannot hold all replicas is what forces a genuine multi-AZ spread. In production, this is the equivalent of a post-incident rebalancing step.

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
