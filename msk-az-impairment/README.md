# AWS Fault Injection Service Experiment: Amazon MSK Availability Zone Impairment

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Example Hypothesis

When an Availability Zone hosting one of an Amazon MSK cluster's brokers becomes unreachable, the cluster should continue serving produce and consume requests from the brokers in the remaining Availability Zones, after a brief and recoverable disruption while leadership moves out of the impaired AZ. Specifically:

- Brokers in the impaired AZ become unreachable from clients and from the other brokers, simulating an AZ-level network failure.
- Partition leadership for partitions led by brokers in the impaired AZ moves to in-sync replicas in the healthy AZs. Clients briefly see retriable errors for those partitions, refresh metadata, and reconnect to leaders in the healthy AZs — typically within seconds.
- With a replication factor of 3 across 3 AZs and `min.insync.replicas=2`, producers using `acks=all` (and idempotence enabled) continue writing without data loss, because two healthy in-sync replicas remain.
- `UnderReplicatedPartitions` rises while the AZ is impaired (replicas in the impaired AZ fall behind) but `OfflinePartitionsCount` remains 0.
- When connectivity is restored, the brokers in the recovered AZ rejoin, replicas catch up, and `UnderReplicatedPartitions` returns to 0.

### What does this enable me to verify?

* Your MSK cluster spans at least 3 Availability Zones with a replication factor of 3, so it can tolerate the loss of a single AZ.
* Producer and consumer clients are configured with multiple bootstrap brokers and retry/reconnect logic so they fail over to brokers in healthy AZs.
* Appropriate MSK monitoring and alarms are in place (were you able to detect the AZ impairment and the recovery?).
* Your application maintains its availability and latency SLAs during the loss of one Availability Zone.

## Prerequisites

Before running this experiment, ensure that:

1. You have the IAM role created for FIS to use. An example IAM policy document and trust policy are provided (`msk-az-impairment-iam-policy.json`, `fis-iam-trust-relationship.json`).
2. You have created the FIS Experiment Template from the sample provided (`msk-az-impairment-experiment-template.json`) and replaced all placeholder values (`<YOUR ...>`).
3. The MSK cluster you want to target is deployed across at least 3 Availability Zones with a replication factor of 3 and `min.insync.replicas` of at least 2, so the cluster can tolerate the loss of one AZ without data loss or offline partitions.
4. You have identified the subnet ID of the MSK broker in the Availability Zone you want to impair, and set it as the target subnet ARN in the experiment template.
5. You have appropriate monitoring and observability in place to track the impact of the experiment (see Observability below).

## How it works

This experiment simulates an Availability Zone impairment for an MSK cluster using the native `aws:network:disrupt-connectivity` FIS action with the `availability-zone` scope. AWS FIS does not provide a native `aws:msk` action, so AZ-level faults are injected at the network layer that the brokers depend on.

The action targets the subnet containing the MSK broker(s) in the Availability Zone you want to impair. With `scope=availability-zone`, FIS temporarily clones the subnet's network ACL (tagged `managedByFIS=true`), adds deny rules that block intra-VPC traffic to and from subnets in other Availability Zones, and associates the cloned ACL with the target subnet for the duration of the action. When the action completes (or the experiment is stopped), FIS restores the original network ACL association and deletes the clone.

The result is that the broker(s) in the target AZ can no longer communicate with the brokers and clients in the other AZs, which mirrors a real Availability Zone partition. Because the change is implemented as a network ACL swap with automatic restoration, the impairment is cleanly reverted at the end of the experiment.

To verify the experiment is working properly, monitor cluster health and your client traffic during the action:

```bash
# Watch under-replicated partitions and offline partitions during the impairment
aws cloudwatch get-metric-statistics --namespace AWS/Kafka \
  --metric-name UnderReplicatedPartitions \
  --dimensions Name="Cluster Name",Value=<YOUR-CLUSTER-NAME> \
  --start-time "$(date -u -v-10M +%Y-%m-%dT%H:%M:%SZ)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --period 60 --statistics Maximum

# Confirm FIS created and then removed the managedByFIS network ACL
aws ec2 describe-network-acls --filters "Name=tag:managedByFIS,Values=true" \
  --query 'NetworkAcls[].NetworkAclId'
```

During the experiment you should observe `UnderReplicatedPartitions` rise for the impaired AZ's replicas and return to 0 after the action ends, while `OfflinePartitionsCount` stays at 0 if the cluster is configured for AZ resilience.

