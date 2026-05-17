# AWS Fault Injection Service Experiment: ElastiCache Primary Node Reboot

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

When the ElastiCache primary node is rebooted, applications experience a brief connection interruption (typically 1–3 minutes). The connection pool detects the disconnection and reconnects automatically once the node returns to `available` status. Unlike a failover (which swaps primary/replica roles), a reboot keeps the same node as primary, making this a useful test for connection pool recovery without topology changes. No data loss occurs and no cascading failures propagate to upstream services.

### What does this enable me to verify?

* Your application's Redis or Valkey client handles brief connection drops and reconnects automatically
* Connection pool retry and backoff logic functions correctly during a primary node restart
* Cache warming behavior after a node reboot (cold-cache effect on application performance)
* Single-node failure impact independent of an AZ-level event
* Difference between a node reboot (same primary, same role) vs. a failover (role swap, topology change)

## Prerequisites

Before running this experiment, ensure that:

1. You have the roles created for FIS and SSM Automation to use. Example IAM policy documents and trust policies are provided.
2. You have created the SSM Automation Document from the sample provided (`elasticache-primary-node-reboot-automation.yaml`).
3. You have created the FIS Experiment Template from the sample provided (`elasticache-primary-node-reboot-experiment-template.json`).
4. The target replication group has `ClusterEnabled: false` (cluster mode disabled). The `RebootCacheCluster` API is **not supported** on cluster-mode-enabled replication groups.
5. Update `<YOUR CACHE CLUSTER ID>` in the experiment template with the `CacheClusterId` of the primary node (e.g., `my-cluster-0001-001`).
6. You have identified the primary node's `CacheClusterId` using the command below.
7. You have appropriate monitoring and observability in place to track the impact of the experiment.

```bash
# Identify the primary node CacheClusterId
aws elasticache describe-replication-groups \
  --replication-group-id <YOUR-REPLICATION-GROUP-ID> \
  --query 'ReplicationGroups[0].NodeGroups[].NodeGroupMembers[].[CacheClusterId,CurrentRole]' \
  --output table
```

## How it works

This experiment uses an SSM Automation document invoked by FIS to reboot a specific primary node by `CacheClusterId`. This is a direct parameter-based approach suited for cases where the target cluster is already known.

The experiment follows this sequence:

1. **Reboot**: SSM Automation calls `RebootCacheCluster` on the specified `CacheClusterId`, rebooting node `0001`.
2. **Wait**: The automation polls `DescribeCacheClusters` until the node status returns to `available` (up to 10 minutes).
3. **Complete**: FIS marks the experiment as completed once the SSM document finishes successfully.

> **Note**: This action reboots the primary node in place — the same node remains primary after recovery. If you want to test a primary-replica role swap (topology change), use the `elasticache-replication-group-failover` template instead.

To monitor the node status during the experiment:

```bash
watch -n 10 'aws elasticache describe-cache-clusters \
  --cache-cluster-id <YOUR-CACHE-CLUSTER-ID> \
  --query "CacheClusters[0].CacheClusterStatus"'
```

## Stop Conditions

The experiment does not have any specific stop conditions defined. The reboot completes automatically when the node returns to `available` status.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Identifying the correct primary node `CacheClusterId` before running the experiment.
2. Verifying that cluster mode is disabled (`ClusterEnabled: false`) on your replication group.
3. Identifying business metrics tied to your cache layer, such as `CurrConnections`, `CacheHitRate`, and application error rates.
4. Creating Amazon CloudWatch alarms on `CurrConnections` drops and `CacheHitRate` degradation to detect the experiment impact.
5. Adding a stop condition tied to a critical business alarm to automatically halt the experiment if needed.
6. Implementing appropriate connection retry logic and exponential backoff in your Redis/Valkey client.
7. Comparing results with the `elasticache-replication-group-failover` template to understand the difference between a reboot and a full role swap.
8. Documenting the findings from your experiment and updating your incident response procedures accordingly.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
