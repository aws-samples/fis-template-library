# AWS Fault Injection Service Experiment: ElastiCache Redis Primary Node Reboot

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

If the primary node of a tagged replication group is rebooted, the time your application can't write to the primary endpoint should not exceed 30 seconds, and your application's error rate should be back to its baseline within 60 seconds of the replication group showing `available` again. Because the reboot clears the cache, your application should then read from its source of truth and repopulate the cache without returning errors.

Measure this from your application: the time between the first and the last failed write to the primary endpoint, and its error rate per minute compared with the five minutes before the experiment. The hypothesis is false if writes fail for longer than 30 seconds, if the error rate is still above its baseline 60 seconds after the group shows `available`, or if requests fail while the cache is empty. The Amazon ElastiCache metrics `CacheMisses` and `CurrConnections` for the primary show the emptied cache and the reconnections. For the reconnect to work, your client needs connect and read timeouts and retries, and has to reconnect to the primary endpoint.

### What does this enable me to verify?

* Appropriate Redis connection monitoring and observability is in place (were you able to detect the reboot?)
* Alarms are configured correctly for node availability changes (were the right people notified?)
* Your application handles brief Redis connection disruptions gracefully
* Connection pooling and retry logic work correctly during node reboots
* Your application copes with an emptied cache (cache misses, repopulation, load on the source of truth)
* Recovery controls and reconnection mechanisms work as expected

## Prerequisites

Before running this experiment, ensure that:

1. You have created two IAM roles: one for FIS (trust policy `fis-iam-trust-relationship.json`, permissions `elasticache-redis-primary-node-reboot-fis-role-iam-policy.json`) and one for SSM Automation (trust policy `ssm-iam-trust-relationship.json`, permissions `elasticache-redis-primary-node-reboot-ssm-automation-role-iam-policy.json`). Replace `<YOUR REGION>` and `<YOUR AWS ACCOUNT>` in the policies and in both trust policies, and `<YOUR SSM AUTOMATION ROLE NAME>` in the FIS role policy.
2. You have created the SSM Automation document `ElastiCache-Redis-Primary-Node-Reboot` (document format YAML) from `elasticache-redis-primary-node-reboot-automation.yaml`. The FIS template and the FIS role policy refer to the document by this name.
3. You have created the FIS experiment template from `elasticache-redis-primary-node-reboot-experiment-template.json`, replacing `<YOUR REGION>`, `<YOUR AWS ACCOUNT>`, `<YOUR ROLE NAME>` (the FIS role) and `<YOUR SSM AUTOMATION ROLE NAME>` (the SSM Automation role).
4. The ElastiCache (Redis OSS) replication groups you want to target have the `FIS-Ready=True` tag. ElastiCache adds a replication group's tags to all of its clusters, and the SSM Automation role's policy allows `RebootCacheCluster` only on clusters with this tag. If you change `tagKey` or `tagValue` in the template, change the policy's condition too. The experiment reboots the primary node of every replication group in the Region that carries the tag, and refuses to run, before it reboots anything, if more than 20 groups carry it.
5. Each targeted replication group uses the Redis OSS engine, is cluster mode disabled (`RebootCacheCluster` does not support cluster mode enabled), has `MultiAZ=enabled` and `AutomaticFailover=enabled`, has one primary and at least one replica, is not a member of a Global Datastore, and is `available`, with its primary cluster and node `available`. The experiment checks each of these for every tagged group, and if any group fails one, it fails before it reboots anything. Valkey groups are refused.
6. Losing the data in the targeted replication groups is acceptable. Rebooting a primary node clears its data, and ElastiCache does not fail over to a replica. AWS documents that "when the primary is rebooted, it's cleared of data when it comes back online. When the read replicas see the cleared primary cluster, they clear their copy of the data, which causes data loss" ([Minimizing downtime in ElastiCache by using Multi-AZ](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/AutoFailover.html)). Run this experiment only on replication groups whose contents you can afford to lose.
7. You have appropriate monitoring and observability in place to track the impact of the experiment.
8. Tested with: Redis OSS 7.1, `cache.t4g.micro`, one primary and one replica, one and two tagged groups, in `eu-west-2`. Other engine versions, node types, more replicas, more tagged groups and other Regions have not been tested.

## How it works

