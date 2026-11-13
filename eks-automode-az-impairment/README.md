# AWS Fault Injection Service Experiment: EKS Auto Mode Availability Zone Impairment

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

When an Availability Zone experiences an impairment affecting an EKS Auto Mode cluster, the workload should sustain the failure by running its replicas in the remaining healthy AZs, scaling up there as needed, rather than losing capacity for the duration. Specifically:

- When network connectivity is disrupted in the target AZ, pods in that AZ become unreachable
- While the AZ is impaired, EKS Auto Mode does not add working capacity in it: launches there fail, and nodes in it are cordoned
- When pods in the target AZ are deleted, Kubernetes reschedules them into the healthy AZs only, scaling up there if required
- The application remains available throughout the experiment, serving from the healthy AZs
- When the impairment ends, the NodePool and nodes are restored and capacity becomes available in that AZ again

Whether the third and fourth points hold depends on your workload's topology spread constraints and the capacity headroom in the surviving AZs. See [Cluster configuration determines the outcome](#cluster-configuration-determines-the-outcome). A workload that cannot fail over runs at reduced capacity for the duration, and the experiment still reports success.

## Background: Why This Is Different from Standard EKS

EKS Auto Mode manages the underlying EC2 instances on your behalf. You do not have direct access to stop or terminate the nodes, so a traditional AZ failure test (stopping EC2 instances) does not work. Deleting pods does not simulate the network side of an AZ failure either, and EKS Auto Mode keeps trying to provision new nodes, including in the impaired AZ.

This experiment combines five faults and actions:

1. **Network disruption**: block all traffic on the target AZ's subnets with network ACLs. Nodes and pods already in the AZ become unreachable.
2. **Insufficient capacity in the AZ**: make EC2 launches in the target AZ fail with `InsufficientInstanceCapacity`, for the IAM roles that launch your nodes (the EKS cluster role for Auto Mode, plus the Auto Scaling groups of any managed node groups).
3. **Zonal shift as the operator recovery action**: after a short delay that represents detection time, start an Amazon Application Recovery Controller (ARC) zonal shift for the cluster away from the target AZ. While it is active, EKS Auto Mode does not launch nodes in that AZ for any NodePool, including the built-in ones.
4. **Kubernetes-side impairment** (SSM automation, starts with the zonal shift): cordon the nodes in the target AZ, exclude the AZ from a custom NodePool and raise that NodePool's weight, and delete the pods in the AZ, simulating the sudden loss of the AZ's workloads.
5. **Restore and cleanup** (SSM automation): put back only what the run changed and remove everything it created.

The failure comes first, as in a real event. The pods are deleted only after the zonal shift has taken effect, so their replacements are placed in the surviving AZs and stay there.

### What each mechanism covers

