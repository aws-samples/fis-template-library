# AWS Fault Injection Service Experiment: Amazon MSK Broker Reboot

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Example Hypothesis

When a single Amazon MSK broker is rebooted, the cluster should remain available and continue serving produce and consume requests using the remaining brokers, after a brief and recoverable disruption while partition leadership moves off the rebooted broker. Specifically:

- Partition leadership for partitions led by the rebooted broker should automatically move to in-sync replicas on other brokers. Clients briefly see retriable errors (for example `NotLeaderOrFollowerException`) for those partitions, refresh metadata, and reconnect to the new leaders — typically within seconds.
- With a replication factor of 3 and `min.insync.replicas=2`, producers using `acks=all` (and idempotence enabled) should continue writing without data loss across the leadership change.
- `UnderReplicatedPartitions` may rise briefly while the broker is down but should return to 0 after recovery.
- `OfflinePartitionsCount` should remain 0 throughout (no partition should lose all replicas).
- The broker should rejoin the cluster and the cluster should return to `ACTIVE` within a few minutes, and the surviving brokers should absorb the rebooted broker's share of load (expect a temporary CPU increase, since one of three brokers represents roughly a third of cluster capacity).

### What does this enable me to verify?

* Your MSK cluster is configured for resilience (replication factor ≥ 3, `min.insync.replicas` ≥ 2, brokers spread across Availability Zones).
* Producer and consumer clients reconnect to new partition leaders gracefully and retry transient failures.
* Appropriate MSK monitoring and alarms are in place (were you able to detect the broker reboot and the recovery?).
* Your application tolerates the temporary loss of broker capacity without breaching business SLAs.

## Prerequisites

Before running this experiment, ensure that:

1. You have the roles created for FIS and SSM Automation to use. Example IAM policy documents and trust policies are provided (`msk-broker-reboot-fis-role-iam-policy.json`, `msk-broker-reboot-ssm-role-iam-policy.json`, `fis-iam-trust-relationship.json`, `ssm-iam-trust-relationship.json`).
2. You have created the SSM Automation Document from the sample provided (`msk-broker-reboot-automation.yaml`) with the name `msk-broker-reboot-automation`.
3. You have created the FIS Experiment Template from the sample provided (`msk-broker-reboot-experiment-template.json`) and replaced all placeholder values (`<YOUR ...>`).
4. The MSK cluster you want to target is a **provisioned** cluster (not Serverless), is in the `ACTIVE` state, and has the `FIS-Ready=True` tag applied. The SSM automation role's `kafka:RebootBroker` permission is scoped with a `FIS-Ready=True` resource-tag condition, so an untagged cluster is both skipped by discovery and denied the reboot.
5. Your cluster has a replication factor of at least 3 across at least 2 (ideally 3) Availability Zones, with `min.insync.replicas` set to at least 2, so a single broker reboot does not cause data loss or offline partitions.
6. You have appropriate monitoring and observability in place to track the impact of the experiment (see Observability below).

## How it works

This experiment reboots a single MSK broker to test cluster resilience and partition leader failover. The reboot is implemented using an SSM Automation Document invoked by FIS, because AWS FIS does not provide a native `aws:msk` action — the `RebootBroker` MSK API is the supported way to restart a broker. The automation follows this sequence:

1. **Dynamic Discovery**: Scans MSK clusters and selects the first `ACTIVE`, provisioned cluster tagged with `FIS-Ready=True`.
2. **Broker Selection**: Lists the cluster's broker nodes and selects a broker to reboot. By default (`brokerSelection=random`) it picks the lowest broker ID for a deterministic, repeatable target; you can instead pass a specific broker ID.
3. **Broker Reboot**: Calls the MSK `RebootBroker` API for the selected broker. (`RebootBroker` reboots exactly one broker per invocation.)
4. **Recovery Monitoring**: Polls `DescribeClusterOperation` until the reboot operation reaches a terminal `*COMPLETE` state (for a broker reboot this is `REBOOT_COMPLETE`), then reports the current cluster state. If the operation reaches a `*FAILED` state, or does not reach a terminal state within the monitoring window, the automation raises an error so the FIS experiment is marked as failed. The monitoring window is bounded to stay within the AWS Systems Manager `aws:executeScript` 600-second handler limit.

To verify the experiment is working properly, you can monitor cluster and broker state and watch your client traffic:

