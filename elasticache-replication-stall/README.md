# AWS Fault Injection Service Experiment: ElastiCache Replication Stall

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

> 中文说明请见 [README.zh-CN.md](README.zh-CN.md).

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

When a read replica stops applying the replication stream while its replication link stays up, the application continues to serve reads from that replica with unchanged latency, serves writes normally against the primary (provided `min-replicas-to-write` is `0`, the default — see prerequisite 17), and alerting detects the growing replication gap rather than reporting the cluster as healthy.

Two failure modes this experiment is designed to surface:

1. **Stale reads that look healthy.** The replica keeps answering reads at normal latency, but the data it returns is frozen at the moment the stall began. An application that treats "the replica responded quickly" as "the replica is current" will serve stale data without any error.
2. **A monitoring blind spot.** While the stream is stalled, the primary still reports `lag=0` for that replica in `INFO replication`, because that field measures how recently an acknowledgement arrived, not how far behind the replica is. Monitoring built on that field alone, or on `connected_slaves`, cannot see this fault. The gap is visible in `master_repl_offset` minus the replica's `offset` on the primary, and in the CloudWatch `ReplicationLag` metric.

If the fault is sustained long enough that the backlog outgrows what the replica can hold, the replication link drops and the replica performs a full resynchronisation. That escalation is driven by the volume of accumulated backlog, which is approximately the write rate multiplied by the pause duration.

## Prerequisites

Before running this experiment, ensure that:

### 1. Target cache cluster

1. The target is a **node-based** ElastiCache replication group running **Valkey** or **Redis OSS**. Serverless caches are not supported: `client pause` is on the list of commands ElastiCache makes unavailable for serverless caches.
2. **Both cluster mode disabled and cluster mode enabled are supported.** On a cluster-mode-enabled group, set `TargetShardId` to one shard for a first run — see "Blast radius on a sharded cluster" below.
3. The replication group has **at least one replica**, and its `Status` is `available`. A cross-Availability-Zone replica makes the experiment closest to a real inter-AZ network event.
4. The cluster does **not** require an auth token or RBAC authentication. This document connects without credentials and will exit with a clear error if the cache replies `NOAUTH` or `WRONGPASS`. Extend the document to read a token from AWS Secrets Manager if you need authenticated clusters.
5. If the replication group has **encryption in transit** enabled, set the `UseTls` document parameter to `true`. On a cluster-mode-enabled group this additionally requires `elasticache:DescribeCacheClusters` on the instance profile, because `CLUSTER SHARDS` reports node endpoints as IP addresses and a TLS certificate cannot be validated against an IP. The document resolves node DNS names from the API and **fails closed with an explicit error** if it can only obtain an IP while `UseTls` is true.

> ### How the two cluster modes are discovered
>
> The AWS API reference states that two `DescribeReplicationGroups` fields are
> populated only for cluster mode disabled replication groups:
>
> - `NodeGroupMember.CurrentRole` — "This member is only applicable for Valkey or
>   Redis OSS (cluster mode disabled) replication groups."
> - `NodeGroupMember.ReadEndpoint` — "The read endpoint is only applicable on
>   Valkey or Redis OSS (cluster mode disabled) clusters."
>
> This was confirmed against a live 3-shard cluster-mode-enabled group, where
> every member returned `CurrentRole: null` and `ReadEndpoint: null`, while
> `NodeGroupId` and `Slots` were populated.
>
> The document therefore uses two discovery paths:
>
> | Mode | Roles and endpoints from | Shard identity from |
> |---|---|---|
> | Cluster mode disabled | `NodeGroupMember.CurrentRole` / `ReadEndpoint` | `NodeGroupId` |
> | Cluster mode enabled | `CLUSTER SHARDS` against the configuration endpoint | hash slot mapped back to `NodeGroupId` via `NodeGroups[].Slots` |
>
> Neither `cluster shards` nor `cluster nodes` appears on the ElastiCache
> restricted-command list. In both modes the selected node must additionally
> report `role:slave` over its own `INFO replication` before it is targeted, so
> the control-plane view and the data-plane view have to agree.
>
> The fault itself is mode-independent. `CLIENT PAUSE` is node-local in cluster
> mode too: the pause state lives in the per-process `server` struct, and the
> only cluster-related use of it in the engine is a node pausing itself during a
> manual failover. Pausing one shard's replica does not affect the other shards.