## Expected application impact and client resilience

Losing an Availability Zone removes a portion of the cluster's brokers at once, so the impact is broader than a single broker reboot but should still be recoverable with the right configuration. What a well-configured application experiences, and the settings that make it resilient:

- **Leadership leaves the impaired AZ.** All partitions led by brokers in the impaired AZ fail over to in-sync replicas in the healthy AZs. Clients receive retriable errors (such as `NotLeaderOrFollowerException` / `LEADER_NOT_AVAILABLE`), refresh metadata, and reconnect to leaders in the healthy AZs. Connections to brokers in the impaired AZ time out, so client connection and request timeouts govern how quickly clients shift away.
- **Connect to multiple brokers across AZs.** Configure clients with brokers from more than one AZ in `bootstrap.servers` so they can still reach the cluster when an entire AZ is unreachable.
- **Producer durability and retry settings:**
  - `acks=all` with `enable.idempotence=true` — preserves acknowledged writes and ordering across the failover (requires `max.in.flight.requests.per.connection` ≤ 5).
  - `delivery.timeout.ms` set high enough (for example 120000) to ride out the failover instead of failing sends; pace retries with `retry.backoff.ms`.
- **Consumer behavior:** expect a partition rebalance and a short consumption pause as the group coordinator and partition leaders move to healthy AZs. Tune `session.timeout.ms` and `heartbeat.interval.ms` so the transient AZ loss does not eject consumers unnecessarily.
- **Know the safety boundary.** With replication factor 3 across 3 AZs and `min.insync.replicas=2`, the cluster tolerates the loss of one AZ. While one AZ is impaired, only one redundant replica remains for affected partitions — losing a second AZ (or a broker in a healthy AZ) at the same time would drop the in-sync replica count below `min.insync.replicas` and block `acks=all` writes (`UnderMinIsrPartitionCount` rises). Do not run this experiment alongside another fault that removes a second AZ or broker.

> **Monitoring note:** Consumer-lag metrics are only emitted while a consumer group is in a `STABLE` or `EMPTY` state, so they can briefly disappear during the rebalance triggered by the AZ impairment. Rely on `UnderReplicatedPartitions`, `OfflinePartitionsCount`, and `UnderMinIsrPartitionCount` for availability signals during the action, and use consumer lag to confirm consumers catch up afterward.

If your application surfaces errors to end users, drops messages, or stalls for longer than your SLA allows during this experiment, that indicates client retry/timeout settings, broker/AZ spread, replication factor, or capacity need tuning.

## Stop Conditions

The experiment does not have any specific stop conditions defined by default. It runs for the configured `duration` (default 5 minutes) and then FIS automatically restores the original network ACL association. You can stop the experiment at any time, which also triggers the restoration.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

### Recommended Metrics for Stop Conditions

Consider creating CloudWatch alarms on these Amazon MSK metrics (all available at the free `DEFAULT` monitoring level unless noted):

- `OfflinePartitionsCount` — should be `0`; alarm if it exceeds 0 (partitions with no available leader — the most severe availability signal).
- `UnderMinIsrPartitionCount` — partitions below `min.insync.replicas`; with `acks=all`, writes to these partitions are rejected.
- `UnderReplicatedPartitions` — expected to rise during the impairment and return to 0 after recovery; alarm on a sustained high value.
- `ActiveControllerCount` — should equal exactly `1` across the cluster (note this metric is unreliable on KRaft-based clusters).

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the target subnet to ensure it corresponds to the Availability Zone you intend to impair. You can target multiple broker subnets in the same AZ by adding their ARNs to the target.
2. Identifying business metrics tied to your MSK workload (producer throughput, end-to-end latency, consumer lag such as `EstimatedMaxTimeLag` and `MaxOffsetLag`).
3. Creating Amazon CloudWatch metrics and alarms to monitor cluster availability (`OfflinePartitionsCount`, `UnderReplicatedPartitions`) and consumer impact.
4. Adding a stop condition tied to a critical alarm to automatically halt the experiment if thresholds are breached.
5. Verifying your producer and consumer clients use multiple bootstrap brokers and reconnect to leaders in healthy AZs.
6. Testing in a non-production environment first to validate cluster behavior before running against production clusters.
7. Gradually increasing the impairment duration as confidence grows, and documenting findings to build an AZ-failure runbook.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