```bash
# Watch the reboot cluster operation
aws kafka list-cluster-operations-v2 --cluster-arn <YOUR-CLUSTER-ARN> \
  --query 'ClusterOperationInfoList[0].{Type:OperationType,State:OperationState}'

# Watch cluster state return to ACTIVE
watch -n 10 'aws kafka describe-cluster-v2 --cluster-arn <YOUR-CLUSTER-ARN> --query "ClusterInfo.State"'
```

During the experiment, the targeted broker restarts and rejoins the cluster, and partition leadership rebalances. The reboot cluster operation (`OperationType=REBOOT_NODE`) moves through `PENDING` / `UPDATE_IN_PROGRESS` to the terminal state `REBOOT_COMPLETE`, typically within a few minutes. The automation treats any terminal `*COMPLETE` operation state as success and any `*FAILED` state as failure.

## Expected application impact and client resilience

A broker reboot is not transparent to clients — there is a brief window while leadership moves to other brokers. What a well-configured application experiences, and the settings that make it resilient:

- **Leadership moves, clients catch up.** Partitions led by the rebooted broker become temporarily unavailable until a new leader is elected. Kafka clients receive retriable errors (such as `NotLeaderOrFollowerException` / `LEADER_NOT_AVAILABLE`), refresh cluster metadata, and route to the new leader. Applications should treat these as transient and rely on client retries rather than surfacing errors to users.
- **Connect to multiple brokers.** Configure clients with more than one broker in `bootstrap.servers` so they can still reach the cluster and discover new leaders when one broker is down.
- **Producer durability and retry settings:**
  - `acks=all` — wait for all in-sync replicas, so a leadership change does not lose acknowledged writes.
  - `enable.idempotence=true` — prevents duplicates on retry and preserves ordering (requires `max.in.flight.requests.per.connection` ≤ 5).
  - `delivery.timeout.ms` set high enough (for example 120000) to ride out the leader election rather than failing the send; `retries` left at the default high value with `retry.backoff.ms` to pace reconnection attempts.
- **Consumer behavior:** consumers may experience a partition rebalance and a short pause in consumption when the group coordinator or a partition leader moves. Tune `session.timeout.ms` and `heartbeat.interval.ms` so transient unavailability does not eject consumers unnecessarily, and ensure consumers commit offsets so they resume cleanly.
- **Capacity headroom.** With one of three brokers temporarily down, the survivors carry its load. Keep steady-state broker CPU (CPU User + CPU System) with enough headroom (AWS recommends under 60%) so the cluster can absorb a broker loss without saturating.

If your application surfaces errors to end users, drops messages, or stalls for longer than your SLA allows during this experiment, that indicates client retry/timeout settings, `acks`, replication factor, or capacity need tuning.

## Stop Conditions

The experiment does not have any specific stop conditions defined by default. The reboot completes automatically when the broker rejoins and the cluster returns to `ACTIVE`. Because `RebootBroker` requires the cluster to be `ACTIVE` (it errors during `HEALING`), this experiment targets one broker per run; do not run multiple broker-reboot experiments against the same cluster concurrently.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

### Recommended Metrics for Stop Conditions

Consider creating CloudWatch alarms on these Amazon MSK metrics (all available at the free `DEFAULT` monitoring level unless noted):

- `OfflinePartitionsCount` — should be `0`; alarm if it exceeds 0 (partitions with no available leader — the most severe availability signal).
- `UnderMinIsrPartitionCount` — partitions below `min.insync.replicas`; with `acks=all`, writes to these partitions are rejected.
- `UnderReplicatedPartitions` — expected to rise briefly during the reboot and return to 0; a sustained non-zero value indicates replication is not catching up.
- `ActiveControllerCount` — should equal exactly `1` across the cluster (deviation indicates a controller election problem; note this metric is unreliable on KRaft-based clusters).

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case. The default tag is `FIS-Ready=True`.
2. Identifying business metrics tied to your MSK workload (producer throughput, end-to-end latency, consumer lag such as `EstimatedMaxTimeLag` and `MaxOffsetLag`).
3. Creating Amazon CloudWatch metrics and alarms to monitor cluster availability (`OfflinePartitionsCount`, `UnderReplicatedPartitions`) and consumer impact.
4. Adding a stop condition tied to a critical alarm to automatically halt the experiment if thresholds are breached.
5. Verifying your producer and consumer clients are configured with sensible retries, `acks=all`, and reconnection behavior.
6. Testing in a non-production environment first to validate cluster behavior before running against production clusters.
7. Documenting the findings from your experiment and updating your incident response procedures accordingly.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
