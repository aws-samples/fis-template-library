# AWS Fault Injection Service Experiment: ElastiCache Redis Primary Node Failover

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

If the primary node of a tagged replication group is failed over with the ElastiCache `TestFailover` API, writes through the group's primary endpoint should fail for no longer than 60 seconds after the `TestFailover` call, and no write that the primary acknowledged should be lost. Replace 60 seconds and zero lost writes with the thresholds your application needs.

To check it, run a client that writes through the primary endpoint at a steady rate (for example one `INCR` per second), with a connect timeout and a read timeout, that opens a new connection after an error and logs the time and result of every write. The hypothesis is false if the longest run of failed writes after the `TestFailover` call is longer than your threshold, or if the counter's final value is lower than the number of writes the client saw acknowledged. Your client must use the primary endpoint, not a node endpoint, and must reconnect after an error so that it follows the endpoint to the new primary. ElastiCache replicates from the primary to the replicas asynchronously ([replication](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/Replication.Redis.Groups.html)), so a write the primary acknowledged just before the failover may not have reached the replica that becomes primary. Zero lost writes is therefore something this experiment tests, not something the failover guarantees; set the threshold your application can accept.

Reads that go to replicas are affected for longer: the former primary takes the replica role at the failover, and ElastiCache then recovers it, which the experiment waits for. In the test runs the former primary didn't answer clients for 393 to 490 seconds.

### What does this enable me to verify?

* Appropriate Redis connection monitoring and observability is in place (were you able to detect the failover?)
* Alarms are configured correctly for primary node changes (were the right people notified?)
* Your application handles Redis primary node changes gracefully
* Connection pooling and DNS resolution work correctly during failover
* Recovery controls and reconnection logic work as expected

## Prerequisites

Before running this experiment, ensure that:

1. You have created two IAM roles: one for FIS (trust policy `fis-iam-trust-relationship.json`, permissions `elasticache-redis-primary-node-failover-fis-role-iam-policy.json`) and one for SSM Automation (trust policy `ssm-iam-trust-relationship.json`, permissions `elasticache-redis-primary-node-failover-ssm-role-iam-policy.json`). Replace `<YOUR REGION>` and `<YOUR AWS ACCOUNT>` in all four files, and `<YOUR SSM AUTOMATION ROLE NAME>` in the FIS role policy.
2. You have created the SSM Automation document `ElastiCache-Redis-Primary-Node-Failover` from `elasticache-redis-primary-node-failover-automation.json`. The FIS template and the FIS role policy refer to the document by this name.
3. You have created the FIS experiment template from `elasticache-redis-primary-node-failover-experiment-template.json`, replacing `<YOUR REGION>`, `<YOUR AWS ACCOUNT>`, `<YOUR ROLE NAME>` (the FIS role) and `<YOUR SSM AUTOMATION ROLE NAME>` (the SSM Automation role).
4. The ElastiCache (Redis OSS) replication groups you want to target have the `FIS-Ready=True` tag. The experiment fails over every replication group in the Region that carries this tag, all in the same run, so the tag is the only thing that limits which groups it reaches. Anyone who can add tags to a replication group (`elasticache:AddTagsToResource`) can bring it into the experiment. Wait 5 minutes after you add the tag before you start. In the tests the tagging API listed a new tag up to 51 seconds after it was added, but in one run the SSM role's `TestFailover` call on that group was still denied 2.6 minutes after the tag was added; every other call 2.3 minutes or more after a tag was added was allowed, except where a test had changed the policy to deny it. A removed tag was still listed up to 69 seconds after it was removed, and the group was `modifying` for up to 44 seconds after an add and 69 seconds after a removal.
5. Each tagged replication group has cluster mode disabled, `MultiAZ=enabled`, `AutomaticFailover=enabled`, a primary and at least one replica, and is `available`, with every node `available` and no failover or node recovery in progress according to its events from the last 60 minutes. The experiment checks all of this for every tagged group, and fails before it fails over anything if any tagged group doesn't meet it, including a group with a node that is taking a backup (its cluster shows `snapshotting` while the group stays `available`) or a group being modified. A group from which a replica was removed in the last hour after a failover also refuses, with "cannot tell the former primary", until the hour has passed. Cluster mode enabled isn't supported: `describe-replication-groups` doesn't report which node is primary for those groups ([NodeGroupMember](https://docs.aws.amazon.com/AmazonElastiCache/latest/APIReference/API_NodeGroupMember.html)).
6. `TestFailover` can fail over at most 15 node groups (shards) in any rolling 24-hour period ([TestFailover API reference](https://docs.aws.amazon.com/AmazonElastiCache/latest/APIReference/API_TestFailover.html)). This counts every caller in the account, not only this experiment. Each tagged group uses one per run, so the experiment refuses to start, failing over nothing, if more than 15 groups carry the tag.
7. If you change `tagKey` or `tagValue` in the template's `documentParameters`, change the `aws:ResourceTag/FIS-Ready` condition in the SSM role policy to the same key and value. Otherwise `TestFailover` is denied on the groups the new tag selects.
8. The SSM role policy allows `elasticache:TestFailover` only on replication groups in your Region and account that have the tag. No FIS managed policy (`AWSFaultInjectionSimulator*Access`) grants `TestFailover`; [AmazonElastiCacheFullAccess](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AmazonElastiCacheFullAccess.html) grants `elasticache:*` on `*`, and this policy is narrower. Of the condition keys the [Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_elasticache.html) lists for `TestFailover`, the policy also uses `elasticache:ClusterModeEnabled` (false) and `elasticache:MultiAZEnabled` (true), with `BoolIfExists`. The reference describes both keys as request parameters, which `TestFailover` doesn't take, so ElastiCache may not set them for this call. With `BoolIfExists`, a key that is set must match and a key that isn't set doesn't deny the call ([IfExists condition operators](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_condition_operators.html#Conditions_IfExists)). The experiment checks cluster mode and Multi-AZ itself for every group before the first call (prerequisite 5), and that check is the only guard: in the test, a `TestFailover` call through this role on a tagged group with Multi-AZ off was allowed, so ElastiCache doesn't set `elasticache:MultiAZEnabled` for this call. An IAM policy simulation with the keys set to the wrong values does deny the call. The role's read calls (`Describe*` and `tag:GetResources`) are on `*`, and `ssm:GetAutomationExecution`, which triggerFailover uses to read its own run's status, is on automation executions in your Region and account.
9. You have appropriate monitoring and observability in place to track the impact of the experiment.
10. Tested on: Redis OSS 7.1, `cache.t4g.micro`, cluster mode disabled, one primary with one or two replicas, Multi-AZ with automatic failover, one and two tagged groups, in `us-east-2`. Other engines and versions, node types, more replicas and other Regions haven't been tested.

## How it works

This experiment fails over the primary node of each tagged replication group by calling the ElastiCache `TestFailover` API, which promotes a replica to primary. FIS starts the SSM Automation document, which runs these steps:

1. **triggerFailover**: Finds every replication group in the Region tagged `FIS-Ready=True` with the Resource Groups Tagging API (`tag:GetResources`), which returns the tagged resources in the Region ([GetResources](https://docs.aws.amazon.com/resourcegroupstagging/latest/APIReference/API_GetResources.html)). It doesn't use ElastiCache's `ListTagsForResource`, which returns an error for a group that isn't `available` ([ListTagsForResource](https://docs.aws.amazon.com/AmazonElastiCache/latest/APIReference/API_ListTagsForResource.html)). A tagged group that the tagging API lists and that isn't `available` therefore reaches the checks below and refuses the run. A group the tagging API lists that no longer exists is named in the output and left out. Any other read error fails the step. The step then checks each tagged group against prerequisite 5 and records its current primary. If any group fails a check, or no group is tagged, the step fails and nothing is failed over. Otherwise it calls `TestFailover` on each group in turn. Just before each call it checks that the group is still `available` with the same primary and, last, that this run and this step are still `InProgress` (`ssm:GetAutomationExecution`), because a stop doesn't end the step's script (see [Stop Conditions](#stop-conditions)). If a call fails, or its result is unknown, the step fails at once and names that group, the groups already failing over, which ElastiCache finishes on its own, and the groups it didn't reach. If the group has changed or the run's status can't be read, the step fails before that group's call: it says the group wasn't called, and names the groups already failing over and the groups not failed over, that group included. If the run was stopped, the step makes no further call, but Systems Manager shows it `Cancelled` and records no message from it, so verifyHealthy's output and the groups' events show which groups were failed over. The step starts no call more than 100 seconds after it starts: if that time passes during the checks, nothing is failed over, and if it passes before a group's call, the step fails before that call in the same way. Each `TestFailover` call is sent once: its client allows one attempt and no retry (`total_max_attempts` 1), so a retry can't start a second failover.
2. **waitForFailover**: Waits, for up to 5 minutes, until each group reports the event `Failover from primary node <former primary> to replica node <new primary> completed` naming the primary that step 1 recorded, the former primary has the `replica` role, the group has one primary, and the group is `available`. It fails at once if the group is being deleted, the former primary is no longer a member, a failover from another node completed, or the group's events show more than one `TestFailover` call or completed failover since the run started (another run or caller overlapped this one, and this run can't tell which failover is its own). Two copies of an event with the same message, and for a call the same time, count as one.
3. **waitForRecovery** and **waitForRecoveryContinued**: Wait until the former primary has finished recovering after the failover, and then until the group and every node are `available`. Only `Finished recovery for cache nodes` events for the former primary count: on its own cache cluster's events, or on the group's events if they name it. Recovery events for other nodes don't count. Both steps fail at once on the same overlap and deletion checks as step 2. An `aws:executeScript` step runs for at most 10 minutes ([aws:executeScript](https://docs.aws.amazon.com/systems-manager/latest/userguide/automation-action-executeScript.html)), so the wait is split over two steps of up to 8.5 minutes each. FIS keeps the action running until this wait ends, so the experiment covers the whole failover and recovery.
4. **verifyHealthy**: Runs only if a step fails or the experiment is stopped. For up to about 75 seconds, it checks whether every tagged group is `available` with one primary, every node is `available`, and its events from the last 60 minutes show no failover or node recovery still in progress, matching each recovery to its own node. It checks the time before every call, and reports what it found by then, naming any group it didn't reach. It reports in its output and changes nothing; if it couldn't read a group, it reports that too and the step fails. A failover that has started can't be undone: stopping the experiment cancels the waiting step, and ElastiCache finishes the failover and the recovery on its own. The cancelled step's script can go on polling until its own deadline: in the tests, cancelled steps' scripts kept calling AWS for 6 seconds to about 7.5 minutes after the cancel. These polls only read. If the experiment is stopped while verifyHealthy itself runs, Systems Manager cancels it and its report is lost; check the groups' events instead. In every step, the step's own message is in its `FailureDetails` in `get-automation-execution`: its 1,024-character `FailureMessage` often holds only the start of a Python traceback.

Each step checks its own deadline before every API call. `TestFailover` gets one attempt with a 30-second read timeout. Every other call is tried at most 3 times with a 3-second connect timeout and a 10-second read timeout, about 42 seconds at most with the SDK's backoff; in verifyHealthy, at most 2 times with a 5-second read timeout, about 17 seconds. Counted from the script's start, a call started just before a step's deadline ends at least 38 seconds before the step's timeout (verifyHealthy: 18 seconds). A step can take longer than its script: in the tests, every step that wasn't cancelled ended about 3.5, 12.8, 40.0, 67.5, 94.5 or 121.7 seconds after it started, or a further multiple of about 27 seconds later, whatever its script did, so a step can end up to about 27 seconds after its script. verifyHealthy, which runs to its 75-second deadline when a group isn't healthy, ended 94.4 to 94.7 seconds after it started. A slow call at that deadline could make it end at about 121.7 seconds instead, past its 110-second timeout, and its report would be lost.

Every step before verifyHealthy is marked critical (`isCritical: true`), so a failed step ends the automation as Failed even though verifyHealthy then succeeds ([isCritical](https://docs.aws.amazon.com/systems-manager/latest/userguide/automation-actions.html)).

After the run, the former primary is a replica and the new primary stays primary; the experiment doesn't swap them back. ElastiCache doesn't let you promote a replica to primary while Multi-AZ with automatic failover is enabled ([promoting a read replica](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/Replication.PromoteReplica.html)). To make the original node primary again after its recovery has finished, either:

* With one replica, run the experiment again once the recovery has finished. It fails over to the only replica, which is the original primary. This uses another of the account's 15 `TestFailover` node groups for the rolling 24 hours.
* Or turn off Multi-AZ and automatic failover, promote the original node, and turn both back on. The group runs without Multi-AZ and automatic failover until the last command finishes. The AWS guide says to turn off only Multi-AZ, but in the test the promotion was then refused: `InvalidReplicationGroupState: Cannot manually promote a new master cache cluster while autofailover is enabled`. In the tests the group was `available` again with both settings on 4.5 to 5.5 minutes after the first command, and a client saw one `READONLY` write failure at the promotion.

```bash
# 1. Turn off Multi-AZ and automatic failover
aws elasticache modify-replication-group --replication-group-id "<YOUR-CLUSTER-ID>" --no-multi-az-enabled --no-automatic-failover-enabled --apply-immediately

# 2. Repeat until it prints "available" and "disabled"
aws elasticache describe-replication-groups --replication-group-id "<YOUR-CLUSTER-ID>" --query 'ReplicationGroups[0].[Status,AutomaticFailover]' --output text

# 3. Promote the original node
aws elasticache modify-replication-group --replication-group-id "<YOUR-CLUSTER-ID>" --primary-cluster-id "<FORMER PRIMARY CLUSTER ID>" --apply-immediately

# 4. Repeat until it prints "available" and the former primary's cluster ID
aws elasticache describe-replication-groups --replication-group-id "<YOUR-CLUSTER-ID>" --query 'ReplicationGroups[0].[Status,NodeGroups[0].NodeGroupMembers[?CurrentRole==`primary`].CacheClusterId|[0]]' --output text

# 5. Turn automatic failover and Multi-AZ back on
aws elasticache modify-replication-group --replication-group-id "<YOUR-CLUSTER-ID>" --automatic-failover-enabled --multi-az-enabled --apply-immediately
```

The promotion writes a `Failover from master node ... completed` event, and in the test no recovery event for the former primary followed it in the next 7 minutes. `triggerFailover` refuses a group with a completed failover in the last 60 minutes and no later recovery of the former primary, so a run on the group in the hour after this procedure refuses; in the test it did, with "former primary ... recovery pending".

> **Note**: Measured in test runs on Redis OSS 7.1 groups (`cache.t4g.micro`, one primary with one or two replicas) in `us-east-2`. The write figures and how long the former primary didn't answer come from runs with a client that sent one `INCR` a second on a long-lived connection to the primary endpoint and read each node endpoint every second, with 1-second connect and read timeouts, reconnecting after each error:
>
> * The failover completed 15 to 24 seconds after the `TestFailover` call.
> * Writes through the primary endpoint failed for 26 to 31 seconds, starting 0.4 to 1.6 seconds after the `Test Failover API called` event. No acknowledged write was lost.
> * The former primary didn't answer for 393 to 490 seconds, and finished recovery 6.8 to 9.0 minutes after the call. The action lasted 8 min 27 s to 9 min 7 s.

To follow the experiment, watch which node is primary, and list the events:

```bash
# Check current primary before experiment
aws elasticache describe-replication-groups --replication-group-id <YOUR-CLUSTER-ID> --query 'ReplicationGroups[0].NodeGroups[0].NodeGroupMembers[?CurrentRole==`primary`].CacheClusterId'

# Watch the primary change during the experiment
watch -n 5 "aws elasticache describe-replication-groups --replication-group-id <YOUR-CLUSTER-ID> --query 'ReplicationGroups[0].NodeGroups[0].NodeGroupMembers[?CurrentRole==\`primary\`].CacheClusterId'"

# List the failover events
aws elasticache describe-events --source-type replication-group --source-identifier <YOUR-CLUSTER-ID> --duration 60

# List the former primary's own events
aws elasticache describe-events --source-type cache-cluster --source-identifier <FORMER PRIMARY CLUSTER ID> --duration 60
```

The [TestFailover API reference](https://docs.aws.amazon.com/AmazonElastiCache/latest/APIReference/API_TestFailover.html) lists the events in the order they occur: `Test Failover API called for node group <id>` and `Failover from primary node <old primary> to replica node <new primary> completed` as replication group messages, then `Recovering cache nodes <node id>` and `Finished recovery for cache nodes <node id>` as cache cluster messages. It doesn't say which cache cluster reports the recovery messages; the experiment reads them from the former primary's own events and from the group's events. The experiment also accepts `master node` in place of `primary node` in the failover message. In the test runs the failover message said `master node` and named cluster IDs, and the recovery messages appeared only on the former primary's own cluster events, naming its cluster ID.

### What else is affected

* Every client of a tagged group sees the failover, not only the application you're testing: writes through the primary endpoint fail until it points to the new primary.
* Reads from the former primary, through its node endpoint or the reader endpoint, are affected until it has recovered.
* Each run uses one of the account's 15 `TestFailover` node groups per rolling 24 hours for each tagged group, which other users of `TestFailover` in the account share.
* If a CloudFormation stack or CDK app sets the group's `PrimaryClusterId`, the swapped roles can show up as drift ([drift detection](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-cfn-stack-drift.html)).

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped, until a step fails, until every tagged group's former primary has recovered, or after 35 minutes (`maxDuration`).

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

A stop doesn't end `triggerFailover`'s script: in the tests, a cancelled step's script kept running and calling AWS after the cancel (see verifyHealthy above). So just before each `TestFailover` call the step reads its own run's status, and it calls only if the run and the step are both still `InProgress`. Once Systems Manager has recorded a stop, a stop during the readiness checks or between two groups' calls fails over no further group. A stop that Systems Manager hasn't recorded by that read, or one that lands between the read and the call, can still fail over that one group: in the tests, `GetAutomationExecution` first showed the run `Cancelling` 0.2 to 0.4 seconds after the `StopExperiment` request, and triggerFailover `Cancelled` up to 1.4 seconds after it. After any stop, check each group's events as above; verifyHealthy's output names each group's state when it ran, unless the stop came during verifyHealthy itself, which then records nothing. A stop after the call doesn't reverse the failover: FIS cancels the automation, verifyHealthy reports each group's state within SSM's two-minute cancel window ([onCancel](https://docs.aws.amazon.com/systems-manager/latest/userguide/automation-actions.html)), and ElastiCache finishes the failover and the former primary's recovery on its own. In the test runs FIS showed the experiment stopped at once, and verifyHealthy finished 95 to 96 seconds after the stop. Check that it finished with the events commands above, and see [How it works](#how-it-works) to make the original node primary again. A stopped experiment can't be resumed ([stop an experiment](https://docs.aws.amazon.com/fis/latest/userguide/stop-experiment.html)). A stop condition you add can therefore end the waiting, but not the failover or its impact.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case. If you change them, change the SSM role policy's tag condition too (prerequisite 7).
2. Identifying business metrics tied to your Redis operations, such as cache hit rates and application response times.
3. Creating Amazon CloudWatch metrics and alarms to monitor Redis failover impact.
4. Adding stop conditions tied to critical business metrics to automatically halt the experiment if needed. Test the alarm by setting it to `ALARM` with `aws cloudwatch set-alarm-state` during a run ([SetAlarmState](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_SetAlarmState.html)).
5. Implementing appropriate connection retry logic in your application to handle primary node changes.
6. Testing your application's Redis connection pooling and DNS resolution during failover scenarios.
7. Documenting the findings from your experiment and updating your incident response procedures accordingly.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