This experiment reboots the Redis primary node to test application resilience during a brief connection disruption. FIS starts the SSM Automation document, which runs these steps:

1. **rebootPrimaryNode**: Lists every replication group in the Region, page by page, and keeps the ones tagged `FIS-Ready=True`. It fails if there are none. For each one it reads the group and its primary again and checks the conditions in Prerequisites item 5. If any group fails a check, the step fails and nothing is rebooted. It then calls `RebootCacheCluster` on the primary node of each group. Before each call it reads its own execution, and makes no more calls unless both the run and this step are still `InProgress`, in case SSM leaves the script running after a stop or a timeout. If that read fails, it makes no more calls. It also makes no call once 200 seconds have passed since the script started, checked after the read, so that a call, which gives up after about 80 seconds, ends inside the step's 300-second timeout. If a call fails, for example because of a missing permission, the step records the error and goes on to the other groups. If no call succeeds, the step fails.
2. **waitForReboot** and **waitForRebootContinued**: For each rebooted node, wait until it has restarted, and its cluster, the node, the replication group and every node in the group are `available` again. A node counts as restarted when its status was seen as `rebooting` after the call, or when ElastiCache records the event `Cache node <id> restarted` after the call. When the group is back, the step checks that the rebooted node is still the primary, and fails if it isn't. An `aws:executeScript` step runs for at most 10 minutes, so the wait is split over two steps (up to 17 minutes in total). It fails if the wait runs out, or if a cluster or group starts being deleted. At the end, if any reboot call failed in step 1, the run fails with that error once the other nodes are back. FIS keeps the action running until this wait ends.
3. **reportAfterFailure**: Runs only if a step fails. It finds the tagged groups again and checks, for about 30 seconds in all, whether every tagged group is `available` with one primary and every cluster and node `available`, prints what it found, and fails the run.
4. **reportAfterStop**: Runs only if the experiment is stopped. It makes the same check and prints what it found. Automation gives a cancelled run at most two minutes to finish, so the check is kept short. If it can't read every replication group in the Region in that time, it says so, and reports only the tagged groups it found.

If any group is still not healthy when the check's time runs out, both report steps print "Not healthy yet: {}" and list every group as not checked, including groups they found healthy, so the message doesn't say which group is still rebooting. Check the groups yourself with the commands below.

Each script retries throttled ElastiCache calls. The experiment changes nothing that it has to undo: there is no failover to reverse, and the cleared data can't be brought back.

ElastiCache does not fail over when you reboot a primary: the same node stays primary, and the primary endpoint keeps pointing to it.

To verify the experiment is working properly, you can monitor the node status and test connectivity:

```bash
# Find the primary cluster
aws elasticache describe-replication-groups --replication-group-id <YOUR REPLICATION GROUP ID> --query 'ReplicationGroups[0].NodeGroups[0].NodeGroupMembers[?CurrentRole==`primary`].CacheClusterId'

# Check the primary cluster and node status
aws elasticache describe-cache-clusters --cache-cluster-id <PRIMARY-CLUSTER-ID> --show-cache-node-info --query 'CacheClusters[0].[CacheClusterStatus,CacheNodes[0].CacheNodeStatus]'

# List the reboot events of the last 60 minutes
aws elasticache describe-events --source-type cache-cluster --source-identifier <PRIMARY-CLUSTER-ID> --duration 60

# Monitor Redis connectivity during reboot (add --tls if the group uses encryption in transit,
# and --user and --pass, or -a, if it uses AUTH)
watch -n 5 'redis-cli -h <redis-endpoint> ping'

# Monitor application health
curl -I https://<your-app>/health
```

During the experiment, the cluster status changes from `available` to `rebooting cache cluster nodes` as soon as the reboot is requested. The node status changes to `rebooting` only when the node actually restarts. Then the event `Cache node 0001 restarted` appears, and the cluster and node return to `available`.

> **Note**: Measured in test runs on two-node Redis OSS 7.1 replication groups (`cache.t4g.micro`) in `eu-west-2`, with a client opening a new connection to the primary endpoint and to the reader endpoint every second, with 1-second connect and read timeouts:
>
> * The node kept serving for 13 to 33 seconds after `RebootCacheCluster` was called, then restarted.
> * Writes on the primary endpoint failed for 6 to 7 seconds while it restarted. The same node stayed primary. Reads on the reader endpoint didn't fail.
> * After every restart the data was gone.
> * The experiment's wait saw the group `available` again 95 to 213 seconds after the call.
> * Stopping the experiment 3 seconds after the call did not prevent the restart or the data loss: the node restarted 21 seconds after the call, 18 seconds after the experiment had ended.