### Blast radius on a sharded cluster

`ReplicaScope` counts replicas **per shard**, so on the common topology of one
replica per shard, `ONE_PER_SHARD` and `ALL` resolve to exactly the same set —
every replica in the cluster. On a 3 shard × 2 node group that means the entire
replica tier stalls at once, and the experiment has no unaffected shard left to
compare against.

Use `TargetShardId` to inject into one shard and keep the rest as in-experiment
controls. Observation always covers **every** shard's primary regardless of
targeting, precisely so the untargeted shards can serve as that control.

### 2. Injector EC2 instance

The fault is injected over the cache data plane, so it must be issued from inside the VPC. SSM Automation's `aws:executeScript` runs in an AWS-managed sandbox with no VPC connectivity and therefore cannot reach a cache node, which is why this template uses `aws:ssm:send-command` against an instance you control.

5. You have at least one **Linux** EC2 instance in the same VPC as the cache cluster, in a subnet with a network path to the cache nodes. The document is Linux-only: every step carries a `platformType: Linux` precondition.
6. The instance is a **managed instance**: SSM Agent **3.0.502 or later** is installed and running (required for the document's `onFailure` / `finallyStep` step controls), and the instance appears under Fleet Manager in Systems Manager. The document's `Region` parameter defaults to the instance's own Region, read from the instance metadata service, so the injector needs IMDS access unless you pass `Region` explicitly.
7. The instance profile has **both**:
   - the `AmazonSSMManagedInstanceCore` AWS managed policy, and
   - `elasticache:DescribeReplicationGroups`, which the document uses to read the topology, **and** `elasticache:DescribeCacheClusters`, which it uses on cluster-mode-enabled groups to resolve node DNS names. A sample policy is provided in `elasticache-replication-stall-injector-instance-policy.json`.
8. The instance's subnet can reach the **ElastiCache API endpoint** — through a NAT gateway, or through an interface VPC endpoint for `com.amazonaws.<region>.elasticache`. Without this the role-resolution step fails and the experiment stops before injecting anything.
9. `python3` and the `aws` CLI are present on the instance. Both ship with Amazon Linux 2023 and Amazon Linux 2. **No pip packages and no internet access to PyPI are required**: the embedded script speaks the cache wire protocol using only the Python standard library.
10. The instance is tagged `FIS-Ready=True` **and** `FIS-Role=ElastiCacheInjector`. The second tag keeps the experiment from sending the command to unrelated instances that merely carry the repository's common `FIS-Ready` tag.

### 3. Network path from the injector to the cache

11. The cache cluster's security group allows **inbound TCP on the cache port (6379 by default) from the injector instance's security group**. Without this rule the validation step fails on a connection timeout.

### 4. IAM and the SSM document

12. You have registered the SSM document in your account with the name `ElastiCacheReplicationStall`, from `elasticache-replication-stall-ssm-template.yaml`:

    ```bash
    aws ssm create-document \
      --name ElastiCacheReplicationStall \
      --document-type Command \
      --document-format YAML \
      --content file://elasticache-replication-stall-ssm-template.yaml
    ```

13. The IAM role referenced in the `roleArn` field of the experiment template exists, trusts `fis.amazonaws.com` (see `fis-iam-trust-relationship.json`) and carries the permissions in `elasticache-replication-stall-iam-policy.json`.
14. You have replaced every placeholder in `elasticache-replication-stall-template.json`: `<YOUR REGION>`, `<YOUR AWS ACCOUNT>`, `<YOUR ROLE NAME>` and `<YOUR REPLICATION GROUP ID>`.

### 5. Observability, before you inject

15. A steady-state baseline has been captured for at least 10 minutes on `ReplicationLag`, `ReplicationBytes`, read latency and read error rate. Without a baseline you cannot tell the fault's effect from normal variation.
16. Write traffic is flowing to the primary during the experiment. With no writes there is nothing for the replica to fall behind on, and the experiment will report no effect even though the injection succeeded.
17. You know the value of `min-replicas-to-write` in the target's parameter group. At the default `0` the primary never rejects writes because of replica state. At `1` or higher, a sustained stall under heavy write load **rejects writes on the primary for far longer than the pause**: in validation, a 30-second pause rejected every write for **166.8 seconds**. A stall alone does not trip this gate — it measures how recently an acknowledgement arrived, and acknowledgements keep flowing during a pause. It trips only when the backlog piles up in the replica's memory until the node starts swapping and stops acknowledging; the primary then drops the link at `repl-timeout` (60 seconds) and rejections continue until a full resynchronisation completes. Treat a non-zero value as widening the blast radius to the primary's write path.

## How it works

The experiment sends one SSM Command document to a single tagged injector instance. The document runs three steps.

**ValidatePrerequisites** — writes the helper script to the instance, then performs the checks below. The step sets `onFailure: exit`, so if any check fails, `InjectReplicationStall` is skipped and nothing is paused.

- resolves the topology and selects target nodes, by `CurrentRole` on a cluster-mode-disabled group and by `CLUSTER SHARDS` on a cluster-mode-enabled one. A node whose role cannot be proven to be `replica` is skipped with a warning and never paused. This fails closed on purpose: pausing a primary would be a far larger fault than the one under test, and node names do not reliably indicate role after a failover.
- connects to each candidate and confirms the node itself reports `role:slave`, so the API view and the data-plane view have to agree.
- issues `CLIENT PAUSE 1 <mode>` as an availability probe. One millisecond has no measurable effect, but it proves the command is permitted on this cluster before the real injection.
- refuses to start if a state file from an earlier run is still present on the instance.

**InjectReplicationStall** — records the primary-side view, issues `CLIENT PAUSE <PauseMilliseconds> <PauseMode>` on each resolved replica (or, with `DutyCyclePercent` above 0, a repeating short pause — see [Duty-cycle mode](#duty-cycle-mode)), then samples the primary's `INFO replication` until `DurationSeconds` elapses, logging `master_repl_offset` alongside each replica's acknowledged `offset`, `lag` and `state`.

Observation is taken from the **primary**, not the replica, because `PauseMode=ALL` also blocks `INFO` on the paused replica.

**RestoreAndVerify** — issues `CLIENT UNPAUSE`, reports `master_link_status`, `master_sync_in_progress` and the replica's offset, prints the primary-side view again and removes the state file and the helper script. It is a `finallyStep`, so it runs even when validation exits early. `CLIENT PAUSE` expires on its own, so this step is a safety net rather than the primary recovery mechanism; the fault self-heals even if the experiment is interrupted or the instance becomes unreachable.

### Choosing PauseMode

| Your application | Use | Why |
|---|---|---|
| Reads from replicas | `WRITE` | Stalls the replication stream while the replica keeps serving reads, which is the condition you want to test. |
| Reads only from the primary | `ALL` | Simpler, and no application read path touches the paused node. |

Do not use `ALL` when the application reads from replicas: reads on that node are blocked for the whole pause, which mixes "replication fell behind" together with "a read node was removed from service" and makes the result impossible to attribute.

### Controlling severity

Severity is governed by the accumulated backlog, roughly the write rate multiplied by the pause duration. Start with a short `PauseMilliseconds` and increase it to walk from a stall that the application does not notice, through a replica that is reported as lagging, to a replication link that drops and resynchronises in full. Increase one variable at a time so each step stays attributable.

Escalation can arrive sooner than expected on small node types. In a validation run on `cache.t4g.micro` with three writer threads at 1 KiB per value, a `PauseMode=WRITE` pause of only **20 seconds** produced this sequence on the primary:

```
master_repl_offset=109213724521  slave0(offset=109021347493, lag=3s,  state=online)
master_repl_offset=109218366559  slave0(offset=109021347493, lag=28s, state=online)   <- acknowledged offset frozen
...
slave0(offset=0, lag=0s, state=wait_bgsave)   <- link dropped, full resynchronisation
```

The replica's acknowledged offset stayed frozen while the primary advanced, the link stayed `online` throughout the pause, and the backlog then grew past what the node could hold — `sync_full` incremented and the replica reached 1.45 GB behind before catching up. Size the pause against the node type and the write rate, not against the clock alone.

Note also that the `RestoreAndVerify` step is best-effort by design. In the same run, `CLIENT UNPAUSE` timed out because the replica was too saturated to answer, and the document logged a warning and continued. Recovery does not depend on that call: the pause expires on its own.

### Duty-cycle mode

`CLIENT PAUSE` is binary: the stream is either held or not. Setting `DutyCyclePercent` to 1-99 approximates a partial degradation instead. At the start of every `CyclePeriodMilliseconds` the document issues `CLIENT PAUSE <period x percent / 100> <PauseMode>`, the pause expires on its own, and the cycle repeats for `DurationSeconds`. The replica repeatedly falls behind and catches up, which is closer to a replication link that is degraded by packet loss or throttling than one long freeze followed by a single catch-up. `PauseMilliseconds` is ignored in this mode.

What the two parameters control, measured on `cache.t4g.micro` at about 12 MiB/s of writes:

| Parameter | Controls | Observed |
|---|---|---|
| `CyclePeriodMilliseconds` × `DutyCyclePercent` / 100, the pause slice | Peak backlog per cycle, roughly write rate × pause slice | 50% of 4000 ms: every cycle peaked at 32-37 MiB and fell back to 0-3 MiB; baseline peak 10-11 MiB |
| `DutyCyclePercent` | Fraction of time the stream is held | Requested 50% / 75%, effective 50.0% / 75.0% |

**Average throughput is not a dial.** In the same measurements the replica kept up on average at every duty cycle up to 90%, because it applies the backlog in the gap far faster than writes arrive. To make a replica fall behind on average you need writes near the replica's apply rate, or a duty cycle near 100%, which is the single-pause mode.

Safety in this mode:

- Before every pause the replica's role is re-read over the data plane. A node that no longer reports `role:slave` — for example after a failover promoted it — is dropped from the injection rather than paused as a primary.
- If the loop falls behind schedule (a slow replica, or observation taking longer than the gap), missed cycles are skipped, never issued back to back. The summary reports the effective duty cycle and any skipped cycles.
- Observation is sampled just before a pause slice expires, where the backlog peaks. Sampling at the start of a slice only ever sees the trough of the sawtooth.
- Set the FIS action's `duration` to cover `DurationSeconds` plus the validate and restore steps. The template ships with `PT3M`, sized for the single-pause defaults.

**CloudWatch cannot see short pause slices.** During a 60-second run at 50% of 4000 ms, the CloudWatch `ReplicationLag` maximum for the paused replica stayed at 0.001-0.009 seconds while the offset gap rose to 37 MiB every cycle. Neither `ReplicationLag` nor the `lag` field of `INFO replication` resolves a stall of a few seconds. Use `master_repl_offset` minus the replica's `offset` on the primary, which the document logs, or your application's own staleness signal.

## Validation

Validated end to end against two live replication groups in `ap-northeast-1`,
both running **Valkey 8.2** on `cache.t4g.micro`.

**Cluster mode disabled** (1 primary in `ap-northeast-1a`, 1 replica in
`ap-northeast-1c`). With write traffic present, the replica's acknowledged
offset froze while the primary advanced and the link stayed `online`:

```
master_repl_offset=109213724521  slave0(offset=109021347493, lag=3s,  state=online)
master_repl_offset=109218366559  slave0(offset=109021347493, lag=28s, state=online)
```

**Cluster mode enabled** (3 shards x 2 nodes). `TargetShardId=0002`,
`PauseMode=WRITE`, 25-second pause, cluster-aware write load spread across all
slots. Only the targeted shard stalled; the other two tracked their primaries
throughout and acted as controls:

| elapsed | shard 0001 replica | **shard 0002 replica** | shard 0003 replica |
|---|---|---|---|
| +6s | 82952549 | **66163374** | 83108186 |
| +12s | 104020083 | **66163374** | 104258492 |
| +18s | 124803283 | **66163374** | 125022580 |
| +24s | 145465515 | **66163374** | 145678460 |
| +30s | 166522453 | 166227863 (caught up) | 166731140 |

After the pause expired, shard 0002's replica applied roughly 100 MB of backlog
and returned to `master_link_status=up` with `master_sync_in_progress=0`.

**Monitoring blind spot, sustained.** On the same sharded group, one shard's replica was held stalled for 11 minutes. Throughout, the primary's `INFO replication` reported `lag` of 0–1 seconds and `state=online`, and the replication group stayed `available`; CloudWatch `ReplicationLag` for that replica rose from 52 to 592 seconds, one minute per minute, while the untargeted shards stayed at 0.001 seconds.

**Write rejection with `min-replicas-to-write=1`** (cluster mode disabled, 4 writer threads × 4 KiB × pipeline 50 over a fixed 80 MiB keyspace, `PauseMode=ALL`, 30-second pause): first `-NOREPLICAS` at 15.3 s, then every write rejected until 183 s. The replica's `SwapUsage` rose from 176 to 323 MiB while its engine CPU stayed at 0–5%; the link dropped at about 73 s and recovery followed a full resynchronisation.

**Duty-cycle mode.** Cluster mode disabled, `DutyCyclePercent=50`, `CyclePeriodMilliseconds=4000`, 40 seconds, about 12 MiB/s of writes over a fixed keyspace: 10 pauses issued, 0 failed, effective duty 50.0%; the replica's offset gap peaked at 37 MiB against a 10 MiB baseline, the link stayed `online`, and 0 writes failed. Cluster mode enabled, `TargetShardId=0002` on a shard with two replicas, `DutyCyclePercent=75`, about 8 MiB/s into that shard: the targeted replica peaked at 31 MiB while the shard's other replica stayed at its 7.5 MiB baseline. A single-pause run (`DutyCyclePercent=0`) on the same cluster behaved as before.

Also verified: the idempotency guard refuses a second `validate`; an unknown
`TargetShardId` is rejected before anything is injected; a run **without** write
traffic correctly shows no replication gap, which is why flowing writes are an
explicit prerequisite.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until the pause expires and the RestoreAndVerify step has completed on the targeted instance.

Stop conditions are based on an AWS CloudWatch alarm based on an operational or 
business metric requiring an immediate end of the fault injection. This 
template makes no assumptions about your application and the relevant metrics 
and does not include stop conditions by default.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case. This template deliberately requires two tags on the injector instance, `FIS-Ready=True` and `FIS-Role=ElastiCacheInjector`, so that the command is not sent to unrelated instances.
2. Identifying business metrics tied to cached reads — for example cache hit ratio, read latency, and any correctness signal that would expose a stale read.
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of the replication stall. `ReplicationLag` is the primary signal for stalls lasting tens of seconds or more; it does not resolve the few-second pause slices of duty-cycle mode, so for that mode alarm on the offset gap instead. Do not build the alarm on the `lag` field of `INFO replication` or on `connected_slaves`: neither moves while the stream is stalled.
4. Adding a stop condition tied to the alarm to automatically halt the experiment if critical thresholds are breached.
5. Running the experiment in a non-production environment first, and confirming there that `CLIENT PAUSE` is permitted on your cluster and engine version before scheduling it anywhere else.
6. Extending the document to read an auth token from AWS Secrets Manager if your clusters use an auth token or RBAC.
7. Pairing this experiment with `elasticache-az-power-interruption` for coverage of the abrupt failure mode. This template covers gradual degradation with the link intact; that one covers the node disappearing.

## Import Experiment
You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).

## Files in This Directory

| File | Purpose |
|---|---|
| `README.md` | This document |
| `README.zh-CN.md` | Chinese translation |
| `AWSFIS.json` | Template version marker |
| `elasticache-replication-stall-template.json` | FIS experiment template |
| `elasticache-replication-stall-ssm-template.yaml` | SSM Command document that performs the injection |
| `elasticache-replication-stall-iam-policy.json` | Policy for the FIS experiment role |
| `elasticache-replication-stall-injector-instance-policy.json` | Policy for the injector instance profile (`DescribeReplicationGroups` + `DescribeCacheClusters`) |
| `fis-iam-trust-relationship.json` | Trust relationship for the FIS experiment role |