| Mechanism | What it stops | What it does not stop |
|---|---|---|
| Network disruption | Traffic to and from every resource in the target AZ subnets | Launches of new instances in the AZ |
| Insufficient capacity, cluster role | EKS Auto Mode launches whose request names only the target AZ, for every NodePool (a pod pinned to the AZ by a volume or a `DoNotSchedule` spread constraint stays `Pending`) | Launch requests that list several AZs. FIS does not apply the fault to a request that spans more than one AZ, so a pod with no zone constraint can still receive a node in the target AZ |
| Insufficient capacity, node group Auto Scaling groups | Managed node group launches in the target AZ | Launches by anything else |
| Custom NodePool exclusion and weight | The custom NodePool launching in the target AZ; pods both pools can place prefer the custom NodePool | A pod that only the built-in `general-purpose` NodePool can place, or that can only run in the target AZ |
| Zonal shift | Auto Mode launches in the target AZ for every NodePool, built-in included, because the AZ is removed from the candidates for every request. Auto Mode also cordons the nodes in the AZ. According to the [EKS zonal shift documentation](https://docs.aws.amazon.com/eks/latest/userguide/zone-shift.html), it also removes the AZ from managed node group Auto Scaling groups, and supports self-managed Karpenter from version 1.12 | Launches before the shift starts or takes effect. A node in the target AZ has been observed launching shortly after a shift became active |

The capacity faults run from the start of the experiment, so they cover single-AZ launch requests before the zonal shift starts and in the window before it takes effect. The zonal shift covers the multi-AZ requests the capacity fault cannot. That is why the template runs both.

### Important: use a custom NodePool, not a built-in one

AWS documents that [the built-in `general-purpose` and `system` NodePools cannot be modified](https://aws.amazon.com/blogs/containers/maximizing-value-with-amazon-eks-auto-mode-strategies-for-visibility-control-and-optimization/). The Kubernetes API accepts a patch to them, but EKS Auto Mode reconciles the built-in NodePool back to its managed configuration. A zone exclusion applied to `general-purpose` was in place two minutes in and had been reverted about four minutes into a fifteen-minute impairment.

**Point `NodePoolName` at a custom NodePool that you own.** A custom NodePool is not reconciled by EKS, so the exclusion holds for the full duration. The automation rejects `general-purpose` and `system`. The capacity fault and the zonal shift are what keep the built-in NodePools from launching in the target AZ. Verify the exclusion survives the whole window before trusting results:

```bash
# Should keep showing the target AZ excluded for the full impairment duration.
watch -n 30 "kubectl get nodepool <YOUR NODEPOOL NAME> -o json \
  | jq '.spec.template.spec.requirements[] | select(.key==\"topology.kubernetes.io/zone\")'"
```

## Prerequisites

Before running this experiment, ensure that:

1. **IAM roles**: create three roles:
   - **FIS execution role**: uses `eks-automode-az-impairment-iam-policy.json`. Starts the SSM automation, drives the network disruption, injects the insufficient capacity errors and starts the zonal shift. It never calls the Kubernetes API.
   - **SSM automation role**: uses `eks-automode-az-impairment-ssm-automation-iam-policy.json`. Orchestrates the automation: validates inputs, launches and terminates the temporary client instance, manages its security group and the temporary cluster security group rule, and sends the `runCommand`s.
   - **EC2 instance profile role**: attach the AWS managed policy `AmazonSSMManagedInstanceCore` (so the SSM Agent registers) **plus** the inline policy `eks-automode-az-impairment-instance-profile-iam-policy.json`. This is the role the Kubernetes work runs under.

   > **Which identity calls the Kubernetes API?** The Kubernetes work runs **on the temporary EC2 instance**, so it uses the **instance profile role's** credentials and the EKS bearer token is minted for that role. The SSM automation role only orchestrates. The EKS access entry and RBAC below must map the instance profile role.

2. **EKS cluster access**: create an EKS access entry for the **instance profile role**, mapped to the username the RBAC binds (`fis-az-impairment-client`):

   ```bash
   aws eks create-access-entry \
     --principal-arn arn:aws:iam::<YOUR AWS ACCOUNT>:role/<YOUR INSTANCE PROFILE ROLE NAME> \
     --username fis-az-impairment-client \
     --cluster-name <YOUR EKS CLUSTER>
   ```

   The FIS execution role and the SSM automation role do not need an access entry.

3. **Kubernetes RBAC**:

   ```bash
   kubectl apply -f eks-automode-az-impairment-rbac.yaml
   ```

   This grants the `fis-az-impairment-client` user permission to read and cordon nodes, list and delete pods, and read and patch NodePools. The username in the `ClusterRoleBinding` must match the `--username` above.

4. **SSM automation document**:

   ```bash
   aws ssm create-document \
     --name "eks-automode-az-impairment-automation" \
     --document-type "Automation" \
     --content file://eks-automode-az-impairment-automation.yaml \
     --document-format YAML
   ```

5. **Zonal shift on the cluster**: enable zonal shift once, and tag the cluster so the FIS target can find it. Enabling it has no effect on the cluster until a shift starts, and ARC zonal shift has [no additional charge](https://aws.amazon.com/application-recovery-controller/pricing/). ARC zonal shift support for EKS Auto Mode was [announced in July 2026](https://aws.amazon.com/about-aws/whats-new/2026/07/eks-auto-mode-arc-zonal-shift/).

   ```bash
   aws eks update-cluster-config --name <YOUR EKS CLUSTER> \
     --zonal-shift-config enabled=true
   aws eks tag-resource \
     --resource-arn arn:aws:eks:<YOUR REGION>:<YOUR AWS ACCOUNT>:cluster/<YOUR EKS CLUSTER> \
     --tags FIS-Ready=True
   ```

   If your cluster cannot use zonal shift, delete the `wait-for-recovery-action` and `shift-away-from-az` actions and the `eks-cluster-for-zonal-shift` target from the template. The built-in NodePools can then launch nodes in the target AZ from requests that list several AZs.

6. **Multi-AZ deployment**: the cluster must have subnets in at least 2 AZs, with workloads distributed across them. **3 AZs is recommended**: with `DoNotSchedule` and `maxSkew: 1`, a 3-AZ cluster lets evicted pods redistribute across both surviving AZs, whereas a 2-AZ cluster leaves them `Pending`. See [Number of Availability Zones](#3-number-of-availability-zones).

7. **Workload must be able to fail over** into the surviving AZs. See [Cluster configuration determines the outcome](#cluster-configuration-determines-the-outcome). This is a property of your workload, not of the experiment.

8. **NodePool**: identify the custom NodePool your workloads use (`kubectl get nodepools`). It must not be `general-purpose` or `system`, and its zone requirement must use the `In` operator.

9. **Tag the target subnets**: the network disruption resolves its target by tag, so the subnet(s) in the AZ you want to impair must carry `FIS-Ready=True`:

   ```bash
   aws ec2 create-tags \
     --resources <YOUR SUBNET ID IN TARGET AZ> \
     --tags Key=FIS-Ready,Value=True
   ```

10. **In-VPC client connectivity to the EKS API**: the automation launches a short-lived EC2 instance **inside your VPC** (`aws:runInstances` into `SubnetId`) and runs all Kubernetes operations on it with `aws:runCommand`. The traffic originates inside the VPC, so the experiment works against a **private** EKS endpoint without opening public access. For this to work:
    - **`SubnetId`** must be in the cluster VPC and **not in the target AZ**. The network disruption denies traffic in the impaired AZ, and a client there would lose the API too. It must reach the Systems Manager endpoints (NAT gateway, or the `ssm`, `ssmmessages` and `ec2messages` interface VPC endpoints) and the Amazon Linux package repositories (NAT, or an S3 gateway endpoint).
    - The cluster must have **private endpoint access enabled** (`endpointPrivateAccess: true`). Public access is not required.
    - **`ClusterSecurityGroupId`**: the private endpoint's network interfaces sit behind the cluster security group, which by default only accepts traffic from itself. The automation adds a temporary tcp/443 rule from the client's security group to that security group and removes it during cleanup. Leave the parameter empty to use the security group EKS created for the cluster, or set it if you use a different one.
    - **`InstanceProfileName`** must be an existing instance profile whose role has `AmazonSSMManagedInstanceCore` and the permissions from prerequisite 1, plus the access entry and RBAC from prerequisites 2 and 3.

11. **Other launchers of nodes**: see [Blocking launches in the target AZ](#blocking-launches-in-the-target-az) if your cluster also has managed node groups or self-managed Karpenter.

## Validating SSM-to-EKS connectivity

The automation checks the path itself before it changes anything: the `ValidateEKSAccess` step is read-only, and confirms the client can authenticate to the Kubernetes API and holds every permission the run needs. If it fails, the run ends without having changed the cluster. Distinguish the failure modes:

- A **connection timeout** at `ValidateEKSAccess` means packets from the client subnet never reached the API server. Check that private endpoint access is enabled, that `SubnetId` can route to it, and that the cluster security group accepts the temporary tcp/443 rule (`ClusterSecurityGroupId`).
- A `403` means the network path works but the **instance profile role** lacks Kubernetes access. Fix its EKS access entry, or the subject in `eks-automode-az-impairment-rbac.yaml`.
- If `WaitForSSMAgent` times out, the instance could not reach the SSM service endpoints. Add a NAT path or the `ssm`, `ssmmessages` and `ec2messages` interface VPC endpoints to `SubnetId`.
- The automation runs while the network disruption is active. Connections to the API server's network interface in the target AZ time out, and the client retries them against the other addresses. A timeout that persists across all retries is not caused by the disruption, provided `SubnetId` is in a surviving AZ. To validate the path on its own, run the SSM automation directly, without the FIS experiment.

**Check the cluster's endpoint access mode:**

```bash
aws eks describe-cluster --name <YOUR EKS CLUSTER> \
  --query 'cluster.resourcesVpcConfig.{public:endpointPublicAccess,private:endpointPrivateAccess,cidrs:publicAccessCidrs}'
```

**Why this design.** The ephemeral in-VPC instance means the Kubernetes API traffic originates inside the VPC and is subject to your security groups and the EKS private endpoint, so the cluster's API can stay private. The instance is created at the start of the run and removed at the end, with its security group and the temporary cluster security group rule, on completion, failure or cancel.

## Cluster configuration determines the outcome

This experiment always does the same things on the Kubernetes side: cordon the nodes in the target AZ, exclude that AZ from the custom NodePool, and delete the pods there. What you *observe* — a service that rides through the impairment, or one that runs degraded — is decided entirely by **your workload's configuration**, not by anything in the experiment template.

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

### Which behavior to expect

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

The number of AZs in your cluster changes both the blast radius and the redistribution behavior during impairment.

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

This is realistic production behavior: after an AZ recovers, workloads drift from their intended spread until an explicit action redistributes them. See [Recovery Behavior](#recovery-behavior) for how to rebalance.

## How It Works

The network disruption and the capacity faults start with the experiment. After the detection delay, the zonal shift and the SSM automation start together. The shift, the network disruption and the capacity faults end at the same time.

### Experiment Flow

```text
t=0       disrupt-az-network (15 min): all traffic in the AZ's subnets is denied
          insufficient-capacity-in-az, insufficient-capacity-in-az-node-groups (15 min)
          wait-for-recovery-action (1 min)

t=1m      wait-for-recovery-action ends, and together:
            - shift-away-from-az (14 min): within about a minute, Auto Mode
              stops launching in the AZ for every NodePool and cordons the
              AZ's nodes
            - cordon-and-exclude-az (SSM automation) starts

SSM automation:
t=1m      ValidateInputs, CreateSecurityGroup, AuthorizeEKSAccess
t=~1.5m   LaunchClientInstance, WaitForSSMAgent, BootstrapClient
t=~4m     ValidateEKSAccess (read-only preflight)
t=~4m     SnapshotAndImpair: record the original state, cordon the AZ's nodes,
          patch the custom NodePool (exclude the AZ, raise the weight),
          delete the pods on those nodes. The shift has applied, so their
          replacements go to the surviving AZs.

t=15m     network disruption, zonal shift and capacity faults end together
t=~18m    SSM WaitForDuration ends -> RestoreNodePool, CleanupResources
```

**Why the pods are deleted after the zonal shift starts:** EKS applies a zonal shift by polling, so it takes up to about a minute to take effect. In testing, Auto Mode still launched nodes in the target AZ for pods that appeared up to 52 seconds after the shift started. Starting the automation with the shift means its client setup (about three minutes) passes before any pod is deleted. The replacement pods are then placed in the surviving AZs, and none of them is given a new node in the impaired AZ. If pods were deleted before the shift applied, a replacement with no zone constraint could get a new node in the impaired AZ from a launch request that lists several AZs, which the capacity fault does not block.

**Why the automation deletes pods at all:** the network disruption allows traffic within the subnet, so nodes in the target AZ can still reach the API server's network interface in the same subnet. They may stay `Ready`, and Kubernetes would then not evict their pods on its own. The automation deletes them to simulate the sudden loss of the AZ's workloads.

**Kubernetes calls during the outage:** the automation now makes its Kubernetes changes while the network is disrupted. The private endpoint also resolves to the API server's network interface in the target AZ, and connections to that address time out. The client retries failed connections against the other addresses, so the changes complete. In testing, the impair step finished normally during the outage.

**Why pods are deleted only after the NodePool is patched:** cordoning marks the existing nodes in the AZ unschedulable and the NodePool patch stops the custom NodePool launching there. Only then are pods deleted, so Kubernetes has no placement option left in the impaired AZ. The cordon, patch and delete run as one program on the in-VPC instance, so the ordering holds within a single process.

### Actions Detail

| Action | Action ID | Description | Starts |
|--------|-----------|-------------|--------|
| `disrupt-az-network` | `aws:network:disrupt-connectivity` | Denies all traffic on the target AZ's subnets with network ACLs | t=0 |
| `insufficient-capacity-in-az` | `aws:ec2:api-insufficient-instance-capacity-error` | Fails EC2 launches in the target AZ made by the roles in the `node-launch-roles` target | t=0 |
| `insufficient-capacity-in-az-node-groups` | `aws:ec2:asg-insufficient-instance-capacity-error` | Fails launches in the target AZ for the managed node group Auto Scaling groups | t=0 |
| `wait-for-recovery-action` | `aws:fis:wait` | Detection time before the operator recovery action | t=0 |
| `shift-away-from-az` | `aws:arc:start-zonal-autoshift` | Starts a zonal shift for the cluster away from the target AZ. FIS renews it every minute while the action runs and cancels it when the action ends or the experiment is stopped | after `wait-for-recovery-action` |
| `cordon-and-exclude-az` | `aws:ssm:start-automation-execution` | Launches an in-VPC client, validates access, snapshots and impairs the Kubernetes side, waits, restores and cleans up | after `wait-for-recovery-action` |

### SSM Automation Document

The automation (`eks-automode-az-impairment-automation`) manages the Kubernetes side. All Kubernetes API calls run from an ephemeral EC2 instance inside your VPC.

| Step | What it does |
|------|--------------|
| `ValidateInputs` | Checks the AZ, NodePool name, VPC, subnet and security group against the cluster before anything is created |
| `CreateSecurityGroup` | Creates a temporary security group for the client, tagged with the execution ID |
| `AuthorizeEKSAccess` | Adds tcp/443 from the client security group to the cluster security group |
| `LaunchClientInstance`, `WaitForSSMAgent`, `BootstrapClient` | Launches the instance in `SubnetId`, waits for the SSM Agent, installs the Python modules and fails if an install fails |
| `ValidateEKSAccess` | Read-only: authenticates and checks every Kubernetes permission the run needs |
| `SnapshotAndImpair` | Records the NodePool (zone requirement and weight) and each target-AZ node (UID and whether it was already cordoned), then cordons the nodes, patches the NodePool with a JSON patch that tests the current value first, reads the NodePool back, and deletes the non-system pods |
| `WaitForDuration` | Holds the impairment for `Duration` |
| `RestoreNodePool` | Reverts only what the run changed (see [Recovery Behavior](#recovery-behavior)) |
| `CleanupResources` | Finds the rule, instance and security group by execution tag, removes them, waits for the instance to terminate, retries the security group delete, and fails if anything remains |

`SnapshotAndImpair` and `WaitForDuration` route failures and cancellation to `RestoreNodePool`, and every earlier step routes failures to `CleanupResources`, so a cancel at any point restores the cluster and removes the temporary resources.

### Why This Experiment Uses No `aws:eks:pod` Actions

FIS resolves `aws:eks:pod` targets by **namespace and label selector**, and the [FIS documentation](https://docs.aws.amazon.com/fis/latest/userguide/eks-pod-actions.html) states you *"can't identify targets of type `aws:eks:pod` in your experiment template using resource ARNs or resource tags."* Pods do not inherit their node's `topology.kubernetes.io/zone` label (that label exists on nodes only), so a selector such as `app=myapp,topology.kubernetes.io/zone=ap-southeast-2a` matches zero pods. That leaves no way to scope a pod action to one AZ:

- An AZ-qualified label selector resolves to nothing, and with `emptyTargetResolutionMode: skip` the action silently does nothing
- Dropping the AZ term and targeting `app=myapp` deletes pods in the healthy AZs too, which degrades the capacity the experiment is meant to show survives

So the automation deletes the pods itself: it lists the pods on nodes in the target AZ and deletes them with `gracePeriodSeconds=0`. This scopes the deletion to the AZ with no dependency on FIS pod targeting. For the same reason there is no `aws:eks:pod-network-packet-loss` action: the network ACLs already block all traffic in the AZ, which is broader than per-pod packet loss.

If you add `aws:eks:pod` actions to a fork, all of them fail unless the target pods set `readOnlyRootFilesystem: false` in their `securityContext`, and you need a Kubernetes service account, an EKS access entry for the FIS role and the matching RBAC. None of these are installed by this experiment.

## Blocking launches in the target AZ

The insufficient capacity actions act on the **IAM role (or Auto Scaling group) that makes the EC2 launch call**, so every launcher in your cluster needs to be a target.

- **EKS Auto Mode**: Auto Mode launches instances with the **EKS cluster role** (the role your cluster was created with). Set the `node-launch-roles` target to that role's ARN and the `AllowInsufficientCapacityForNodeLaunchRoles` statement in the FIS role policy to the same ARN. CloudTrail shows these calls as `CreateFleet` made by that role and invoked by `eks.amazonaws.com`.
- **Managed node groups**: their Auto Scaling groups launch the instances. The `managed-node-group-asgs` target selects them by the tag `k8s.io/cluster-autoscaler/<YOUR EKS CLUSTER>` set to `owned`. Check that your node group's Auto Scaling group has the tag:

  ```bash
  aws autoscaling describe-tags \
    --filters Name=key,Values=k8s.io/cluster-autoscaler/<YOUR EKS CLUSTER> \
    --query 'Tags[].ResourceId'
  ```

  The template sets `emptyTargetResolutionMode: skip`, so a cluster with no managed node groups runs without error and the node group action does nothing.
- **Self-managed Karpenter, or any other component that launches EC2 instances**: these use other IAM roles. Add each role's ARN to the `resourceArns` of the `node-launch-roles` target, and add the same ARN to the `ec2:FisTargetArns` condition of the `AllowInsufficientCapacityForNodeLaunchRoles` statement.

The fault applies only to launch requests that name a single AZ. A request that lists several AZs is not affected, which is why the zonal shift is part of the experiment. The zonal shift also restricts managed node groups and self-managed Karpenter (version 1.12 or later) to the healthy AZs once it takes effect; the capacity faults cover these launchers before then. This experiment has tested the managed node group fault, but not the zonal shift's effect on managed node groups or self-managed Karpenter. Nodes already running in the AZ are not affected by the capacity faults; the network disruption handles those. While the fault is active, Auto Mode logs an `InsufficientCapacityError` event about every 40 seconds as it retries. Once the fault ends, Auto Mode launches the nodes that pods were waiting for within about 30 seconds.

### What the zonal shift changes

Beyond blocking launches, the zonal shift changes what the experiment measures:

- Auto Mode cordons every node in the shifted AZ and excludes the AZ from launches for every NodePool. Managed node group Auto Scaling groups are restricted to the healthy AZs.
- The ARC zonal shift also moves in-cluster service traffic away from pods in the AZ, so the experiment covers the AZ failure plus the documented recovery action, not only the cluster's unaided response. To measure how long the cluster runs before that recovery action starts, set `wait-for-recovery-action` to the detection time you want to test.
- **When the shift ends, Auto Mode uncordons every node in the AZ, including a node an operator had cordoned before the run.** During the shift Auto Mode adds an `eks-arc-zonal-shift/impaired-zone` taint and marks the nodes unschedulable; when the shift ends it removes both, and the operator's own cordon goes with them. The automation restores only what it cordoned itself and skips a node that was already cordoned, but the end of the shift still clears that cordon. Note which nodes are cordoned before the run and cordon them again afterwards, or drain them out of the AZ before the run.
- ARC zonal shift has [no additional charge](https://aws.amazon.com/application-recovery-controller/pricing/).

## Targets

| Target Name | Resource Type | Selection | Description |
|-------------|---------------|-----------|-------------|
| `subnets-in-target-az` | `aws:ec2:subnet` | Tag `FIS-Ready=True`, scoped to the target AZ | Subnets whose traffic is denied |
| `node-launch-roles` | `aws:iam:role` | ARN | The EKS cluster role (and any other role that launches your nodes) |
| `managed-node-group-asgs` | `aws:ec2:autoscaling-group` | Tag `k8s.io/cluster-autoscaler/<YOUR EKS CLUSTER>` = `owned` | Auto Scaling groups of managed node groups |
| `eks-cluster-for-zonal-shift` | `aws:arc:zonal-shift-managed-resource` | Tag `FIS-Ready=True`, resource type `EKS` | The cluster the zonal shift applies to. `zonalAutoshiftStatus` is `ANY`, so the shift works whether or not zonal autoshift is enabled on the cluster |

FIS cannot combine a fixed resource ARN with the parameters of the zonal shift target, so the cluster is selected by its `FIS-Ready=True` tag. Pod termination is handled by the SSM automation, not by a FIS `aws:eks:pod` target (see [Why This Experiment Uses No `aws:eks:pod` Actions](#why-this-experiment-uses-no-awsekspod-actions)).

### Target Requirements

- The subnets must carry `FIS-Ready=True` and be in the AZ named by the target's `availabilityZoneIdentifier` and the automation's `TargetAZ`, so the network disruption and the Kubernetes-level impairment affect the same AZ
- The cluster must carry `FIS-Ready=True` and have zonal shift enabled (prerequisite 5)
- Nodes must carry the standard `topology.kubernetes.io/zone` label (EKS applies it automatically)
- The instance profile role must have Kubernetes API access through an EKS access entry (username `fis-az-impairment-client`) and the RBAC in `eks-automode-az-impairment-rbac.yaml`

## Parameters to Configure

Replace these placeholders before importing the template:

| Placeholder | Description |
|-------------|-------------|
| `<YOUR AWS ACCOUNT>` | Your 12-digit AWS account ID |
| `<YOUR REGION>` | AWS Region of the cluster (for example `ap-southeast-2`) |
| `<YOUR FIS ROLE NAME>` | FIS execution role name |
| `<YOUR SSM AUTOMATION ROLE NAME>` | SSM automation role name |
| `<YOUR INSTANCE PROFILE ROLE NAME>` | Role behind the client's instance profile (referenced by the SSM automation role's `iam:PassRole`) |
| `<YOUR INSTANCE PROFILE NAME>` | Instance profile for the client instance |
| `<YOUR EKS CLUSTER>` | EKS cluster name |
| `<YOUR EKS CLUSTER ROLE NAME>` | The EKS cluster IAM role that Auto Mode uses to launch nodes (add other launch roles as described in [Blocking launches in the target AZ](#blocking-launches-in-the-target-az)) |
| `<YOUR TARGET AZ>` | AZ to impair (for example `ap-southeast-2a`) |
| `<YOUR SUBNET ID IN TARGET AZ>` | Subnet(s) in the target AZ to tag `FIS-Ready=True` |
| `<YOUR CLIENT SUBNET ID>` | Subnet in a surviving AZ for the client instance (the `SubnetId` document parameter) |
| `<YOUR VPC ID>` | VPC of the cluster (the `VpcId` document parameter) |
| `<YOUR NODEPOOL NAME>` | Name of a custom NodePool |

The `ClusterSecurityGroupId` document parameter is empty by default, which uses the cluster security group EKS created. `ImpairNodePoolWeight` is `100` by default (`0` leaves the NodePool weight unchanged). The automation does not accept the built-in `general-purpose` or `system` NodePools.

### Timing parameters

| Setting | Default | Meaning |
|---------|---------|---------|
| `disrupt-az-network` `duration` | `PT15M` | Length of the network disruption |
| Capacity actions `duration` | `PT15M` | The network `duration` |
| `wait-for-recovery-action` | `PT1M` | Detection time before the zonal shift and the automation start |
| `shift-away-from-az` `duration` | `PT14M` | Network `duration` minus the detection time, so the shift ends with the network disruption |
| SSM `Duration` | `PT14M` | The shift `duration`. The automation impairs about three minutes after it starts, so restore runs about three minutes after the network returns |
| SSM action `maxDuration` | `PT30M` | `Duration` plus 15 minutes for setup, restore and cleanup |

With the defaults the network is down from t=0 to t=15 minutes, the zonal shift runs from t=1 to t=15 minutes, and pods are deleted at about t=4 minutes. You can raise `wait-for-recovery-action` to test a longer detection time; the pods are still deleted only after the shift starts. Keep the shift, capacity fault and network durations ending together, and keep SSM `Duration` long enough for restore to run after the network returns.

### Optional hardening

The templates keep the cluster, account, VPC and subnet in `<YOUR ...>` placeholders. If you want a run to refuse any other target, scope the IAM policies to one cluster ARN (already the case for the EKS and Auto Scaling statements) and rely on the access entry, which exists only on the intended cluster. An allowlist passed as a parameter adds no protection, because whoever starts the run supplies both the targets and the allowlist.

## How Pods in the Target AZ Are Selected

No pod label selector configuration is required. The SSM automation resolves the target pods itself:

1. Lists nodes matching `topology.kubernetes.io/zone=<TargetAZ>`
2. For each of those nodes, lists pods via `fieldSelector=spec.nodeName=<node>`
3. Deletes each pod with `gracePeriodSeconds=0`, skipping the `kube-system`, `kube-node-lease` and `kube-public` namespaces and pods owned by a DaemonSet

This means **all non-system pods on nodes in the target AZ are deleted**, across every namespace. If you need to limit the blast radius to specific workloads, add a namespace or label filter to the pod-deletion logic in the `SnapshotAndImpair` step of `eks-automode-az-impairment-automation.yaml`.

## Stop Conditions

The experiment does not include stop conditions by default. It will continue until all actions complete (approximately 19 minutes with the default timing).

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

1. **Network**: FIS restores the original network ACLs.
2. **Zonal shift**: FIS cancels the shift when the action ends or the experiment is stopped. Auto Mode then uncordons the nodes in the AZ.
3. **Capacity faults**: they end with their duration. Auto Mode launches the nodes that pods were waiting for within about 30 seconds.
4. **NodePool**: `RestoreNodePool` restores the zone requirement and the weight to their recorded original values (or removes the weight if the NodePool had none).
5. **Nodes**: `RestoreNodePool` uncordons only the nodes this run cordoned. It does not touch a node that was already cordoned when the run started, or a node that was replaced or no longer exists. The end of the zonal shift does uncordon a node an operator cordoned before the run; see [What the zonal shift changes](#what-the-zonal-shift-changes).
6. **Temporary resources**: the cluster security group rule, the client instance and its security group are removed, and the step fails if any remains.
7. **Pods**: behavior depends on your workload configuration, described in [Cluster configuration determines the outcome](#cluster-configuration-determines-the-outcome):
   - The pods deleted from the target AZ are not recreated there. Their replacements run in the surviving AZs, and Kubernetes does not move a running pod back when the AZ recovers. The exception is a pod that can only run in the target AZ (a zone node selector, or an EBS volume in that AZ): it stays `Pending` during the test and starts in the AZ once it recovers. A later rollout restart or an Auto Mode consolidation can also reschedule pods into any AZ.
   - With `ScheduleAnyway`, pods that failed over stay in the surviving AZs. The spread is a preference, so a running pod is never moved to satisfy it.
   - With `DoNotSchedule` (2 AZs), pods left `Pending` schedule into the restored AZ as soon as the NodePool is restored and Auto Mode provisions a node there.
   - With `DoNotSchedule` (3 AZs), pods already rescheduled into the surviving AZs stay in their 0/3/3 distribution, because topology spread constraints are evaluated only at scheduling time.

### Restore status and failure signal

`SnapshotAndImpair` prints the recorded state as a `SNAPSHOT` line, then a JSON summary with `Status: IMPAIRED`. `RestoreNodePool` prints one of these:

- `{"Status": "RESTORED", ...}`: the NodePool matches its original state and the nodes this run cordoned are uncordoned.
- `{"Status": "NOTHING_TO_RESTORE"}`: `SnapshotAndImpair` made no changes, for example because input validation or the preflight failed.
- `MANUAL RECOVERY REQUIRED`: the restore could not complete, and the step fails so the failure shows in the automation execution and can trip an alarm or a stop condition. The output includes an `ORIGINAL STATE` line. This also happens if something else changed the NodePool during the run (EKS reconciliation, a GitOps controller or an operator): the automation leaves it as it found it, because it cannot tell which change is safe to revert.

**Manual recovery.** Read the `ORIGINAL STATE` and `SNAPSHOT` lines from the step output in CloudWatch Logs (log group `/aws/ssm/eks-automode-az-impairment`). Set the NodePool's `topology.kubernetes.io/zone` requirement and `spec.weight` back to the values under `original`, and `kubectl uncordon` any node under `nodes` that was not already unschedulable. If the cleanup step failed, delete the leftover instance and security group (found by the automation execution ID tag) and remove the tcp/443 rule that references the client security group from the cluster security group.

**To rebalance pods that stayed put:**

```bash
kubectl rollout restart deployment/<your-deployment-name>
```

This cycles the pods so the scheduler places them again across all AZs. A soft constraint does not guarantee a spread: if the surviving AZ has headroom for every replica, the scheduler may place them all there again. In production this is the equivalent of a post-incident rebalancing step.

**Why no automatic rebalance occurs:** topology spread constraints influence where a pod is initially placed but never evict a running pod to re-satisfy the constraint. With EKS Auto Mode's `consolidationPolicy: WhenEmpty`, no node is provisioned in the restored AZ because no scheduling demand exists there. After an AZ recovers, workloads stay where they failed over until an operator rebalances them (rollout restart, scaling event or a descheduler).

Recovery time depends on node provisioning, pod startup time, health check grace periods and load balancer target registration.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to your EKS workload health.
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of the AZ impairment, and an alarm on the SSM automation execution failing.
4. Adding a stop condition tied to the alarm to halt the experiment if critical thresholds are breached.
5. Checking that every component that launches your nodes (managed node groups, self-managed Karpenter) is a target of the capacity faults.
6. Setting `wait-for-recovery-action` to the detection time you want to test, and adjusting the shift and SSM durations to match.
7. Narrowing the blast radius if needed. By default the automation deletes all non-system pods on nodes in the target AZ, across every namespace. Add a namespace or label filter in the pod-deletion logic of `SnapshotAndImpair`.
8. **Testing in a non-production environment first** to validate automation behavior and timing.
9. Documenting expected versus actual behavior to build an AZ failure runbook.
10. Gradually increasing scope (longer duration, more namespaces, multiple NodePools).

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).

## Files in This Directory

| File | Description |
|------|-------------|
| `README.md` | This documentation file |
| `AWSFIS.json` | Template version marker for fis-template-library-tooling |
| `eks-automode-az-impairment-template.json` | FIS experiment template definition |
| `eks-automode-az-impairment-automation.yaml` | SSM Automation document: launches an ephemeral in-VPC client, validates access, impairs the Kubernetes side, waits, restores and cleans up |
| `eks-automode-az-impairment-iam-policy.json` | IAM policy for the FIS execution role (network disruption, capacity faults, zonal shift, SSM automation start) |
| `eks-automode-az-impairment-ssm-automation-iam-policy.json` | IAM policy for the SSM automation role (orchestration) |
| `eks-automode-az-impairment-instance-profile-iam-policy.json` | Inline IAM policy for the instance profile role (EKS describe and Kubernetes API access); attach alongside `AmazonSSMManagedInstanceCore` |
| `eks-automode-az-impairment-rbac.yaml` | Kubernetes RBAC for the instance profile role (bound through the `fis-az-impairment-client` username) |
| `fis-iam-trust-relationship.json` | Trust policy for the FIS service |
| `ssm-iam-trust-relationship.json` | Trust policy for the SSM service |
