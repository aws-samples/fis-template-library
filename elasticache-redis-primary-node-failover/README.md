# AWS Fault Injection Service Experiment: ElastiCache Redis Primary Node Failover

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

When the Redis primary node fails over to a replica, applications should detect the failover and reconnect to the new primary within 30 seconds. Connection pooling should handle the DNS endpoint changes gracefully, and no data should be lost during the transition. Application performance should return to normal within 60 seconds of failover completion.

### What does this enable me to verify?

* Appropriate Redis connection monitoring and observability is in place (were you able to detect the failover?)
* Alarms are configured correctly for primary node changes (were the right people notified?)
* Your application handles Redis primary node changes gracefully
* Connection pooling and DNS resolution work correctly during failover
* Recovery controls and reconnection logic work as expected

## Prerequisites

Before running this experiment, ensure that:

1. You have created two IAM roles: one for FIS (trust policy `fis-iam-trust-relationship.json`, permissions `elasticache-redis-primary-node-failover-fis-role-iam-policy.json`) and one for SSM Automation (trust policy `ssm-iam-trust-relationship.json`, permissions `elasticache-redis-primary-node-failover-ssm-role-iam-policy.json`). Replace `<YOUR REGION>` and `<YOUR AWS ACCOUNT>` in both policies, and `<YOUR SSM AUTOMATION ROLE NAME>` in the FIS role policy.
2. You have created the SSM Automation document `ElastiCache-Redis-Primary-Node-Failover` from `elasticache-redis-primary-node-failover-automation.json`. The FIS template and the FIS role policy refer to the document by this name.
3. You have created the FIS experiment template from `elasticache-redis-primary-node-failover-experiment-template.json`, replacing `<YOUR REGION>`, `<YOUR AWS ACCOUNT>`, `<YOUR ROLE NAME>` (the FIS role) and `<YOUR SSM AUTOMATION ROLE NAME>` (the SSM Automation role).
4. The ElastiCache (Redis OSS) replication groups you want to target have the `FIS-Ready=True` tag. The experiment fails over the primary of the first node group (shard) of every replication group in the Region that carries this tag.
5. Each targeted replication group has Multi-AZ enabled with `AutomaticFailover=enabled`, at least 1 primary + 1 replica node, and is in `available` status. If any tagged group does not meet this, the experiment fails before it fails over anything.
6. TestFailover can fail over at most 15 node groups (shards) in any rolling 24-hour period ([TestFailover API reference](https://docs.aws.amazon.com/AmazonElastiCache/latest/APIReference/API_TestFailover.html)). Plan repeated runs within that quota.
7. You have appropriate monitoring and observability in place to track the impact of the experiment.

## How it works

This experiment forces a Redis primary node failover by using the ElastiCache TestFailover API to promote a replica node to primary. FIS starts the SSM Automation document, which runs these steps:

1. **triggerFailover**: Lists the replication groups in the Region and keeps the ones tagged `FIS-Ready=True`. It checks that each one is `available` with `AutomaticFailover=enabled`, then calls `TestFailover` for each. An API error, for example a missing permission, fails the step with that error.
2. **waitForFailover**: Waits (up to 5 minutes) until ElastiCache reports the event `Failover from master node ... to replica node ... completed` for each group, and the group is `available` with one primary.
3. **waitForRecovery** and **waitForRecoveryContinued**: Wait until ElastiCache reports `Finished recovery for cache nodes ...` for the former primary. An `aws:executeScript` step runs for at most 10 minutes, so the wait is split over two steps (up to 18 minutes in total). FIS keeps the action running until this wait ends, so the experiment covers the whole failover and recovery.
4. **verifyHealthy**: Runs only if a step fails or the experiment is stopped. It checks, for up to about 90 seconds, whether every tagged group is `available` with one primary and no failover or node recovery still in progress according to the group's events, and reports what it found in its output. A failover that has started cannot be undone: stopping the experiment stops the waiting, and ElastiCache finishes the failover and the recovery on its own.

ElastiCache updates the primary endpoint to point to the new primary, and the former primary becomes a replica. The original primary does not come back; the roles stay swapped.

> **Note**: Measured in four test runs on a two-node Redis OSS 7.1 replication group (`cache.t4g.micro`) in `us-east-1`, with a client opening a new connection to the primary endpoint every second:
>
> * Writes on the primary endpoint failed for 26 to 38 seconds after `TestFailover` was called (30, 35, 38 and 26 seconds).
> * The former primary did not answer clients until just before ElastiCache reported `Finished recovery for cache nodes`, 9 to 11 minutes after `TestFailover` was called. Until then the group had no working replica.
> * No acknowledged writes were lost.

To verify the experiment is working properly, you can monitor the primary node before and after:

```bash
# Check current primary before experiment
aws elasticache describe-replication-groups --replication-group-id <YOUR-CLUSTER-ID> --query 'ReplicationGroups[0].NodeGroups[0].NodeGroupMembers[?CurrentRole==`primary`].CacheClusterId'

# Monitor during experiment
watch -n 5 'aws elasticache describe-replication-groups --replication-group-id <YOUR-CLUSTER-ID> --query "ReplicationGroups[0].Status"'

# List the failover events
aws elasticache describe-events --source-type replication-group --source-identifier <YOUR-CLUSTER-ID> --duration 60
```

In testing, the group status stayed `available` the whole time, so follow the failover with the events command. You should see, in order, `Test Failover API called for node group <id>` and `Failover from master node <old primary> to replica node <new primary> completed`. The former primary's own events (`--source-type cache-cluster --source-identifier <old primary>`) then show `Recovering cache nodes` and, several minutes later, `Finished recovery for cache nodes`.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until the failover has completed and the former primary has recovered, or after 30 minutes (`maxDuration`). Stopping it early does not reverse a failover that has started.

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to your Redis operations, such as cache hit rates and application response times.
3. Creating Amazon CloudWatch metrics and alarms to monitor Redis failover impact.
4. Adding stop conditions tied to critical business metrics to automatically halt the experiment if needed.
5. Implementing appropriate connection retry logic in your application to handle primary node changes.
6. Testing your application's Redis connection pooling and DNS resolution during failover scenarios.
7. Documenting the findings from your experiment and updating your incident response procedures accordingly.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
