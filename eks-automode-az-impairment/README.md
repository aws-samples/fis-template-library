# AWS Fault Injection Service Experiment: EKS Auto Mode Availability Zone Impairment

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE

## Hypothesis

When an Availability Zone experiences an impairment affecting an EKS Auto Mode cluster, the workload should sustain the failure by running its replicas in the remaining healthy AZs — scaling up there as needed — rather than losing capacity for the duration. Specifically:

- When network connectivity is disrupted in the target AZ, pods in that AZ should become unreachable
- When nodes in the target AZ are cordoned and the NodePool is patched to exclude the AZ, EKS Auto Mode should not provision new nodes in the impaired AZ
- When pods are deleted in the target AZ, Kubernetes should reschedule them into the healthy AZs only, scaling up there if required
- The application should remain available throughout the experiment, serving from the healthy AZs
- When the NodePool is restored and nodes are uncordoned, capacity should become available in that AZ again

Whether the third and fourth points hold depends on your workload's topology spread constraints and the capacity headroom in the surviving AZs — see [Cluster configuration determines the outcome](#cluster-configuration-determines-the-outcome). A workload that cannot fail over will instead run at reduced capacity for the duration, and the experiment will still report success.

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
     --principal-arn arn:aws:iam::<ACCOUNT>:role/<YOUR SSM AUTOMATION ROLE NAME> \
     --username fis-ssm-automation \
     --cluster-name <YOUR EKS CLUSTER>
   ```
   Only the SSM automation role needs Kubernetes access. The FIS execution role never calls the Kubernetes API — it only starts the SSM automation and drives the NACL action — so it does not need an access entry.

3. **Kubernetes RBAC**: Apply the RBAC configuration to your cluster:
   ```bash
   kubectl apply -f eks-automode-az-impairment-rbac.yaml
   ```
   This grants the SSM automation permission to cordon/uncordon nodes, delete pods, and patch the NodePool.

4. **SSM Automation Document**: Deploy the SSM automation document:
   ```bash
   aws ssm create-document \
     --name "eks-automode-az-impairment-automation" \
     --document-type "Automation" \
     --content file://eks-automode-az-impairment-automation.yaml \
     --document-format YAML
   ```

5. **Multi-AZ Deployment**: Your EKS Auto Mode cluster must have subnets in at least 2 different AZs, with workloads distributed across them. **3 AZs is recommended** — with `DoNotSchedule` and `maxSkew: 1`, a 3-AZ cluster allows evicted pods to redistribute across both surviving AZs (all pods `Running`), whereas a 2-AZ cluster leaves them `Pending`. See [Number of Availability Zones](#3-number-of-availability-zones).

6. **Workload must be able to fail over into the surviving AZs** — see [Cluster configuration determines the outcome](#cluster-configuration-determines-the-outcome) below. This is a property of *your* workload, not of the experiment, and it decides whether you observe a surviving service or a degraded one.

7. **NodePool Identification**: Identify which NodePool your workloads use:
   ```bash
   kubectl get nodepools
   ```
   This must be a **custom NodePool**, not the built-in `general-purpose` or `system` pools — see [Important: use a custom NodePool](#important-use-a-custom-nodepool-not-a-built-in-one) above. Built-in pools are reconciled by EKS and the AZ exclusion will be silently reverted mid-experiment.

8. **Tag the target subnet**: The FIS experiment resolves its target by tag, so the VPC subnet in the AZ you want to impair must carry the tag `FIS-Ready=True`. The template also scopes the target to a single AZ via the `availabilityZoneIdentifier` parameter, so only the FIS-Ready subnet(s) in `<YOUR TARGET AZ>` are selected. Tag it with:
   ```bash
   aws ec2 create-tags \
     --resources <YOUR SUBNET ID IN TARGET AZ> \
     --tags Key=FIS-Ready,Value=True
   ```
   The IAM policy's `ec2:ReplaceNetworkAclAssociation` permission is conditioned on this tag, so the network-disruption action can only associate the deny-NACL with a subnet you have explicitly marked `FIS-Ready=True`.

## Cluster configuration determines the outcome

This experiment always does the same three things: cordon the nodes in the target AZ, exclude that AZ from the NodePool, and delete the pods there. What you *observe* — a service that rides through the impairment, or one that runs degraded — is decided entirely by **your workload's configuration**, not by anything in the experiment template.

The intent of an AZ impairment scenario is to show that the workload sustains the failure by running its replicas in the healthy AZs. If your workload is not configured to allow that, the experiment will still report success while the service sits at reduced capacity. Check the two settings below **before** running it, or you will draw the wrong conclusion from a passing experiment.

These are cluster/workload changes, applied with `kubectl` against your own manifests. Nothing here is part of the FIS template.

### 1. Topology spread constraint: `whenUnsatisfiable`

This is the setting that decides the outcome.

```yaml
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: ScheduleAnyway   # <-- or DoNotSchedule
    labelSelector:
      matchLabels:
        app: myapp