### What else is affected

* **Every client of each tagged group.** Writes to the primary endpoint fail while the primary restarts. The replicas clear their copy of the data too, so readers on the reader endpoint and the node endpoints find the cache empty.
* **Every tagged group in the Region, at the same time.** The experiment reboots the primary of every group with the tag, not one of them.
* **Your source of truth.** While the cache is empty, every read your application would have served from the cache goes to the system behind it.
* **Who can opt a group in.** Anyone who can add the `FIS-Ready=True` tag to a replication group adds it to the experiment. Before each run, check which resources carry the tag, for example with `aws resourcegroupstaggingapi get-resources --tag-filters Key=FIS-Ready,Values=True --query 'ResourceTagMappingList[].ResourceARN'`. Replication groups have `:replicationgroup:` in their ARN.
* **Read-only calls on every group.** Step 1 and the report steps call `ListTagsForResource` on every replication group in the Region, tagged or not. If one of those calls fails, the step fails.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped, until every rebooted node has restarted and its group is `available` again, until a step fails, or until the wait runs out (about 25 minutes at most, inside the template's `maxDuration` of 30 minutes).

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

What a stop does depends on when it comes:

* **Before the `RebootCacheCluster` call** (in rebootPrimaryNode): no more calls are made once the step reads a status other than `InProgress`. A call that is already being sent when the stop arrives, or that starts in the moment between the status check and the call, can't be stopped. AWS doesn't document how soon after a stop the step's status changes. Until it does, the loop goes on, so a slow change can let every tagged group not yet rebooted (up to 20) be rebooted after the stop. In the test runs SSM didn't end the step's script at the stop: the script went on to its next status read, 29 and 37 seconds after the stop, saw the stop there and made no more calls. How many groups a stop can still reach when the calls follow each other without a pause wasn't measured.
* **After the call** (in rebootPrimaryNode, waitForReboot or waitForRebootContinued): the stop ends the wait, not the reboot. A reboot that ElastiCache has accepted can't be cancelled: the node restarts on its own and its data is cleared, possibly after the experiment has ended. In the test runs the restart came 19 to 39 seconds after the call.
* **During reportAfterFailure**: the stop moves the run to `reportAfterStop`, which makes the same check, and the run ends Cancelled (not tested).

In the test runs, FIS showed the experiment stopped within a second of the stop. `reportAfterStop` then ran for about 31 seconds, and the SSM execution ended Cancelled 31 to 33 seconds after the stop.

A stopped experiment can't be resumed ([Stop an experiment](https://docs.aws.amazon.com/fis/latest/userguide/stop-experiment.html)). Starting it again reboots the primaries again and clears their data again.

Nothing needs to be restored by hand: there is no failover to reverse. The data can't be brought back. Repopulate the cache from your source of truth, or restore a backup into a new replication group ([Restoring from a backup into a new cache](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/backups-restoring.html)).

A stop condition can end the wait, but once the reboot call is accepted it can't stop the reboot or protect the data. An alarm on a metric of the rebooted node can have no data while the node restarts. Set its missing-data treatment to `breaching` if it should fire then. Test the alarm before you rely on it, for example by setting it to `ALARM` during a test run with `aws cloudwatch set-alarm-state --alarm-name <ALARM NAME> --state-value ALARM --state-reason "FIS stop condition test"` ([SetAlarmState](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_SetAlarmState.html)).

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to your Redis operations, such as connection counts and application response times.
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of the Redis primary node reboot.
4. Adding a stop condition tied to the alarm to automatically halt the experiment if critical thresholds are breached. In this experiment a stop ends the wait; it does not cancel a reboot that has been requested (see Stop Conditions).
5. Implementing appropriate connection retry logic in your application to handle brief node unavailability.
6. Testing your application's Redis connection pooling and recovery mechanisms.
7. Documenting the findings from your experiment and updating your incident response procedures accordingly.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
