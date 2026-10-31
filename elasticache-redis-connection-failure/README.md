# AWS Fault Injection Service Experiment: ElastiCache Redis Connection Failure

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

If the port 6379 ingress rules are removed from the target nodes' security groups for 5 minutes (the default `duration`):

* your application's error rate should not exceed `<YOUR THRESHOLD>` from 30 seconds after its first failed Redis call until the rules are back, because its circuit breakers serve degraded responses instead of errors;
* within 60 seconds of the rules coming back, your application's Redis calls should succeed at their usual rate; and
* in the minute after the rules come back, the [`NewConnections`](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/CacheMetrics.Redis.html) metric, summed across the nodes (it is reported per node), should not exceed the number of connections your clients normally open, such as the number of clients times their pool size. A higher sum means the clients reconnected in a retry storm. Retries during the fault don't show in this metric, because the security group drops them before they reach the nodes.

### What does this enable me to verify?

* Appropriate Redis connectivity monitoring and observability is in place (were you able to detect the connection failure?)
* Alarms are configured correctly for connectivity issues (were the right people notified?)
* Your applications handle Redis unavailability gracefully without cascading failures
* Redis client circuit breaker functionality works correctly
* Client-side retry logic doesn't create amplification effects or retry storms
* Recovery controls work as expected when Redis connectivity is restored

## Prerequisites

Before running this experiment, ensure that:

1. You have the roles created for FIS and SSM Automation to use. Example IAM policy documents and trust policies are provided.
2. You have created the SSM Automation Document from the sample provided (redis-connection-failure-automation.yaml)
3. You have created the FIS Experiment Template from the sample provided (redis-connection-failure-experiment-template.json)
4. The ElastiCache Redis cluster(s) you want to target have the "FIS-Ready":"True" tag and value
5. The target clusters use security groups of their own. The experiment removes port 6379 rules from the security groups of every tagged node, which cuts off every other resource that relies on those rules (see [What else is affected](#what-else-is-affected)).
6. The target nodes run the Redis engine. Nodes that run Valkey are not targeted.
7. You run the experiment in the standard AWS partition. The automation builds each node's ARN with `arn:aws`, so in AWS GovCloud (US) and China Regions it finds no node and changes nothing.
8. Your applications implement proper Redis client circuit breakers and retry logic
9. You have appropriate monitoring and observability in place to track the impact of the experiment.
10. The experiment was tested on a two-node Redis OSS 7.1 replication group (`cache.t4g.micro`, cluster mode disabled) in `us-east-1`, with one security group that held one port 6379 rule whose source was a security group. Cluster mode enabled, ports other than 6379, rules with an IP address range as their source, and nodes with more than one security group weren't tested.
11. Before every run, save the rules of each target node's security groups, for example `aws ec2 describe-security-groups --group-ids <SECURITY GROUP ID> > <SECURITY GROUP ID>-before.json`. If a stop or a failed restore leaves rules removed, this copy and the automation's output are the only records of them (see [Stop Conditions](#stop-conditions)).
12. The README's commands need the AWS CLI and `redis-cli`.

## How it works

This experiment simulates Redis connection failures by removing rules from the nodes' VPC security groups to block connections for a specified duration. The experiment follows this sequence:

1. **Dynamic Discovery**: Scans every ElastiCache cache cluster (node) that runs the Redis engine and selects those tagged with "FIS-Ready":"True". It reads each node's own tags; tags you add to a replication group are also added to all of its nodes ([Tagging your ElastiCache resources](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/Tagging-Resources.html)). It hands the next step its list of tagged nodes as a step output, which SSM cuts to 100 items ([aws:executeScript](https://docs.aws.amazon.com/systems-manager/latest/userguide/automation-action-executeScript.html)), so the automation acts on at most 100 tagged nodes and skips the rest without an error.
2. **Connection Disruption**: For each tagged node it received, removes from each of its security groups the ingress rules whose `FromPort` and `ToPort` are both 6379, whatever their protocol, and records them in the step's output for the restore. Only those exact rules are removed: a rule for a port range that includes 6379, an all-traffic rule, or another security group that allows port 6379 keeps the node reachable, and a node that listens on another port isn't affected. If no tagged node is found, no rule matches, or a tag read or a security group call fails, the automation still ends `Success`, with no fault on the nodes it couldn't change. A failed call to list the cache clusters fails the run before anything changes. During a run, check with the `describe-security-groups` command below, for each of the node's security groups, that no rule still admits port 6379.
3. **Sustained Failure**: Maintains connection disruption for specified duration to test resilience
4. **Restoration**: Adds the recorded rules back. A failed restore is listed in the automation's output, but the run still ends `Success`, so after every run check with the `describe-security-groups` command below that the rules are back, and add any that are missing.

The connection failure is implemented using an SSM Automation Document invoked by FIS. The SSM Automation Document modifies security group rules to block access to Redis, then restores connectivity after the specified duration.

To verify the experiment is working properly, you can monitor Redis connectivity and application behavior:

```bash
# Monitor Redis connectivity (add --tls if in-transit encryption is on)
watch -n 5 'redis-cli -h <redis-endpoint> ping'

# Check application health endpoints
curl -I https://<your-app>/health

# Monitor security group rules (run it for each of the node's security groups)
aws ec2 describe-security-groups --group-ids <security-group-id> --query 'SecurityGroups[0].IpPermissions'
```

During the experiment, you should observe connection timeouts when attempting to reach Redis and applications activating circuit breakers or degraded mode operations.

**Note:** Removing a security group rule does not immediately interrupt tracked connections that are already open; the security group keeps allowing their packets until those connections time out ([Amazon EC2 security group connection tracking](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/security-group-connection-tracking.html)). Clients that hold long-lived pooled connections to Redis may therefore keep working during the fault while only new connections fail. In one test run, with a port 6379 rule whose source was a security group, a connection that an AWS Lambda client had opened before the rule was removed kept working for the 40 seconds it was watched. Connections are untracked, and drop at once when the rule is removed, if the port 6379 rule allows all addresses (`0.0.0.0/0` or `::/0`) and the security group also has an outbound rule that allows all addresses on all ports, unless they come through a path that AWS always tracks, such as a NAT gateway, a Network Load Balancer or an AWS Lambda function's network interface. To test pooled clients, restart them or close their pools at the start of the fault. Before you judge the hypothesis, confirm from your application's metrics that its Redis calls failed during the fault.

### What else is affected

* Every resource that uses the tagged nodes' security groups loses the port 6379 rules for the length of the fault, whether or not it carries the tag: other cache clusters, and anything else that relies on those rules. Give the target clusters security groups of their own.
* Open connections that the security group doesn't track drop at once (see the note above).
* If CloudFormation or CDK manages the security groups, the rules change outside the stack. Drift detection shows the security groups as changed during the run, and the rules the restore adds back get new security group rule IDs. Don't update the stack during a run: if the update adds a removed rule back, the restore's call to add the rules fails as a duplicate, the other rules in that call stay removed, and the run still ends `Success`.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until the automation restores the security group rules at the end of the configured duration (5 minutes by default).

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

What a stop does depends on which step of the automation is running. A stop condition works the same way as a stop.

* **While it finds the nodes** (`getTargetClusters`): the automation ends with nothing changed, so there is nothing to undo.
* **While it removes the rules** (`disableRedisConnections`): not tested. The cancel handler adds back the rules listed in this step's output, so if SSM ends the step before it records its output, rules it already removed may stay removed.
* **During the fault** (`waitForDuration`): the cancel handler adds the removed rules back. SSM gives a cancel path at most two minutes to run ([properties shared by all actions](https://docs.aws.amazon.com/systems-manager/latest/userguide/automation-actions.html)). In one test run, a stop 23 seconds into the fault restored the rule 3 seconds after FIS cancelled the automation, and FIS reported the experiment `stopped` before the rule was back.
* **While it adds the rules back** (`restoreRedisConnections`): not tested. This step has no cancel handler, so a stop may leave rules removed. So may the action reaching the template's `maxDuration` of 30 minutes, which can happen with a `duration` close to it, or if the script steps run slowly: they have no timeout of their own and can each run for up to 600 seconds, so on the normal path the restore can also take that long.
* **After the restore**: nothing changes.

A failed restore doesn't fail the run, so after every stop compare the security groups with the copy you saved before the run. To add missing rules back by hand, find the automation run, read the rules its `disableRedisConnections` step removed, and add them back for each security group:

```bash
# FIS starts the automation by document ARN, so filter by start time, not document name
aws ssm describe-automation-executions \
  --filters Key=StartTimeAfter,Values=<TIME JUST BEFORE THE RUN, e.g. 2026-10-19T00:30:00Z> \
  --query "AutomationExecutionMetadataList[].[AutomationExecutionId,DocumentName,AutomationExecutionStatus]" \
  --output table

# The removed_rules of each security group are in this step's output
aws ssm get-automation-execution --automation-execution-id <EXECUTION ID> \
  --query "AutomationExecution.StepExecutions[?StepName=='disableRedisConnections'].Outputs.OutputPayload" \
  --output text

# Add one security group's removed rules back (or the missing rules from your saved copy)
aws ec2 authorize-security-group-ingress --group-id <SECURITY GROUP ID> \
  --ip-permissions '<REMOVED RULES JSON>'
```

A stopped experiment can't be resumed; start a new one. To check a stop condition before you rely on it, set its alarm to `ALARM` with `aws cloudwatch set-alarm-state` while a run is in progress, and check that FIS stops the experiment ([SetAlarmState](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_SetAlarmState.html)).

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to your Redis connectivity, such as cache hit rates and application error rates.
3. Creating Amazon CloudWatch metrics and alarms to monitor Redis connectivity and circuit breaker activation.
4. Adding stop conditions tied to critical business metrics to automatically halt the experiment if needed.
5. Implementing appropriate circuit breakers in your application to handle Redis unavailability gracefully.
6. Testing your application's behavior under various connection failure scenarios and durations. Keep `duration` well below the template's `maxDuration` of 30 minutes, which also has to cover finding the nodes, removing the rules and adding them back.
7. Documenting the findings from your experiment and updating your incident response procedures accordingly.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