```

With `DoNotSchedule` and `maxSkew: 1`, concentrating every replica into one AZ violates the constraint (a 6-vs-0 split is a skew of 6), so the scheduler **refuses to place the evicted pods at all**. They stay `Pending`. Because they are unschedulable rather than merely unplaced, EKS Auto Mode never receives a signal to provision capacity for them, so no replacement node appears anywhere.

With `ScheduleAnyway`, the even spread becomes a preference. The evicted pods schedule immediately into the surviving AZ, using spare capacity on existing nodes if there is any, and prompting Auto Mode to provision a node there if there is not.

### 2. Capacity headroom in the surviving AZs

Failover only completes if the replicas actually fit. Compare the total requests of the replicas that will move against the allocatable capacity left in the surviving AZs:

```bash
# Allocatable CPU per node, by zone.
kubectl get nodes -o custom-columns=\
'NAME:.metadata.name,ZONE:.metadata.labels.topology\.kubernetes\.io/zone,CPU:.status.allocatable.cpu'

# What each node is already committed to.
kubectl describe node <node> | grep -A5 'Allocated resources'
```

If existing nodes have headroom, failover is as fast as pod startup — no EC2 launch required. If they do not, Auto Mode provisions new nodes and failover additionally waits on instance launch and node registration (typically 60–90s). Make sure nothing prevents that scale-up: a `spec.limits` on the NodePool, an insufficient `maxSkew`, or restrictive instance-type requirements can all cap it.

### Which behaviour to expect

| Workload configuration | AZs | During impairment | What it demonstrates |
|---|---|---|---|
| `ScheduleAnyway`, headroom available | 2 | All replicas `Running` in surviving AZ; no new nodes | Workload sustains AZ loss; fastest recovery |
| `ScheduleAnyway`, no headroom | 2 | Replicas briefly `Pending`, then `Running` on newly provisioned nodes | Workload sustains AZ loss via scale-up |
| `ScheduleAnyway`, scale-up blocked (NodePool `limits`, instance constraints) | 2 | Some replicas stay `Pending` | Capacity ceiling — a real finding to fix |
| `DoNotSchedule` | 2 | Replicas stay `Pending` for the whole impairment; service degraded | Proves the AZ exclusion is in force, but **not** that the workload survives |
| `ScheduleAnyway`, headroom available | 3 | All replicas `Running`, distributed 0/3/3 across surviving AZs | Workload sustains AZ loss with even distribution |
| `DoNotSchedule`, `maxSkew: 1` | 3 | All replicas `Running`, distributed 0/3/3 across surviving AZs | **Both proves the exclusion AND that the workload survives** — the key 3-AZ advantage |
| `DoNotSchedule`, `maxSkew: 1`, no headroom | 3 | Replicas briefly `Pending`, then `Running` after Auto Mode scale-up in surviving AZs | Workload sustains via scale-up in both surviving AZs |

Both settings are legitimate tests, but they answer different questions. `DoNotSchedule` is the stricter proof that the impairment itself is real — `Pending` pods are unambiguous evidence that nothing could be scheduled into the impaired AZ, which is useful when validating the template or the automation. `ScheduleAnyway` is what you want for an AZ impairment scenario that showcases the workload sustaining the failure.

### 3. Number of Availability Zones

The number of AZs in your cluster changes both the blast radius and the redistribution behaviour during impairment.

| Cluster AZs | Pods lost | Surviving pods | Where replacements land | Effective capacity during impairment |
|---|---|---|---|---|
| 2 AZs (e.g. 3/3) | 50% of replicas | 50% | Single surviving AZ only | 50% baseline (if `DoNotSchedule`) or 100% (if `ScheduleAnyway` with headroom) |
| 3 AZs (e.g. 2/2/2) | 33% of replicas | 67% | **Distributed across both surviving AZs** | 67% baseline (if `DoNotSchedule`) or 100% (if `ScheduleAnyway` with headroom) |

With **3 AZs and `DoNotSchedule`**, the topology spread constraint (`maxSkew: 1`) forces the scheduler to distribute evicted pods across both surviving AZs rather than concentrating them in one. After the 2 pods in the target AZ are killed, the scheduler must place them so that no zone exceeds the others by more than 1 — the only valid 6-pod arrangement across 2 zones is 3/3. This means the workload stays spread even under failure, rather than hotspotting into a single AZ.

With **2 AZs and `DoNotSchedule`**, there is only one surviving AZ. The evicted pods cannot schedule there because moving from a 3/3 spread to 0/6 violates `maxSkew: 1` (skew = 6). They remain `Pending`.

This makes the 3-AZ topology fundamentally different: `DoNotSchedule` no longer means "degraded for the duration" — it means "pods redistribute evenly across surviving zones while still proving the impaired AZ is excluded."

### Validation results

**2 AZs** (6 replicas, 500m CPU requests, `DoNotSchedule`): the service ran at 50% capacity (3 `Running` / 3 `Pending`) for the full 15-minute impairment. Changing only `whenUnsatisfiable` to `ScheduleAnyway` produced 6 `Running` / 0 `Pending` throughout — 100% availability — with the replicas packing onto existing nodes in the surviving AZ and no new nodes needed.

**3 AZs** (6 replicas, 500m CPU requests, `DoNotSchedule`): the 2 pods in the target AZ were killed and rescheduled — one to each surviving AZ — producing a clean 0/3/3 distribution. All 6 pods were `Running` throughout the impairment. The `maxSkew: 1` constraint was satisfiable across 2 remaining zones (3 vs 3 = skew 0), so unlike the 2-AZ case, `DoNotSchedule` did not cause degradation. The workload sustained the AZ loss with pods distributed across both surviving zones rather than collapsing into one.

| Metric | 2 AZs | 3 AZs |
|---|---|---|
| Starting distribution | 3 / 3 | 2 / 2 / 2 |
| Pods killed | 3 (50%) | 2 (33%) |
| During impairment (`DoNotSchedule`) | 0 / 3 + 3 `Pending` | 0 / 3 / 3 — all `Running` |
| During impairment (`ScheduleAnyway`) | 0 / 6 — all `Running` | 0 / 3 / 3 — all `Running` |
| Nodes reprovisioned during | 0 | 0 |
| Post-restore distribution | Unchanged until rollout restart | Unchanged until rollout restart |

### After the experiment

Regardless of `whenUnsatisfiable` or AZ count, replicas do **not** automatically migrate back once the impaired AZ is restored. Topology spread constraints are evaluated only at scheduling time — they never evict a running pod to satisfy a spread. Additionally, with `consolidationPolicy: WhenEmpty`, no new node is reprovisioned in the restored AZ because no scheduling demand exists there.

The post-restore state is:
- NodePool zone requirement includes all original AZs again ✓
- No cordoned nodes remain ✓
- No leftover NACLs (FIS restores these automatically) ✓
- **Pods stay where they landed during impairment** — the cluster has capacity in the restored AZ but nothing triggers rebalancing

This is realistic production behaviour: after an AZ recovers, workloads drift from their intended spread until an explicit action redistributes them. See [Recovery Behavior](#recovery-behavior) for how to rebalance.

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

The experiment uses a single SSM Automation document (`eks-automode-az-impairment-automation`) that manages the complete EKS-specific fault lifecycle:

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

### Why This Experiment Uses No `aws:eks:pod` Actions

The ECS experiment uses `aws:ecs:stop-task` as a separate FIS action because ECS tasks have native AZ metadata that FIS can filter on (resource tags + `AvailabilityZone` path filter).

EKS pod targets have no equivalent. FIS resolves `aws:eks:pod` targets by **namespace + label selector**, and the [FIS documentation](https://docs.aws.amazon.com/fis/latest/userguide/eks-pod-actions.html) states you *"can't identify targets of type `aws:eks:pod` in your experiment template using resource ARNs or resource tags."* Critically, **pods do not inherit their node's `topology.kubernetes.io/zone` label** — that label exists on Nodes only. A selector like `app=myapp,topology.kubernetes.io/zone=us-east-1a` therefore matches zero pods.

That leaves no correct way to scope a pod action to one AZ:

- An AZ-qualified label selector resolves to nothing, and with `emptyTargetResolutionMode: skip` the action silently does nothing while the experiment still reports success
- Dropping the AZ term and targeting `app=myapp` hits pods in the **healthy** AZs too — degrading the very capacity the experiment is meant to prove survives

So pod termination is handled by the SSM automation instead, directly via the Kubernetes API: it lists pods on nodes in the target AZ and deletes them with `gracePeriodSeconds=0` (sudden death, same as ECS stop-task). This gives precise AZ-scoped termination with no dependency on FIS pod targeting.

**This is also why there is no `aws:eks:pod-network-packet-loss` action.** Beyond the same targeting problem, subnet-level NACLs (`aws:network:disrupt-connectivity`) already block all traffic in the AZ — strictly broader than per-pod packet loss, since it affects every resource in the subnet rather than only labelled pods. The pod action would add setup cost (a Kubernetes service account, the `privileged` Pod Security Standard, root in the ephemeral container, and `readOnlyRootFilesystem: false` on every target pod) for no additional coverage.

If you do add `aws:eks:pod` actions to a fork of this experiment, note that all of them fail unless target pods set `readOnlyRootFilesystem: false` in their `securityContext` — FIS cannot otherwise monitor injection status. You would also need to re-add a Kubernetes service account, an EKS access entry for the FIS role, and the corresponding RBAC, none of which this experiment installs.

## Targets

| Target Name | Resource Type | Selection Mode | Description |
|-------------|---------------|----------------|-------------|
| `subnets-in-target-az` | `aws:ec2:subnet` | ALL | VPC subnets tagged `FIS-Ready=True` in the target AZ (scoped via the `availabilityZoneIdentifier` parameter) to disrupt network connectivity |

The template defines only this one FIS target. It is resolved by the `FIS-Ready=True` resource tag and scoped to a single AZ with the `availabilityZoneIdentifier` parameter (rather than a hard-coded subnet ARN), consistent with the tagging strategy used across this library. Pod termination is handled by the SSM automation via the Kubernetes API rather than by a FIS `aws:eks:pod` target — see [Why This Experiment Uses No `aws:eks:pod` Actions](#why-this-experiment-uses-no-awsekspod-actions) above.

### Target Requirements
- The subnet must carry the `FIS-Ready=True` tag and be in the AZ named by both the target's `availabilityZoneIdentifier` parameter and the automation's `TargetAZ` parameter, so the network disruption and the Kubernetes-level impairment affect the same AZ
- Nodes must carry the standard `topology.kubernetes.io/zone` label (EKS applies this automatically) — the automation uses it to find nodes and pods in the target AZ
- The SSM automation role must have Kubernetes API access via an EKS Access Entry plus the RBAC in `eks-automode-az-impairment-rbac.yaml`

## Parameters to Configure

Before running the experiment, update these placeholder values:

| Placeholder | Description |
|-------------|-------------|
| `<YOUR AWS ACCOUNT>` | Your 12-digit AWS account ID |
| `<YOUR REGION>` | AWS region where resources are deployed (e.g., `ap-southeast-2`) |
| `<YOUR FIS ROLE NAME>` | FIS execution IAM role name |
| `<YOUR SSM AUTOMATION ROLE NAME>` | SSM automation IAM role name |
| `<YOUR EKS CLUSTER>` | Name of your EKS cluster |
| `<YOUR TARGET AZ>` | Availability Zone to impair (e.g., `ap-southeast-2a`) |
| `<YOUR SUBNET ID IN TARGET AZ>` | Subnet ID(s) in the target AZ to tag with `FIS-Ready=True` (used in the `create-tags` step, not hard-coded in the template) |
| `<YOUR NODEPOOL NAME>` | Name of a **custom** EKS Auto Mode NodePool (not `general-purpose` or `system`) |

## How Pods in the Target AZ Are Selected

No pod label selector configuration is required. The SSM automation resolves the target pods itself:

1. Lists nodes matching `topology.kubernetes.io/zone=<TargetAZ>`
2. For each of those nodes, lists pods via `fieldSelector=spec.nodeName=<node>`
3. Deletes each pod with `gracePeriodSeconds=0`, skipping the `kube-system`, `kube-node-lease`, and `kube-public` namespaces

This means **all non-system pods on nodes in the target AZ are deleted**, across every namespace. If you need to limit the blast radius to specific workloads, add a namespace or label filter to the `DeletePodsInAZ` step in `eks-automode-az-impairment-automation.yaml`.

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

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or 
business metric requiring an immediate end of the fault injection. This 
template makes no assumptions about your application and the relevant metrics 
and does not include stop conditions by default.

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
4. **Pods**: behaviour depends on the configuration described in [Cluster configuration determines the outcome](#cluster-configuration-determines-the-outcome):
   - With `ScheduleAnyway` (2 or 3 AZs), pods that failed over **stay** in the surviving AZ(s). The spread is only a preference, so a running pod is never moved to satisfy it.
   - With `DoNotSchedule` (2 AZs), pods that were left `Pending` schedule into the restored AZ on their own as soon as the NodePool is restored and Auto Mode provisions a node there — no manual step needed.
   - With `DoNotSchedule` (3 AZs), pods **already rescheduled successfully** into the surviving AZs during impairment. They stay in their 0/3/3 distribution — they will not rebalance to 2/2/2 because topology spread constraints are only evaluated at scheduling time.

### Restore status and failure signal

The `RestoreNodePool` step reports a `Status` in its `RestoreResult` output describing how the cleanup went. On a clean run this is `NODEPOOL_RESTORED` (or `NODEPOOL_ALREADY_CORRECT` / `NODEPOOL_UNCHANGED_NO_PATCH_RECORDED` when there was nothing to undo).

If the restore cannot complete cleanly, the step **fails the SSM automation** (raises after first attempting to uncordon nodes) so the failure is visible to an operator and can trip a CloudWatch alarm or FIS stop condition, rather than being silently reported as success. A terminal restore leaves the target AZ still excluded from the NodePool and/or nodes still cordoned, so it requires **manual remediation**. Statuses that fail the step are:

- `NODEPOOL_RESTORE_FAILED_<code>` — the restore PATCH to the Kubernetes API returned a non-200 status.
- `NODEPOOL_RESTORE_ERROR: <message>` — an unexpected exception occurred during NodePool restore.
- Any status containing `UNCORDON_ERROR` or `UNCORDON_LIST_FAILED` — one or more nodes could not be uncordoned.

One status is treated as a **warning, not a failure**:

- `NODEPOOL_MODIFIED_EXTERNALLY_SKIPPED` — the NodePool was changed by something else (EKS Auto Mode reconciliation, a GitOps controller, or an operator) after the automation patched it. The automation **deliberately declined to touch it**, because removing a requirement it no longer recognises could be destructive. That external change has frequently already reverted the AZ exclusion, so failing here would be a false alarm. It is logged as a `WARNING` and the step still succeeds — but a human should confirm the NodePool's `topology.kubernetes.io/zone` requirement is correct. If you want unattended runs to alarm on it, create a metric filter on the `WARNING: NODEPOOL_MODIFIED_EXTERNALLY_SKIPPED` log line rather than relying on step failure.

**Manual remediation** when the step fails: inspect the `RestoreResult` in the automation execution output, then restore the NodePool's `topology.kubernetes.io/zone` requirement to its original values and uncordon any remaining nodes in the target AZ (`kubectl uncordon <node>`). Because the automation records its failure, an unattended run will surface it instead of leaving degraded capacity in place unnoticed.

**To rebalance pods that stayed put:**

```bash
kubectl rollout restart deployment/<your-deployment-name>
```

This cycles the pods so the scheduler places them fresh across all AZs. Note that a soft constraint still will not guarantee a spread: if the surviving AZ has enough headroom for every replica, the scheduler may simply place them all there again. In production, this is the equivalent of a post-incident rebalancing step.

**Why no automatic rebalance occurs:**

Kubernetes topology spread constraints are admission-time only — they influence where a pod is *initially placed* but never evict a running pod to re-satisfy the constraint. Combined with EKS Auto Mode's `consolidationPolicy: WhenEmpty` (or Karpenter's equivalent), no new node is provisioned in the restored AZ because no scheduling demand exists there. The node that was cordoned and drained during impairment was likely terminated, and nothing triggers its replacement.

This post-impairment drift is realistic production behaviour: after an AZ recovers, workloads remain where they failed over until an operator explicitly rebalances them (rollout restart, scaling event, or a descheduler).

Recovery time depends on:
- Control plane operations to provision new nodes (if needed)
- Pod startup time
- Health check grace periods
- Load balancer target registration

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to your EKS workload health.
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of the AZ impairment.
4. Adding a stop condition tied to the alarm to automatically halt the experiment if critical thresholds are breached.
5. Reviewing the RBAC ClusterRole and confirming the `fis-ssm-automation` username matches the one in your EKS Access Entry.
6. Narrowing the blast radius if needed — by default the automation deletes all non-system pods on nodes in the target AZ, across every namespace. Add a namespace or label filter to the `DeletePodsInAZ` step to scope it.
7. **Testing in a non-production environment first** to validate automation behavior and timing.
8. Documenting expected vs actual behavior to build an AZ failure runbook.
9. Gradually increasing scope (longer duration, more namespaces, multiple NodePools).

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).

## Files in This Directory

| File | Description |
|------|-------------|
| `README.md` | This documentation file |
| `AWSFIS.json` | Template version marker for fis-template-library-tooling |
| `eks-automode-az-impairment-template.json` | FIS experiment template definition |
| `eks-automode-az-impairment-automation.yaml` | SSM Automation document (cordon, patch NodePool, wait, restore) |
| `eks-automode-az-impairment-iam-policy.json` | IAM policy for the FIS execution role |
| `eks-automode-az-impairment-ssm-automation-iam-policy.json` | IAM policy for the SSM automation role |
| `eks-automode-az-impairment-rbac.yaml` | Kubernetes RBAC for the SSM automation role |
| `fis-iam-trust-relationship.json` | Trust policy for FIS service |
| `ssm-iam-trust-relationship.json` | Trust policy for SSM service |
