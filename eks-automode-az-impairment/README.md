# AWS Fault Injection Service Experiment: EKS Auto Mode Availability Zone Impairment

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

When an Availability Zone experiences an impairment affecting an EKS Auto Mode cluster, the workload should sustain the failure by running its replicas in the remaining healthy AZs — scaling up there as needed — rather than losing capacity for the duration. Specifically:

- When network connectivity is disrupted in the target AZ, pods in that AZ should become unreachable
- When nodes in the target AZ are cordoned and the NodePool is patched to exclude the AZ, EKS Auto Mode should not provision new nodes in the impaired AZ
- When pods are deleted in the target AZ, Kubernetes should reschedule them into the healthy AZs only, scaling up there if required
- The application should remain available throughout the experiment, serving from the healthy AZs
- When the NodePool is restored and nodes are uncordoned, capacity should become available in that AZ again

Whether the third and fourth points hold depends on your workload's topology spread constraints, the capacity headroom in the surviving AZs and, with `DoNotSchedule`, whether another NodePool can launch into the target AZ. See [Cluster configuration determines the outcome](#cluster-configuration-determines-the-outcome). A workload that cannot fail over will instead run at reduced capacity for the duration, and the experiment will still report success.

## Background: Why This Is Different from Standard EKS

EKS Auto Mode manages the underlying EC2 instances on your behalf — you don't have direct access to stop or terminate the nodes. This means traditional AZ failure tests (stopping EC2 instances) won't work because:

1. You can't directly access or stop the AWS-managed EC2 instances
2. Simply deleting pods doesn't simulate the network impairment aspect of an AZ failure
3. EKS Auto Mode will immediately try to provision new nodes, potentially back in the impaired AZ

This experiment uses a "trifecta" approach to realistically simulate an AZ failure:

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

