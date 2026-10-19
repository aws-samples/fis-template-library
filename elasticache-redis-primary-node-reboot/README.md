# AWS Fault Injection Service Experiment: ElastiCache Redis Primary Node Reboot

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

> **Warning**: Rebooting a primary node clears its data, and ElastiCache does not fail over to a replica. AWS documents that "when the primary is rebooted, it's cleared of data when it comes back online. When the read replicas see the cleared primary cluster, they clear their copy of the data, which causes data loss" ([Minimizing downtime in ElastiCache by using Multi-AZ](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/AutoFailover.html)). Run this experiment only on replication groups whose contents you can afford to lose.

## Hypothesis

When the Redis primary node is rebooted, applications should detect the brief connection disruption and reconnect automatically within 30 seconds. Connection pooling should handle the temporary unavailability gracefully. Because the reboot clears the cached data, applications should treat the cache as empty afterwards and repopulate it from their source of truth without errors. Application performance should return to normal within 60 seconds of the node becoming available again.

### What does this enable me to verify?

* Appropriate Redis connection monitoring and observability is in place (were you able to detect the reboot?)
* Alarms are configured correctly for node availability changes (were the right people notified?)
* Your application handles brief Redis connection disruptions gracefully
* Connection pooling and retry logic work correctly during node reboots
* Your application copes with an emptied cache (cache misses, repopulation, load on the source of truth)
* Recovery controls and reconnection mechanisms work as expected

## Prerequisites

Before running this experiment, ensure that:

1. You have created two IAM roles: one for FIS (trust policy `fis-iam-trust-relationship.json`, permissions `elasticache-redis-primary-node-reboot-fis-role-iam-policy.json`) and one for SSM Automation (trust policy `ssm-iam-trust-relationship.json`, permissions `elasticache-redis-primary-node-reboot-ssm-role-iam-policy.json`). Replace `<YOUR REGION>` and `<YOUR AWS ACCOUNT>` in both policies, and `<YOUR SSM AUTOMATION ROLE NAME>` in the FIS role policy.
2. You have created the SSM Automation document `ElastiCache-Redis-Primary-Node-Reboot` (document format YAML) from `elasticache-redis-primary-node-reboot-automation.yaml`. The FIS template and the FIS role policy refer to the document by this name.
3. You have created the FIS experiment template from `elasticache-redis-primary-node-reboot-experiment-template.json`, replacing `<YOUR REGION>`, `<YOUR AWS ACCOUNT>`, `<YOUR ROLE NAME>` (the FIS role) and `<YOUR SSM AUTOMATION ROLE NAME>` (the SSM Automation role).
4. The ElastiCache (Redis OSS) replication groups you want to target have the `FIS-Ready=True` tag. ElastiCache adds a replication group's tags to all of its clusters, and the SSM role policy allows `RebootCacheCluster` only on clusters with this tag. If you change the tag in the template, change it in the policy too. The experiment reboots the primary node of every replication group in the Region that carries the tag.
5. Each targeted replication group is cluster mode disabled (`RebootCacheCluster` does not support cluster mode enabled), has Multi-AZ enabled with `AutomaticFailover=enabled`, has at least 1 primary + 1 replica node, and is in `available` status. If any tagged group does not meet this, the experiment fails before it reboots anything.
6. Losing the data in the targeted replication groups is acceptable (see the warning above).
7. You have appropriate monitoring and observability in place to track the impact of the experiment.

## How it works

This experiment reboots the Redis primary node to test application resilience during a brief connection disruption. FIS starts the SSM Automation document, which runs these steps:

1. **rebootPrimaryNode**: Lists the replication groups in the Region and keeps the ones tagged `FIS-Ready=True`. It checks that each one is `available`, has `AutomaticFailover=enabled` and is cluster mode disabled, then calls `RebootCacheCluster` on the primary node of each. An API error, for example a missing permission, fails the step with that error.
2. **waitForReboot** and **waitForRebootContinued**: Wait until ElastiCache reports the event `Cache node <id> restarted` for each rebooted node, and the cluster, the node and the replication group are `available` again. An `aws:executeScript` step runs for at most 10 minutes, so the wait is split over two steps (up to 18 minutes in total). FIS keeps the action running until this wait ends.
3. **verifyHealthy**: Runs only if a step fails or the experiment is stopped. It checks, for up to about 30 seconds, whether every tagged group is `available` with one primary and every cluster and node `available`, and reports what it found in its output. Automation gives a cancelled run at most two minutes to finish, so this check is kept short. A reboot that ElastiCache has accepted cannot be cancelled: stopping the experiment stops the waiting, and the node still restarts and loses its data.

ElastiCache does not fail over when you reboot a primary: the same node stays primary, and the primary endpoint keeps pointing to it.

To verify the experiment is working properly, you can monitor the node status and test connectivity:

```bash
# Find the primary cluster
aws elasticache describe-replication-groups --replication-group-id <YOUR-CLUSTER-ID> --query 'ReplicationGroups[0].NodeGroups[0].NodeGroupMembers[?CurrentRole==`primary`].CacheClusterId'

# Check the primary cluster and node status
aws elasticache describe-cache-clusters --cache-cluster-id <PRIMARY-CLUSTER-ID> --show-cache-node-info --query 'CacheClusters[0].[CacheClusterStatus,CacheNodes[0].CacheNodeStatus]'

# List the reboot events
aws elasticache describe-events --source-type cache-cluster --source-identifier <PRIMARY-CLUSTER-ID> --duration 60

# Monitor Redis connectivity during reboot
watch -n 5 'redis-cli -h <redis-endpoint> ping'

# Monitor application health
curl -I https://<your-app>/health
```

During the experiment, the cluster status changes from `available` to `rebooting cache cluster nodes` as soon as the reboot is requested. The node status changes to `rebooting` only when the node actually restarts. Then the event `Cache node 0001 restarted` appears, and the cluster and node return to `available`.

> **Note**: Measured in seven test runs on a two-node Redis OSS 7.1 replication group (`cache.t4g.micro`) in `us-east-1`, with a client opening a new connection to the primary endpoint every second:
>
> * The node kept serving for 2 to 4 minutes after `RebootCacheCluster` was called (112 to 247 seconds), then restarted.
> * Writes on the primary endpoint failed for 6 to 7 seconds while it restarted. The same node stayed primary.
> * After every restart the data was gone: a counter that had been incremented between 1,164 and 31,137 times started again at 1.
> * The cluster showed `available` again 3 to 5 minutes after the call (186 to 310 seconds), about a minute after the node answered again.
> * Stopping the experiment within 10 seconds of the call did not prevent the restart or the data loss.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped, until the rebooted nodes are available again, or after 30 minutes (`maxDuration`). Stopping it early does not cancel a reboot that ElastiCache has accepted.

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to your Redis operations, such as connection counts and application response times.
3. Creating Amazon CloudWatch metrics and alarms to monitor Redis node availability and connection health.
4. Adding stop conditions tied to critical business metrics to automatically halt the experiment if needed.
5. Implementing appropriate connection retry logic in your application to handle brief node unavailability.
6. Testing your application's Redis connection pooling and recovery mechanisms.
7. Documenting the findings from your experiment and updating your incident response procedures accordingly.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
