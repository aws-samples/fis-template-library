# AWS Fault Injection Service Experiment: ElastiCache AZ Power Interruption

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

If power is interrupted to the ElastiCache nodes in a target Availability Zone while the primary node is in that AZ, writes on the primary endpoint should resume within 30 seconds of the node in that AZ no longer answering, once automatic failover has promoted a replica in a healthy AZ. Applications using the primary endpoint reconnect automatically after the role change. Replica replacements remain blocked in the impaired AZ for the experiment duration, so the cluster operates at reduced capacity. After the power interruption ends, nodes in the target AZ rejoin the replication group and the cluster returns to full capacity.

### What does this enable me to verify?

* ElastiCache Multi-AZ automatic failover works correctly under an AZ-level power failure
* Applications handle primary endpoint changes gracefully without manual intervention
* Connection pool retry and reconnect logic functions correctly during AZ-level disruption
* Cluster behavior under reduced replica capacity while an AZ remains impaired
* CloudWatch alarms detect `ReplicationLag` spikes and `IsMaster` role changes as expected

## Prerequisites

Before running this experiment, ensure that:

1. You have the roles created for FIS to use. An example IAM policy document and trust policy are provided.
2. You have created the FIS Experiment Template from the sample provided (elasticache-az-power-interruption-experiment-template.json).
3. The ElastiCache replication group(s) you want to target have the `FIS-Ready=True` tag.
4. Your replication group has Multi-AZ enabled with `AutomaticFailover=enabled`.
5. The replication group is **not** an ElastiCache Serverless resource — the `replicationgroup-interrupt-az-power` action does not support Serverless.
6. Update `<YOUR AVAILABILITY ZONE>` in the experiment template with the target AZ identifier (e.g., `us-east-1a`).
7. You have appropriate monitoring and observability in place to track the impact of the experiment.
8. The experiment was tested on a two-node Redis OSS 7.1 replication group (`cache.t4g.micro`, cluster mode disabled) in `us-east-1`. Other engines, node types, topologies and Regions weren't tested.

## How it works

This experiment uses the native FIS action `aws:elasticache:replicationgroup-interrupt-az-power` to simulate an AZ-level power failure for ElastiCache replication groups. Unlike a node reboot or manual failover, this action blocks all replica replacements in the impaired AZ for the duration of the experiment, giving a more realistic simulation of a sustained AZ outage.

The experiment follows this sequence:

1. **Target Resolution**: FIS resolves all replication groups tagged `FIS-Ready=True` in the specified AZ.
2. **Power Interruption**: FIS interrupts power to nodes in the target AZ. If the primary is in that AZ, automatic failover promotes the replica with the least replication lag.
3. **Reduced Capacity**: Replica replacements in the impaired AZ are blocked for the experiment duration (`PT10M` by default).
4. **Recovery**: After the experiment ends, the impaired AZ is restored and nodes rejoin the replication group. If a failover happened, the primary does not move back: in testing, the recovered node rejoined as a replica. To move the primary back to its original AZ in a cluster mode disabled group, follow [Promoting a read replica to primary](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/Replication.PromoteReplica.html): with Multi-AZ enabled, you turn Multi-AZ off, promote the original node, and turn Multi-AZ back on once the replication group is `available`.

> **Note**: Timings measured in two test runs on the replication group described in Prerequisites, with a client that wrote to the primary endpoint once a second over a new connection, with a fresh DNS lookup and a 1-second timeout each time:
>
> * Power loss is not immediate. The node in the target AZ stopped answering 42 and 74 seconds after the FIS action started, so keep `duration` well above that; shorter durations weren't tested.
> * Writes on the primary endpoint resumed 23 and 31 seconds after the node stopped answering, so one of the two runs missed the hypothesis's 30 seconds by 1 second. Measure the hypothesis from when the node stops answering, not from when the action starts.
> * `describe-replication-groups` showed every member `available` within 2 minutes of the experiment ending, but the node in the target AZ answered clients again only about 9 to 10 minutes after the experiment ended or was stopped. Check reachability from a client before you treat the cluster as back at full capacity.
> * While the recovering node still did not answer clients, the CloudWatch `IsMaster` metric for that node showed `1` for one minute, so an alarm on `IsMaster` could see two primaries in that minute. Check roles with `CurrentRole` in `describe-replication-groups`, and reachability with a client connection.

> **Note**: Resource targeting for this action supports `resourceTags` and `filters`. Targeting by `resourceArns` is not supported and is rejected at template creation time.

To verify the experiment is working, monitor the primary node role change:

```bash
# Watch for role changes every 5 seconds
watch -n 5 'aws elasticache describe-replication-groups \
  --replication-group-id <YOUR-REPLICATION-GROUP-ID> \
  --query "ReplicationGroups[0].NodeGroups[].NodeGroupMembers[].[CacheClusterId,CurrentRole,PreferredAvailabilityZone]" \
  --output table'
```

This shows roles, not reachability: as the note above says, members show `available` minutes before a recovering node answers clients.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until the configured `duration` parameter (`PT10M` by default) ends.

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

Stopping the experiment ends the power interruption, but it doesn't undo a failover or speed up recovery. In testing, after a stop 60 seconds into the action, the node in the target AZ took about 9 minutes to answer clients again, about as long as after a full run, and the primary stayed in the AZ the failover moved it to. A stopped experiment can't be resumed; start a new one. A stop condition works the same way: it can end the power interruption early, but not the recovery after it. To check a stop condition before you rely on it, set its alarm to `ALARM` with `aws cloudwatch set-alarm-state` while a run is in progress, and check that FIS stops the experiment ([SetAlarmState](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_SetAlarmState.html)).

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Updating `<YOUR AVAILABILITY ZONE>` to match the AZ where your primary node typically runs.
3. Identifying business metrics tied to your cache layer, such as cache hit rates, connection counts, and application response times.
4. Creating Amazon CloudWatch alarms on `ReplicationLag`, `IsMaster`, and `CurrConnections` metrics to monitor failover impact.
5. Adding a stop condition tied to a critical business alarm to automatically halt the experiment if needed. It ends the power interruption early, not the recovery after it.
6. Verifying your application uses the **primary endpoint** (not node-specific endpoints) so it can reconnect after a role change.
7. Testing your connection pool retry logic and reconnect timeout configuration.
8. Documenting the findings from your experiment and updating your runbooks accordingly.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