1. **IAM Roles**: Create three roles:
   - **FIS execution role** — uses `eks-automode-az-impairment-iam-policy.json`. Starts the SSM automation and drives the NACL network-disruption action. It never calls the Kubernetes API.
   - **SSM automation role** — uses `eks-automode-az-impairment-ssm-automation-iam-policy.json`. Orchestrates the automation: launches/terminates the ephemeral client instance, manages its security group, and sends the `runCommand`s.
   - **EC2 instance profile role** — attach the AWS managed policy `AmazonSSMManagedInstanceCore` (so the SSM Agent registers) **plus** the inline policy `eks-automode-az-impairment-instance-profile-iam-policy.json` (grants `eks:DescribeCluster`, `eks:AccessKubernetesApi`, `ec2:DescribeSubnets`, `sts:GetCallerIdentity`, and write access to the `/aws/ssm/AWS-RunShellScript` CloudWatch Logs log group for the automation's command output). This is the role the Kubernetes work actually runs under — see the note below.

   > **Which identity calls the Kubernetes API?** The cordon/patch/delete/restore logic runs **on the ephemeral EC2 instance**, so it uses the **instance profile role's** credentials, and the EKS bearer token is minted for that role. The SSM automation role only orchestrates; it does not call the Kubernetes API. Therefore the EKS Access Entry and RBAC below must map the **instance profile role**, not the SSM automation role.

2. **EKS Cluster Access**: Grant the **instance profile role** Kubernetes API access by creating an EKS Access Entry mapped to the username the RBAC binds (`fis-az-impairment-client`):
   ```bash
   aws eks create-access-entry \
     --principal-arn arn:aws:iam::<ACCOUNT>:role/<YOUR INSTANCE PROFILE ROLE NAME> \
     --username fis-az-impairment-client \
     --cluster-name <YOUR EKS CLUSTER>
   ```
   The FIS execution role and the SSM automation role do **not** need an access entry — neither calls the Kubernetes API.

3. **Kubernetes RBAC**: Apply the RBAC configuration to your cluster:
   ```bash
   kubectl apply -f eks-automode-az-impairment-rbac.yaml
   ```
   This grants the client (the `fis-az-impairment-client` user mapped to the instance profile role) permission to cordon/uncordon nodes, delete pods, and patch the NodePool. The username in the RBAC `ClusterRoleBinding` must match the `--username` in the access entry above.

4. **SSM Automation Document**: Deploy the SSM automation document:
   ```bash
   aws ssm create-document \
     --name "eks-automode-az-impairment-automation" \
     --document-type "Automation" \
     --content file://eks-automode-az-impairment-automation.yaml \
     --document-format YAML
   ```

5. **Multi-AZ Deployment**: Your EKS Auto Mode cluster must have subnets in at least 2 different AZs, with workloads distributed across them. **3 AZs is recommended**: with `DoNotSchedule` and `maxSkew: 1`, a 3-AZ cluster lets evicted pods spread across both surviving AZs. With `DoNotSchedule` and either AZ count, Auto Mode adds nodes for the evicted pods only if no other NodePool, such as an enabled built-in one, can launch into the target AZ; otherwise they run only on spare capacity of the existing nodes. See [Number of Availability Zones](#3-number-of-availability-zones).

6. **Workload must be able to fail over into the surviving AZs** — see [Cluster configuration determines the outcome](#cluster-configuration-determines-the-outcome) below. This is a property of *your* workload, not of the experiment, and it decides whether you observe a surviving service or a degraded one.

7. **NodePool Identification**: Identify which NodePool your workloads use:
   ```bash
   kubectl get nodepools
   ```
   This must be a **custom NodePool**, not the built-in `general-purpose` or `system` pools — see [Important: use a custom NodePool](#important-use-a-custom-nodepool-not-a-built-in-one) above. Built-in pools are reconciled by EKS and the AZ exclusion will be silently reverted mid-experiment. If the NodePool has a `topology.kubernetes.io/zone` requirement, it must use the `In` operator: the automation removes the target AZ from that requirement's values, which does not exclude the AZ under `NotIn`.

8. **Tag the target subnet**: The FIS experiment resolves its target by tag, so the VPC subnet in the AZ you want to impair must carry the tag `FIS-Ready=True`. The template also scopes the target to a single AZ via the `availabilityZoneIdentifier` parameter, so only the FIS-Ready subnet(s) in `<YOUR TARGET AZ>` are selected. Tag it with:
   ```bash
   aws ec2 create-tags \
     --resources <YOUR SUBNET ID IN TARGET AZ> \
     --tags Key=FIS-Ready,Value=True
   ```
   The template scopes the network-disruption target to subnets tagged `FIS-Ready=True` in `<YOUR TARGET AZ>`, so the deny-NACL is only ever associated with a subnet you have explicitly marked.

9. **In-VPC client connectivity to the EKS API**: The SSM Automation launches a short-lived EC2 instance **inside your VPC** (via `aws:runInstances` into `SubnetId`) and runs all Kubernetes operations on that instance via `aws:runCommand`. Because the traffic originates from inside the VPC, the experiment works against a **private** EKS endpoint without opening public access. For this to work:
   - **`SubnetId`** must be a subnet that (a) can reach the cluster's Kubernetes API endpoint — i.e. the cluster has **private endpoint access enabled** and this subnet is allowed to reach it — and (b) can reach the AWS Systems Manager endpoints so the SSM Agent can register and receive the command. The subnet also needs outbound internet access, for example through a **NAT gateway**: the client installs packages from the Amazon Linux repositories and PyPI, and calls the EKS, EC2 and CloudWatch Logs APIs. The `com.amazonaws.<region>.ssm`, `.ssmmessages` and `.ec2messages` interface VPC endpoints alone are not enough: in testing, with only those endpoints and no route out of the VPC, the SSM Agent registered, but `BootstrapClient` failed after 24 minutes and the automation made no Kubernetes call.
   - **Do not use a subnet in the target AZ.** The network-disruption action denies traffic in the impaired AZ's subnets; launching the client there would sever it from the API too. Use a subnet in a surviving AZ.
   - **Allow the client subnet in the cluster security group.** With a private endpoint, the cluster security group must allow inbound TCP 443 from the CIDR of `SubnetId`. The automation launches the client in a new security group that it creates for each run, so a rule that references a security group cannot match it. Without this rule, `CordonPatchDelete` fails with a connection timeout. Find the group with `aws eks describe-cluster --name <YOUR EKS CLUSTER> --query cluster.resourcesVpcConfig.clusterSecurityGroupId`, then add the rule with `aws ec2 authorize-security-group-ingress --group-id <CLUSTER SECURITY GROUP ID> --protocol tcp --port 443 --cidr <SUBNETID CIDR>`.
   - **`InstanceProfileName`** must be an existing EC2 instance profile whose role has `AmazonSSMManagedInstanceCore` (so the instance registers with SSM) **plus** the inline permissions listed in prerequisite 1 (`eks:DescribeCluster`, `eks:AccessKubernetesApi`, `ec2:DescribeSubnets`, `sts:GetCallerIdentity`, and the CloudWatch Logs permissions) and the EKS Access Entry/RBAC from prerequisites 2–3, since the Kubernetes calls run under this role.
   - The **instance profile role's** EKS Access Entry (step 2) and RBAC (step 3) authorize the Kubernetes calls the instance makes. A connection **timeout** at the `CordonPatchDelete`/`RestoreNodePool` step means the subnet cannot reach the API endpoint (fix reachability); a `403` means the network path works but the instance profile role's access entry/RBAC is missing or misnamed. **Validate this path before a full run** — see [Validating SSM-to-EKS connectivity](#validating-ssm-to-eks-connectivity) below.

## Validating SSM-to-EKS connectivity

The automation's Kubernetes calls run from an **ephemeral EC2 instance launched inside your VPC** (`CordonPatchDelete` and `RestoreNodePool` use `aws:runCommand` on that instance), so the traffic to the cluster's Kubernetes API endpoint originates from `SubnetId` and is subject to your security groups and the EKS **private** endpoint — not to public endpoint access. Distinguish the two failure modes:

- A **connection timeout** at `CordonPatchDelete` or `RestoreNodePool` means packets from the client subnet never reached the API server — a *network reachability* problem (the cluster lacks private endpoint access, or the subnet/security group/route cannot reach it). The most common cause is a missing cluster security group rule for the client subnet (see prerequisite 9). Each Kubernetes request waits at most 5 seconds to connect to each address of the endpoint and at most 30 seconds between reads of the response, and a failed connection is retried up to 3 times. In testing, with the API unreachable and two endpoint addresses, each of these steps failed in about 50 seconds, and the instance and security group were still cleaned up.
- A `403` means the network path works but the **instance profile role** lacks Kubernetes access — fix its EKS Access Entry / the subject in `eks-automode-az-impairment-rbac.yaml` in that case.

Two other reachability notes:

- If `WaitForSSMAgent` times out, the launched instance could not reach the SSM service endpoints, through a NAT gateway or the `ssm`, `ssmmessages` and `ec2messages` interface VPC endpoints. If `BootstrapClient` fails, it could not download packages, which needs the outbound internet access described in prerequisite 9.
- The private endpoint name resolves to the addresses of the control-plane network interfaces that EKS creates in the cluster subnets, and one of them can be in the target AZ's subnet. While the deny-NACL is in place, that address does not answer from the rest of the VPC: in testing, every probe of that address from the other subnets taken while the deny-NACL was in place timed out, while the other addresses answered. The automation's client stops waiting for an address after 5 seconds and tries the next one, but other clients in your VPC that use the endpoint during the experiment can see connection timeouts.

**Check the cluster's endpoint access mode:**
```bash
aws eks describe-cluster --name <YOUR EKS CLUSTER> \
  --query 'cluster.resourcesVpcConfig.{public:endpointPublicAccess,private:endpointPrivateAccess,cidrs:publicAccessCidrs}'
```
For the in-VPC pattern you want `endpointPrivateAccess: true`. You do **not** need `endpointPublicAccess` enabled at all.

**Independent pre-check (no disruption).** Before running the full experiment, confirm the path end to end with a host already inside the client subnet (or a one-off instance launched there):
```bash
# From a host in SubnetId — a fast "ok" confirms reachability; a hang confirms the block.
curl -sk --max-time 5 https://<CLUSTER ENDPOINT HOST>/livez && echo " reachable"
```
A `200`/`ok` confirms the network path is open; a timeout confirms the subnet cannot reach the private endpoint (fix routing/SG/endpoint access before running). The check only predicts the automation's result if the cluster security group admits the subnet's CIDR: the automation runs its client in a new security group, so a rule that admits your test host's security group does not admit the client.

**Why this design.** Launching an ephemeral in-VPC instance and driving it with `aws:runCommand` means the Kubernetes API traffic originates from inside the VPC and is subject to your security groups and the EKS private endpoint, so the cluster's Kubernetes API can stay private. The instance is created at the start of the run, used only for the Kubernetes calls, and terminated (with its temporary security group deleted) on completion, failure, or cancel.

## Cluster configuration determines the outcome

This experiment always does the same three things: cordon the nodes in the target AZ, exclude that AZ from the NodePool, and delete the pods there. What you *observe*, a service that rides through the impairment or one that runs degraded, is decided entirely by **your workload's and cluster's configuration** (including the cluster's other NodePools), not by anything in the experiment template.

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

With `DoNotSchedule` and `maxSkew: 1` in a 2-AZ cluster, concentrating every replica into the surviving AZ violates the constraint while the cordoned node in the target AZ exists (a 6-vs-0 split is a skew of 6), so the scheduler refuses to place the evicted pods. Once Auto Mode has removed that node, the scheduler counts only zones that have a node the pods can use (here, a node of the NodePool), so the pods can run on spare capacity of the existing nodes. Whether EKS Auto Mode adds nodes for them depends on the cluster's other NodePools, because its scheduling simulation counts every zone that any NodePool can launch into. In testing with the built-in `general-purpose` and `system` NodePools enabled, it still counted the target AZ with 0 pods, reported `unsatisfiable topology constraint for topology spread` and added no node, so whenever the surviving nodes had no spare capacity, the evicted pods stayed `Pending` until the NodePool was restored, with 2 AZs and with 3 AZs. With no other NodePool in the cluster, tested with 3 AZs, it added nodes in the surviving AZs within seconds and the evicted pods ran (see [Validation results](#validation-results)). A zone that only another NodePool can launch into counts the same way when it is not the target AZ: in the 2-AZ runs, which used a NodePool limited to 2 AZs of a 3-AZ cluster, Auto Mode also counted the third AZ with 0 pods. Not tested: 2 AZs with no other NodePool, and a NodePool of your own covering the target AZ instead of the built-in ones.

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

If existing nodes have headroom, failover is as fast as pod startup — no EC2 launch required. If they do not, with `ScheduleAnyway` Auto Mode provisions new nodes and failover additionally waits on instance launch and node registration (typically 60-90s). With `DoNotSchedule` and `maxSkew: 1`, Auto Mode provisions nodes for the evicted pods only when no other NodePool can launch into the target AZ (see above); otherwise only existing headroom counts. Make sure nothing prevents that scale-up: a `spec.limits` on the NodePool or restrictive instance-type requirements can cap it.

### Which behaviour to expect

| Workload configuration | AZs | During impairment | What it demonstrates |
|---|---|---|---|
| `ScheduleAnyway`, headroom available | 2 | All replicas `Running` in surviving AZ; no new nodes | Workload sustains AZ loss; fastest recovery |
| `ScheduleAnyway`, no headroom | 2 | Replicas briefly `Pending`, then `Running` on newly provisioned nodes | Workload sustains AZ loss via scale-up |
| `ScheduleAnyway`, scale-up blocked (NodePool `limits`, instance constraints) | 2 | Some replicas stay `Pending` | Capacity ceiling — a real finding to fix |
| `DoNotSchedule` | 2 | Evicted replicas `Pending` until Auto Mode removes the cordoned node, then `Running` on spare capacity in the surviving AZ. Without spare capacity, they stay `Pending` for the whole impairment when another NodePool can launch into the target AZ, as with the built-in NodePools enabled | Proves the AZ exclusion is in force; with another NodePool covering the target AZ, spare capacity decides whether the workload survives |
| `ScheduleAnyway`, headroom available | 3 | All replicas `Running`, distributed 0/3/3 across surviving AZs | Workload sustains AZ loss with even distribution |
| `DoNotSchedule`, `maxSkew: 1`, headroom available | 3 | Evicted replicas `Pending` until Auto Mode removes the cordoned node in the target AZ, then all `Running`, distributed 0/3/3 across surviving AZs | **Both proves the exclusion AND that the workload survives** — the key 3-AZ advantage |
| `DoNotSchedule`, `maxSkew: 1`, no headroom, another NodePool can launch into the target AZ (for example, the built-in NodePools are enabled) | 3 | Evicted replicas stay `Pending` until the NodePool is restored: Auto Mode adds no node for them | The workload runs degraded for the whole impairment |
| `DoNotSchedule`, `maxSkew: 1`, no headroom, no other NodePool can launch into the target AZ | 3 | Evicted replicas briefly `Pending`, then `Running` after Auto Mode adds nodes in the surviving AZs | Workload sustains the AZ loss via scale-up |

Both settings are legitimate tests, but they answer different questions. `DoNotSchedule` is the stricter proof that the impairment itself is real — `Pending` pods are unambiguous evidence that nothing could be scheduled into the impaired AZ, which is useful when validating the template or the automation. `ScheduleAnyway` is what you want for an AZ impairment scenario that showcases the workload sustaining the failure.

### 3. Number of Availability Zones

The number of AZs in your cluster changes both the blast radius and the redistribution behaviour during impairment.

| Cluster AZs | Pods lost | Surviving pods | Where replacements land | Effective capacity during impairment |
|---|---|---|---|---|
| 2 AZs (e.g. 3/3) | 50% of replicas | 50% | Single surviving AZ only | With `DoNotSchedule`: 50% until Auto Mode removes the target AZ's node, then 100% with headroom (without headroom, see [Which behaviour to expect](#which-behaviour-to-expect)). With `ScheduleAnyway` and headroom: 100% |
| 3 AZs (e.g. 2/2/2) | 33% of replicas | 67% | **Distributed across both surviving AZs** | With `DoNotSchedule`: 67% until Auto Mode removes the target AZ's node, then 100% with headroom (without headroom, see [Which behaviour to expect](#which-behaviour-to-expect)). With `ScheduleAnyway` and headroom: 100% |

With **3 AZs and `DoNotSchedule`**, the topology spread constraint (`maxSkew: 1`) forces the scheduler to distribute evicted pods across both surviving AZs rather than concentrating them in one. After the 2 pods in the target AZ are killed and the target AZ has no node left, the scheduler must place them so that no zone exceeds the others by more than 1 — the only valid 6-pod arrangement across 2 zones is 3/3. This means the workload stays spread even under failure, rather than hotspotting into a single AZ, as long as the surviving nodes have spare capacity for the evicted pods, or Auto Mode adds nodes for them, which in testing it did only when no other NodePool could launch into the target AZ.

With **2 AZs and `DoNotSchedule`**, there is only one surviving AZ. While the cordoned node exists, the evicted pods cannot schedule there because moving from a 3/3 spread to 0/6 violates `maxSkew: 1` (skew = 6). Once Auto Mode has removed that node, they can use spare capacity on the existing nodes in the surviving AZ. When another NodePool can launch into the target AZ, Auto Mode adds no node for them, so without spare capacity they remain `Pending`.

With spare capacity in the surviving AZs, the 3-AZ topology keeps the replicas spread across the surviving zones (0/3/3), where 2 AZs put them all in one (0/6), and in both cases `DoNotSchedule` still proves the impaired AZ is excluded. Without spare capacity, and with another NodePool able to launch into the target AZ, the evicted pods stay `Pending` for the duration with either AZ count.

### Validation results

**2 AZs** (500m CPU requests): with `DoNotSchedule`, 6 replicas and no spare capacity on the surviving node, the service ran at 50% capacity (3 `Running` / 3 `Pending`) for the full 15-minute impairment, and Auto Mode added no node until the NodePool was restored. With `DoNotSchedule`, 2 replicas and room on the surviving node, the evicted pod was `Running` there about 50 seconds after the cordon, once Auto Mode had removed the cordoned node. Both `DoNotSchedule` runs used a NodePool limited to 2 AZs of a 3-AZ cluster, with the built-in NodePools enabled. With 6 replicas and `ScheduleAnyway`, where the surviving AZ's nodes had room for all of them, the result was 6 `Running` / 0 `Pending` throughout (100% availability), with no new nodes needed.

**3 AZs** (6 replicas, 500m CPU requests, `DoNotSchedule`): the 2 pods in the target AZ were killed and rescheduled — one to each surviving AZ — producing a clean 0/3/3 distribution. The 2 replacement pods were `Pending` until EKS Auto Mode removed the cordoned node in the target AZ: while that node exists, the scheduler still counts its zone, so a 0/3/3 placement breaks `maxSkew: 1` (`didn't match pod topology spread constraints`). In testing, Auto Mode started removing the node a few seconds after the NodePool patch, and the pods were `Running` within about a minute of being deleted. Once that node was gone, the `maxSkew: 1` constraint was satisfiable across the 2 remaining zones (3 vs 3 = skew 0), so `DoNotSchedule` reduced capacity only for that short time. The workload sustained the AZ loss with pods distributed across both surviving zones rather than collapsing into one. With 9 replicas on full nodes (3 per node, no spare capacity) and the built-in NodePools enabled, the 3 evicted pods stayed `Pending` until the NodePool was restored, and Auto Mode added no node for them. In the same test with the built-in NodePools disabled and no other NodePool in the cluster, Auto Mode added a node in each surviving AZ within seconds of the NodePool patch, and all 9 pods were `Running` about a minute after the eviction, 0/5/4 across the zones.

| Metric | 2 AZs | 3 AZs |
|---|---|---|
| Starting distribution | 3 / 3 | 2 / 2 / 2 |
| Pods killed | 3 (50%) | 2 (33%) |
| Test conditions (`DoNotSchedule`) | No spare capacity on the surviving node; built-in NodePools enabled | Room for the evicted pods; built-in NodePools enabled |
| During impairment (`DoNotSchedule`) | 0 / 3 + 3 `Pending` | 0 / 3 / 3, all `Running` once the target AZ's node is removed |
| During impairment (`ScheduleAnyway`) | 0 / 6 — all `Running` | 0 / 3 / 3 — all `Running` |
| Nodes reprovisioned during | 0 | 0 |
| Post-restore distribution | 3 / 3 with `DoNotSchedule` (the `Pending` pods start in the restored AZ); 0 / 6 with `ScheduleAnyway` until a rebalance | Unchanged; a rollout restart kept 0 / 3 / 3 |

### After the experiment

Regardless of `whenUnsatisfiable` or AZ count, replicas that ran during the impairment do **not** automatically migrate back once the impaired AZ is restored. Topology spread constraints are evaluated only at scheduling time, so they never evict a running pod to satisfy a spread. Additionally, with `consolidationPolicy: WhenEmpty`, no new node is provisioned in the restored AZ unless pods are still `Pending` at the restore, because otherwise no scheduling demand exists there.

The post-restore state is:
- NodePool zone requirement includes all original AZs again ✓
- No cordoned nodes remain ✓
- No leftover NACLs (FIS restores these automatically) ✓
- **Pods that ran during impairment stay where they landed**: the NodePool allows the restored AZ again, but unless pods were still `Pending` at the restore, no node runs there and nothing triggers rebalancing

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
T+~0s   ┌─ ValidateInputs / CreateSecurityGroup ─────────────────────────────┐
        │  Validate AZ/cluster/NodePool, create a temporary client SG         │
        └─────────────────────────────────────────────────────────────────────┘
                          │
T+~5s   ┌─ LaunchClientInstance / WaitForSSMAgent / BootstrapClient ─────────┐
        │  Launch an ephemeral EC2 instance INSIDE the VPC (SubnetId),        │
        │  wait for its SSM Agent, install python3 + urllib3/boto3            │
        └─────────────────────────────────────────────────────────────────────┘
                          │
T+~4m   ┌─ CordonPatchDelete  (aws:runCommand on the in-VPC instance) ───────┐
        │  Cordon all nodes in target AZ (unschedulable)                      │
        │  Patch NodePool to remove target AZ from zone requirements          │
        │  Delete all non-system pods on nodes in target AZ (gracePeriod=0)   │
        │  Kubernetes reschedules to healthy AZs only ✓                       │
        └─────────────────────────────────────────────────────────────────────┘
                          │
T+~4m → T+~19m            ▼  WaitForDuration (impairment period)
                          │
T+15m                     ▼  FIS restores the original NACL (network connectivity returns;
                             the target AZ stays excluded from the NodePool)
                          │
T+~19m                    ▼
        ┌─ RestoreNodePool  (aws:runCommand on the in-VPC instance) ─────────┐
        │  Re-add target AZ to NodePool zone requirements                     │
        │  Uncordon all nodes in target AZ                                    │
        └─────────────────────────────────────────────────────────────────────┘
                          │
T+~20m  ┌─ TerminateInstance / DeleteSecurityGroup ─────────────────────────┐
        │  Terminate the ephemeral instance, delete the temporary SG          │
        └─────────────────────────────────────────────────────────────────────┘
                          │
                          ▼  Pods stay where they landed (see Recovery Behavior)
```

**Why pods are deleted only after the NodePool is patched:** The ordering inside the SSM automation is what makes the impairment stick. Cordoning marks existing nodes in the target AZ unschedulable and the NodePool patch stops EKS Auto Mode from provisioning replacements there. Only then are pods deleted, so Kubernetes has no placement option left in the impaired AZ. If pods were deleted first, they could be rescheduled straight back into the AZ before the exclusion took effect. The cordon, patch, and delete operations run as one `aws:runCommand` program on the in-VPC instance (`CordonPatchDelete`), so the ordering is guaranteed within a single process.

### Actions Detail

| Action | Action ID | Description | Starts |
|--------|-----------|-------------|--------|
| `disrupt-az-network` | `aws:network:disrupt-connectivity` | Blocks all ingress/egress traffic on subnets in the target AZ via NACLs | T+0 |
| `cordon-and-exclude-az` | `aws:ssm:start-automation-execution` | Triggers the SSM automation that launches an in-VPC client instance and performs all K8s operations (cordon, patch, delete pods, wait, restore) from inside the VPC | T+0 |

### SSM Automation Document

The experiment uses a single SSM Automation document (`eks-automode-az-impairment-automation`) that manages the complete EKS-specific fault lifecycle. All Kubernetes API calls run from an **ephemeral EC2 instance inside your VPC**, so they work against a private EKS endpoint:

1. **Validates** input parameters (AZ format, cluster/NodePool choice) — `ValidateInputs`
2. **Creates a temporary security group** and **launches an ephemeral EC2 instance** in `SubnetId` inside the VPC — `CreateSecurityGroup`, `LaunchClientInstance`
3. **Waits for the SSM Agent** to come online and **bootstraps** python3 + `urllib3`/`boto3` — `WaitForSSMAgent`, `BootstrapClient`
4. **Cordons nodes, patches the NodePool, and deletes pods** in the target AZ, all from the in-VPC instance in a single `aws:runCommand` — `CordonPatchDelete`
5. **Waits** for the impairment duration (configurable, default 15 minutes) — `WaitForDuration`
6. **Restores the NodePool** and **uncordons nodes** from the in-VPC instance — `RestoreNodePool`
7. **Terminates the instance** and **deletes the temporary security group** — `TerminateInstance`, `DeleteSecurityGroup`

`CordonPatchDelete` and `WaitForDuration` have `onFailure`/`onCancel` routing to `RestoreNodePool`, which in turn routes to `TerminateInstance` → `DeleteSecurityGroup`. This ensures the NodePool is always restored, nodes are always uncordoned, and the ephemeral instance and security group are always cleaned up — even if the experiment is cancelled or errors. When the experiment is stopped, SSM Automation gives this cancel path at most 2 minutes; in testing, the restore, the instance termination and the security group deletion finished in under a minute. The restore gates on a patch-result file written by `CordonPatchDelete`, so it only touches the NodePool if the patch actually ran; a terminal restore failure makes the step exit non-zero so a stop condition or alarm can trip.

### Why This Experiment Uses No `aws:eks:pod` Actions

FIS resolves `aws:eks:pod` targets by **namespace + label selector**, and the [FIS documentation](https://docs.aws.amazon.com/fis/latest/userguide/eks-pod-actions.html) states you *"can't identify targets of type `aws:eks:pod` in your experiment template using resource ARNs or resource tags."* Critically, **pods do not inherit their node's `topology.kubernetes.io/zone` label** — that label exists on Nodes only. A selector like `app=myapp,topology.kubernetes.io/zone=us-east-1a` therefore matches zero pods.

That leaves no correct way to scope a pod action to one AZ:

- An AZ-qualified label selector resolves to nothing, and with `emptyTargetResolutionMode: skip` the action silently does nothing while the experiment still reports success
- Dropping the AZ term and targeting `app=myapp` hits pods in the **healthy** AZs too — degrading the very capacity the experiment is meant to prove survives

So pod termination is handled by the SSM automation, directly via the Kubernetes API: it lists pods on nodes in the target AZ and deletes them with `gracePeriodSeconds=0` (sudden death). This gives precise AZ-scoped termination with no dependency on FIS pod targeting.

**This is also why there is no `aws:eks:pod-network-packet-loss` action.** Beyond the same targeting problem, subnet-level NACLs (`aws:network:disrupt-connectivity`) already block all traffic in the AZ — strictly broader than per-pod packet loss, since it affects every resource in the subnet rather than only labelled pods. The pod action would add setup cost (a Kubernetes service account, the `privileged` Pod Security Standard, root in the ephemeral container, and `readOnlyRootFilesystem: false` on every target pod) for no additional coverage.

If you do add `aws:eks:pod` actions to a fork of this experiment, note that all of them fail unless target pods set `readOnlyRootFilesystem: false` in their `securityContext` — FIS cannot otherwise monitor injection status. You would also need to re-add a Kubernetes service account, an EKS access entry for the FIS role, and the corresponding RBAC, none of which this experiment installs.

## Targets

| Target Name | Resource Type | Selection Mode | Description |
|-------------|---------------|----------------|-------------|
| `subnets-in-target-az` | `aws:ec2:subnet` | ALL | VPC subnets tagged `FIS-Ready=True` in the target AZ (scoped via the `availabilityZoneIdentifier` parameter) to disrupt network connectivity |

The template defines only this one FIS target. It is resolved by the `FIS-Ready=True` resource tag and scoped to a single AZ with the `availabilityZoneIdentifier` parameter (rather than a hard-coded subnet ARN). Pod termination is handled by the SSM automation via the Kubernetes API rather than by a FIS `aws:eks:pod` target — see [Why This Experiment Uses No `aws:eks:pod` Actions](#why-this-experiment-uses-no-awsekspod-actions) above.

### Target Requirements
- The subnet must carry the `FIS-Ready=True` tag and be in the AZ named by both the target's `availabilityZoneIdentifier` parameter and the automation's `TargetAZ` parameter, so the network disruption and the Kubernetes-level impairment affect the same AZ
- Nodes must carry the standard `topology.kubernetes.io/zone` label (EKS applies this automatically) — the automation uses it to find nodes and pods in the target AZ
- The EC2 instance profile role must have Kubernetes API access via an EKS Access Entry (username `fis-az-impairment-client`) plus the RBAC in `eks-automode-az-impairment-rbac.yaml`

## Parameters to Configure

Before running the experiment, update these placeholder values:

| Placeholder | Description |
|-------------|-------------|
| `<YOUR AWS ACCOUNT>` | Your 12-digit AWS account ID |
| `<YOUR REGION>` | AWS region where resources are deployed (e.g., `ap-southeast-2`) |
| `<YOUR FIS ROLE NAME>` | FIS execution IAM role name |
| `<YOUR SSM AUTOMATION ROLE NAME>` | SSM automation IAM role name |
| `<YOUR INSTANCE PROFILE ROLE NAME>` | Name of the role behind the EC2 instance profile the ephemeral client uses (referenced by the SSM automation role's `iam:PassRole`) |
| `<YOUR EKS CLUSTER>` | Name of your EKS cluster |
| `<YOUR TARGET AZ>` | Availability Zone to impair (e.g., `ap-southeast-2a`) |
| `<YOUR SUBNET ID IN TARGET AZ>` | Subnet ID(s) in the target AZ to tag with `FIS-Ready=True` (used in the `create-tags` step, not hard-coded in the template) |
| `<YOUR CLIENT SUBNET ID (NOT in the target AZ)>` | Subnet (in a surviving AZ) where the ephemeral K8s client instance is launched. The cluster security group must allow TCP 443 from its CIDR, and it needs outbound internet access, for example through a NAT gateway (see prerequisite 9). Passed as the `SubnetId` document parameter |
| `<YOUR VPC ID>` | VPC ID in which the temporary client security group is created — passed as the `VpcId` document parameter |
| `<YOUR INSTANCE PROFILE NAME>` | Existing EC2 instance profile (whose role has `AmazonSSMManagedInstanceCore`, the inline policy from prerequisite 1, and the EKS access entry and RBAC from prerequisites 2 and 3) for the client instance. Passed as the `InstanceProfileName` document parameter |
| `<YOUR NODEPOOL NAME>` | Name of a **custom** EKS Auto Mode NodePool (not `general-purpose` or `system`) |

## How Pods in the Target AZ Are Selected

No pod label selector configuration is required. The SSM automation resolves the target pods itself:

1. Lists nodes matching `topology.kubernetes.io/zone=<TargetAZ>`
2. For each of those nodes, lists pods via `fieldSelector=spec.nodeName=<node>`
3. Deletes each pod with `gracePeriodSeconds=0`, skipping the `kube-system`, `kube-node-lease`, and `kube-public` namespaces

This means **all non-system pods on nodes in the target AZ are deleted**, across every namespace. If you need to limit the blast radius to specific workloads, add a namespace or label filter to the pod-deletion logic in the `CordonPatchDelete` step of `eks-automode-az-impairment-automation.yaml`.

## Fine-Tuning the Wait Duration

The automation deletes pods immediately after cordoning nodes and patching the NodePool, so no separate wait action is needed. If your cluster's control plane is slow enough that pods get rescheduled into the impaired AZ before the NodePool patch propagates, add a short sleep between the patch and the pod deletion inside the `CordonPatchDelete` step's program. Timing depends on:

- **Cluster size**: More nodes = longer cordon time
- **Control plane load**: Busy clusters may take longer for NodePool patches to propagate
- **SSM execution overhead**: First-time execution may be slower

To calibrate:
1. Run the SSM automation document standalone 10 times
2. Measure the time from start to "nodes cordoned + NodePool patched"
3. Size that sleep at the P95 duration + 30 seconds buffer

## Stop Conditions

The experiment does not include stop conditions by default. It will continue until all actions complete (about 20 minutes in testing: the network disruption lasts 15 minutes; the automation spends about 4 minutes launching and preparing its client before its 15-minute wait, and under a minute restoring and cleaning up after it).

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
3. **Nodes**: SSM automation uncordons every unschedulable node in the target AZ, including any node that was cordoned before the experiment started — note that if EKS Auto Mode terminated a drained node during the impairment, there may be no node left in that AZ to uncordon, and `UncordonedNodes` will be empty. This is expected.
4. **Pods**: behaviour depends on the configuration described in [Cluster configuration determines the outcome](#cluster-configuration-determines-the-outcome):
   - With `ScheduleAnyway` (2 or 3 AZs), pods that failed over **stay** in the surviving AZ(s). The spread is only a preference, so a running pod is never moved to satisfy it.
   - With `DoNotSchedule`, pods that are still `Pending` at the restore (2 or 3 AZs, no spare capacity, another NodePool covering the target AZ) schedule into the restored AZ on their own as soon as the NodePool is restored and Auto Mode provisions a node there. No manual step is needed; in testing, this took under a minute.
   - With `DoNotSchedule`, pods that ran in the surviving AZs during impairment, on spare capacity or on nodes Auto Mode added, **stay there** (for example 0/3/3 with 3 AZs, or all in the surviving AZ with 2 AZs). They will not rebalance, because topology spread constraints are only evaluated at scheduling time.

### Restore status and failure signal

The `RestoreNodePool` step runs the restore program on the in-VPC instance and prints a `RestoreResult` JSON line (visible in the step's command output and in the `/aws/ssm/AWS-RunShellScript` CloudWatch Logs log group) describing how the cleanup went. On a clean run this is `NODEPOOL_RESTORED` (or `NODEPOOL_ALREADY_CORRECT` / `NODEPOOL_UNCHANGED_NO_PATCH_RECORDED` when there was nothing to undo). If the log group does not exist yet, the first run creates it with no retention period; to limit how long the output is kept, run `aws logs put-retention-policy --log-group-name /aws/ssm/AWS-RunShellScript --retention-in-days <DAYS>`.

If the restore cannot complete cleanly, the program exits non-zero (after first attempting to uncordon nodes), which **fails the SSM automation step** so the failure is visible to an operator and can trip a CloudWatch alarm or FIS stop condition, rather than being silently reported as success. A terminal restore leaves the target AZ still excluded from the NodePool and/or nodes still cordoned, so it requires **manual remediation**. Statuses that fail the step are:

- `NODEPOOL_RESTORE_FAILED_<code>` — the restore PATCH to the Kubernetes API returned a non-200 status.
- `NODEPOOL_RESTORE_ERROR: <message>` — an unexpected exception occurred during NodePool restore.
- Any status containing `UNCORDON_ERROR` or `UNCORDON_LIST_FAILED` — one or more nodes could not be uncordoned.

One status is treated as a **warning, not a failure**:

- `NODEPOOL_MODIFIED_EXTERNALLY_SKIPPED` — the NodePool was changed by something else (EKS Auto Mode reconciliation, a GitOps controller, or an operator) after the automation patched it. The automation **deliberately declined to touch it**, because removing a requirement it no longer recognises could be destructive. That external change has frequently already reverted the AZ exclusion, so failing here would be a false alarm. It is logged as a `WARNING` and the step still succeeds — but a human should confirm the NodePool's `topology.kubernetes.io/zone` requirement is correct. If you want unattended runs to alarm on it, create a metric filter on the `WARNING: NODEPOOL_MODIFIED_EXTERNALLY_SKIPPED` log line in the `/aws/ssm/AWS-RunShellScript` log group rather than relying on step failure.

**Manual remediation** when the step fails: inspect the `RestoreResult` in the automation execution output, then restore the NodePool's `topology.kubernetes.io/zone` requirement to its original values and uncordon any remaining nodes in the target AZ (`kubectl uncordon <node>`). Because the automation records its failure, an unattended run will surface it instead of leaving degraded capacity in place unnoticed.

**To rebalance pods that stayed put:**

```bash
kubectl rollout restart deployment/<your-deployment-name>
```

This cycles the pods so the scheduler places them again. Note that a soft constraint still will not guarantee a spread: if the surviving AZ has enough headroom for every replica, the scheduler may simply place them all there again. A hard constraint does not guarantee it either: in testing with `DoNotSchedule`, a rollout restart after the experiment left all 6 replicas in the 2 surviving AZs. The restored AZ had no node left, and the scheduler counts only zones that have a node the pods can use (here, a node of the NodePool), so 3 and 3 already satisfied `maxSkew: 1`. Auto Mode launched a node in the restored AZ during the restart, but the new pods were placed on the existing nodes before that node joined the cluster, and the empty node was removed about a minute later. What restored 2/2/2 in testing was scaling the Deployment up until Auto Mode added a node in the restored AZ, setting the `controller.kubernetes.io/pod-deletion-cost` annotation to a negative value on one pod in each zone, and then scaling back down. In production, this is the equivalent of a post-incident rebalancing step.

To rebalance when no node runs in the restored AZ, as in testing:

```bash
# Scale up until Auto Mode adds a node in the restored AZ and pods run there
kubectl scale deployment/<your-deployment-name> --replicas=<MORE REPLICAS>
# Mark one pod in each zone to be removed first, then scale back down
kubectl annotate pod <ONE POD IN EACH ZONE> controller.kubernetes.io/pod-deletion-cost=-100
kubectl scale deployment/<your-deployment-name> --replicas=<YOUR REPLICAS>
```

**Why no automatic rebalance occurs:**

Kubernetes topology spread constraints are scheduling-time only — they influence where a pod is *initially placed* but never evict a running pod to re-satisfy the constraint. Combined with EKS Auto Mode's `consolidationPolicy: WhenEmpty` (or Karpenter's equivalent), no new node is provisioned in the restored AZ because no scheduling demand exists there. In testing, Auto Mode started removing the cordoned node seconds after the NodePool patch, and unless pods are still `Pending` when the NodePool is restored, nothing triggers its replacement.

This post-impairment drift is realistic production behaviour: after an AZ recovers, workloads remain where they failed over until an operator explicitly rebalances them (for example with the scale-up and scale-down above, or a descheduler).

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
5. Reviewing the RBAC ClusterRole and confirming the `fis-az-impairment-client` username matches the one in the instance profile role's EKS Access Entry.
6. Narrowing the blast radius if needed — by default the automation deletes all non-system pods on nodes in the target AZ, across every namespace. Add a namespace or label filter to the pod-deletion logic in the `CordonPatchDelete` step to scope it.
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
| `eks-automode-az-impairment-automation.yaml` | SSM Automation document — launches an ephemeral in-VPC EC2 client, then cordons, patches the NodePool, deletes pods, waits, restores, and cleans up |
| `eks-automode-az-impairment-iam-policy.json` | IAM policy for the FIS execution role |
| `eks-automode-az-impairment-ssm-automation-iam-policy.json` | IAM policy for the SSM automation role (orchestration: launch/terminate instance, security group, runCommand) |
| `eks-automode-az-impairment-instance-profile-iam-policy.json` | Inline IAM policy for the EC2 instance profile role (EKS describe + Kubernetes API access + subnet describe + CloudWatch Logs for the command output); attach alongside `AmazonSSMManagedInstanceCore` |
| `eks-automode-az-impairment-rbac.yaml` | Kubernetes RBAC for the EC2 instance profile role (bound via the `fis-az-impairment-client` username) |
| `fis-iam-trust-relationship.json` | Trust policy for FIS service |
| `ssm-iam-trust-relationship.json` | Trust policy for SSM service |
