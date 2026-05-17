# AWS Fault Injection Service Experiment: ElastiCache Replication Group Failover

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

When the ElastiCache `TestFailover` API is called on a replication group, a replica is promoted to primary and the former primary becomes a replica. The replication group transitions through `modifying` status and returns to `available` within 5 minutes. Applications using the primary endpoint reconnect automatically after the DNS update propagates. No data loss occurs because the promoted replica was fully in sync before the role swap. Unlike a node reboot, the primary identity and endpoint topology change, making this a more demanding test of connection pool behavior.

### What does this enable me to verify?

* ElastiCache automatic failover mechanism triggers a real primary-replica role swap
* Applications detect the primary endpoint topology change and reconnect without manual intervention
* DNS resolution and client-side endpoint caching behavior under a role swap event
* Connection pool behavior when the primary identity changes, not just when the node restarts
* For cluster-mode-enabled replication groups: shard-level failover targeting a specific `NodeGroupId`

## Prerequisites

Before running this experiment, ensure that:

1. You have the roles created for FIS and SSM Automation to use. Example IAM policy documents and trust policies are provided.
2. You have created the SSM Automation Document from the sample provided (`elasticache-replication-group-failover-automation.yaml`).
3. You have created the FIS Experiment Template from the sample provided (`elasticache-replication-group-failover-experiment-template.json`).
4. The target replication group has `AutomaticFailover=enabled` and Multi-AZ enabled.
5. The replication group has at least one primary and one replica node.
6. Update `<YOUR REPLICATION GROUP ID>` in the experiment template with the replication group ID.
7. For cluster-mode-disabled replication groups, `NodeGroupId` is always `0001`. For cluster-mode-enabled, specify the shard ID you want to failover (e.g., `0001`, `0002`).
8. You have appropriate monitoring and observability in place to track the impact of the experiment.

> **Rate limit**: The `TestFailover` API allows up to 15 node group failovers per rolling 24-hour period. For cluster-mode-enabled replication groups, wait for the first failover to complete before triggering another on the same replication group.

## How it works

This experiment uses an SSM Automation document invoked by FIS to trigger the ElastiCache `TestFailover` API. This is a direct parameter-based approach that calls the API with the specified `ReplicationGroupId` and `NodeGroupId`, then polls until the replication group returns to `available` status.

The experiment follows this sequence:

1. **Failover Trigger**: SSM Automation calls `TestFailover` with the specified `ReplicationGroupId` and `NodeGroupId`.
2. **Role Swap**: ElastiCache promotes the replica with the least replication lag to primary. The former primary becomes a replica.
3. **DNS Update**: ElastiCache automatically updates the primary endpoint DNS to point to the new primary node.
4. **Wait**: The automation polls `DescribeReplicationGroups` until the status returns to `available`.
5. **Complete**: FIS marks the experiment as completed.

> **Note**: The failover is permanent — roles are swapped and do not automatically revert. If you need to restore the original primary, run a second `TestFailover` experiment after the replication group is `available`.

To verify the role swap during the experiment:

```bash
# Monitor replication group status and node roles
watch -n 5 'aws elasticache describe-replication-groups \
  --replication-group-id <YOUR-REPLICATION-GROUP-ID> \
  --query "ReplicationGroups[0].{Status:Status,Members:NodeGroups[].NodeGroupMembers[].[CacheClusterId,CurrentRole]}" \
  --output json'
```

## Stop Conditions

The experiment does not have any specific stop conditions defined. The failover completes automatically when the replication group returns to `available` status.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Identifying the correct `ReplicationGroupId` and `NodeGroupId` before running the experiment.
2. For cluster-mode-enabled replication groups, choosing the specific shard (`NodeGroupId`) to failover.
3. Identifying business metrics tied to your cache layer, such as `ReplicationLag`, `IsPrimary`, and `CurrConnections`.
4. Creating Amazon CloudWatch alarms on `ReplicationLag` spikes, `IsPrimary` role changes, and `CurrConnections` drops to detect failover impact.
5. Adding a stop condition tied to a critical business alarm to automatically halt the experiment if needed.
6. Verifying your application uses the **primary endpoint** (not node-specific endpoints) so it benefits from automatic DNS updates during failover.
7. Implementing appropriate connection retry logic and a short DNS TTL awareness in your Redis/Valkey client.
8. Comparing results with the `elasticache-primary-node-reboot` template to understand the difference between a reboot (same primary) and a failover (role swap).
9. Documenting the findings from your experiment and updating your incident response procedures accordingly.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
