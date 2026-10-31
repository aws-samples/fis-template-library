# AWS Fault Injection Service Experiment: DynamoDB Traffic Blackhole Region Impairment

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

The experiment blocks network traffic between the tagged subnets and DynamoDB for 10 minutes, and pauses replication of the tagged global table replicas for the same 10 minutes. With that fault:

- If DynamoDB traffic from the tagged subnets is blocked for 10 minutes, the number of DynamoDB calls from the tagged subnets that succeed during the fault should not exceed 0, and the error rate of DynamoDB calls from other subnets, and of calls from the tagged subnets to other AWS services, should not exceed its normal level.
- If replication of the tagged replicas is paused for 10 minutes, the time from the start until writes stop replicating to and from them should not exceed 5 minutes (the [FIS actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html#global-table-pause-replication) allows up to 5 minutes), and the number of successful writes missing after replication resumes should not exceed 0.
- If DynamoDB traffic from the tagged subnets is blocked, the time until your monitoring detects it should not exceed 3 minutes, and the time until it notifies the team should not exceed 5 minutes.
- If DynamoDB traffic from the tagged subnets is blocked and automated failover to another Region is configured, the time until the failover completes should not exceed 10 minutes, the length of the fault. To test a manual failover that takes longer, raise both actions' `duration` so the fault lasts until the failover should be complete.

To check it, run a client in a tagged subnet that calls DynamoDB at a steady rate with a connect timeout and a read timeout, the same client in an untagged subnet, and a writer that puts a marker item in each Region and reads the others' markers. The hypothesis is false if any call from a tagged subnet succeeds during the fault, if calls from the untagged subnet or to other services fail, if markers still cross between this Region and the others more than 5 minutes after the start, if a successful write is missing after replication resumes, or if your alarm, notification or failover misses its time.

### What does this enable me to verify?

* Network-level DynamoDB connectivity monitoring and alerting works correctly
* Application timeout and retry logic handles network failures appropriately  
* Circuit breaker patterns function as expected for DynamoDB connectivity issues
* Graceful degradation or failover mechanisms activate when DynamoDB is unreachable
* Error handling and user experience during complete DynamoDB network blackouts
* Recovery behavior when network connectivity is restored

## Prerequisites

Before running this experiment, ensure that:

1. You have created the IAM role for FIS from `fis-iam-trust-relationship.json` and `dynamodb-traffic-blackhole-region-impairment-iam-policy.json`, after replacing `<YOUR REGION>` and `<YOUR AWS ACCOUNT>` in both files. The policy covers multi-Region eventually consistent (MREC) global tables. For multi-Region strongly consistent (MRSC) global tables, also allow `dynamodb:InjectError`, which the [FIS actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html#global-table-pause-replication) lists for them.
   The policy lets FIS change a subnet's network ACL association only while the subnet carries `FIS-Ready=True`, so don't remove the tag from a subnet while an experiment runs: FIS uses the same permission to restore it (see [Stop Conditions](#stop-conditions)). The policy lets FIS put and delete the resource policy of any DynamoDB table and any stream in the Region, with no tag condition. FIS changes only the policies of the replicas it resolved as targets and of their streams, but nothing in the policy limits the role to them. A `FIS-Ready` condition on the table grant doesn't work: in testing, with that condition, DynamoDB refused FIS's `PutResourcePolicy` on a tagged replica with `AccessDenied` and "The new resource policy will not allow you to update the resource policy in the future.", and the experiment failed (experiments `EXP25QSsUXmWKiyBpb4` and `EXPSfYSbWRNUUbMLup`). The same grant with no condition worked (`EXPmUddHuw3e6ts6qG`). The message is DynamoDB's check that a new resource policy doesn't lock the caller out; that this check ignores the table's tags is inferred from those runs, not documented. A tag condition on the stream grant wasn't tested.
2. You have created the FIS experiment template from `dynamodb-traffic-blackhole-region-impairment-template.json`, after replacing `<YOUR AWS ACCOUNT>` and `<YOUR ROLE NAME>` in `roleArn`.
3. The EC2 subnets containing your application instances have the `FIS-Ready=True` tag, and your application reaches DynamoDB from them through the Regional endpoint, for example through a DynamoDB gateway endpoint. The deny rules cover only the CIDRs in the Region's DynamoDB prefix list. A DynamoDB interface (PrivateLink) endpoint has private IP addresses in your VPC, outside that list, so this experiment isn't expected to block traffic to it (not tested). Use subnets dedicated to the experiment: every resource with a network interface in a tagged subnet loses DynamoDB access (see [What else is affected](#what-else-is-affected)).
4. The DynamoDB global tables your application uses have the `FIS-Ready=True` tag on their replica in the Region where you run the experiment. The template pauses replication of every global table with this tag in that Region.
5. Both targets match something. The template sets `emptyTargetResolutionMode` to `fail`, so if no subnet or no global table replica in the Region carries the tag, the experiment is terminated at once with the status `failed` ([experiment options](https://docs.aws.amazon.com/fis/latest/userguide/experiment-options.html)). To run only the network part, remove the `pauseReplication` action and the `dynamodbTables` target. To see which subnets and tables a run would pick, start it once with `aws fis start-experiment --experiment-template-id <TEMPLATE ID> --experiment-options actionsMode=skip-all`; this preview doesn't check permissions ([target preview](https://docs.aws.amazon.com/fis/latest/userguide/generate-target-preview.html)).
6. The network ACL of each tagged subnet has room for the deny rules FIS adds: one in each direction for each CIDR in the Region's DynamoDB prefix list. The [FIS actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html#disrupt-connectivity) says: "When the scope is not `all`, the maximum number of entries in network ACLs is 20." In testing, the number of CIDRs in the `com.amazonaws.us-west-1.dynamodb` prefix list, and the number of entries in the network ACL FIS created from the VPC's default network ACL: Awaiting test. What FIS does when the clone would go over the limit wasn't tested. To count the CIDRs in your Region:

   ```bash
   PL=$(aws ec2 describe-managed-prefix-lists --region <YOUR REGION> \
     --filters Name=prefix-list-name,Values=com.amazonaws.<YOUR REGION>.dynamodb \
     --query 'PrefixLists[0].PrefixListId' --output text)
   aws ec2 get-managed-prefix-list-entries --region <YOUR REGION> --prefix-list-id "$PL" --query 'Entries[].Cidr'
   ```

7. Before each run, you record the network ACL each tagged subnet uses, so that you can put it back by hand if FIS can't restore it (see [Stop Conditions](#stop-conditions)). Nothing FIS leaves behind names the original network ACL:

   ```bash
   aws ec2 describe-network-acls --region <YOUR REGION> \
     --filters Name=association.subnet-id,Values=<SUBNET ID> \
     --query 'NetworkAcls[].NetworkAclId' --output text
   ```

8. No other run of this experiment, or of another experiment that targets the same subnets or tables, is in progress. What FIS does when two runs change the same subnet's network ACL association or the same table's resource policy wasn't tested. A second run would clone the network ACL the first run put on the subnet, so the first run's restore could end the second run's fault early and leave the second run's restore pointing at a network ACL that's gone. On a table that had no resource policy, the [FIS actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html#global-table-pause-replication) says the policy FIS creates is deleted when the experiment ends, which could remove the second run's statements with it. A run that has ended can also still write a table's resource policy: in testing, FIS kept retrying a failed `PutResourcePolicy` on a target table about once a minute until 6 minutes after the experiment ended `failed` (`EXP25QSsUXmWKiyBpb4`), and a retry from a run that had ended 2.5 minutes earlier rewrote the resource policy of a table the next run was using, leaving it unchanged that time (`EXPSfYSbWRNUUbMLup`). A rewrite a minute after the end happened again after `EXPMjGphgaVMeMnqSr`. Before you start the next run on the same tables, check CloudTrail for `PutResourcePolicy` calls whose role session name is the ended experiment's ID.
9. Your application instances are running in the tagged subnets and actively using DynamoDB.
10. You have appropriate monitoring and observability in place to track the impact.
11. Tested configuration (Awaiting test): us-west-1, with two tagged subnets on the VPC's default network ACL, a DynamoDB gateway endpoint, and multi-Region eventually consistent global tables replicated to ca-central-1. Interface (PrivateLink) endpoints for DynamoDB, IPv6, network ACLs with more rules than the default one, and strongly consistent global tables weren't tested.

## How it works

The template runs two actions at the same time, each for 10 minutes by default:

- `blockDynamoDBTraffic` uses the `aws:network:disrupt-connectivity` action with `scope: dynamodb` to block all network traffic between your application subnets and the DynamoDB regional endpoints.
- `pauseReplication` uses the `aws:dynamodb:global-table-pause-replication` action to pause replication of the tagged global tables. For MREC tables, FIS adds deny statements for the DynamoDB replication service to the resource policy of the tagged replica and of its stream, creating a policy where none exists. Each statement's ID includes the experiment ID, and each carries a `DateLessThan` condition on `aws:CurrentTime`, so it stops applying at that time even if FIS never removes it. Which time FIS sets there: Awaiting test. Tables may continue to be replicated for up to 5 minutes after the action begins ([FIS actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html#global-table-pause-replication)).

While `pauseReplication` runs, FIS also calls `dynamodb:DescribeTable` on each target table's replicas in the other Regions. The policy allows `DescribeTable` only in `<YOUR REGION>`, so CloudTrail in those Regions records these calls as `AccessDenied` for the experiment's role session. They are expected and harmless: in testing they came in every run that resolved tables, 4 to 64 per run, and target resolution, the pause and the restore went on regardless (for example `EXPmUddHuw3e6ts6qG`). If you alarm on `AccessDenied`, leave out this role.

### Network ACL Mechanism

FIS temporarily:
1. Clones the existing network ACL associated with target subnets
2. Adds deny rules to block DynamoDB traffic in the cloned ACL
3. Associates the modified ACL with your subnets for the experiment duration
4. Restores the original network ACL association and deletes the clone when the action ends or the experiment is stopped

### Duration and Scope

- **Duration**: 10 minutes for both actions (configurable via each action's `duration` parameter)
- **Scope**: DynamoDB regional endpoints only - other AWS services remain accessible
- **Traffic Blocked**: All traffic between the target subnets and the CIDRs in the Region's DynamoDB prefix list, in both directions
- **Intra-subnet**: Traffic between instances in the same subnet remains unaffected
- **Replication**: Paused for every global table tagged `FIS-Ready=True` in the Region where the experiment runs

**Measured behavior** (Awaiting test), with a client in the tagged subnets that calls DynamoDB once a second with a connect timeout, a read timeout and no retries:
- How many network ACLs FIS created for the tagged subnets, their tags, and the deny rules it added: Awaiting test.
- How soon DynamoDB calls from the tagged subnets failed after the association, and how soon they succeeded again after FIS restored the original association, at the end and on a stop: Awaiting test.
- Whether an S3 call through an S3 gateway endpoint in the same subnets, and DynamoDB calls from an untagged subnet on the same network ACL, kept working during the fault: Awaiting test.
- How soon replication stopped in each direction, how soon it resumed after the pause ended or the experiment was stopped, and whether any successful write was lost: Awaiting test.

### What else is affected

- The experiment targets every subnet in the Region tagged `FIS-Ready: True`, and every resource with a network interface in those subnets loses DynamoDB connectivity, whether or not it belongs to your application. Other experiments in this library use the same tag on subnets, so a subnet you tagged for one of them is a target here too.
- It also targets every DynamoDB global table replica tagged `FIS-Ready: True` in the Region where it runs, and pauses its replication, whatever subnet its readers and writers run in. Within 5 minutes of the start, readers of the replicas in other Regions stop seeing writes made in this Region, and readers of this Region's replica stop seeing writes made elsewhere. The deny statements are on this Region's replica and its stream only, so replication between two other Regions of the same table isn't expected to pause (not tested: the test used two Regions).
- The deny statements apply only to the DynamoDB replication service. For MRSC tables, FIS also denies Application Auto Scaling `DescribeTable` and `UpdateTable` on the table, so auto scaling doesn't change the table's capacity during the fault ([FIS actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html#global-table-pause-replication)).
- FIS makes its changes outside CloudFormation, so a stack that manages the subnet's network ACL association or the table's resource policy shows drift during a run, and a stack update to either during a run can overwrite the fault or FIS's restore ([drift detection](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-cfn-stack-drift.html)). Any other writer of the table's or stream's resource policy can do the same. If the table or stream had no resource policy before the run, FIS creates one for the experiment and deletes the whole policy when the experiment ends, including any statement someone else added to it during the run ([FIS actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html#global-table-pause-replication)).

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until both actions complete (10 minutes by default).

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

When the actions end, or when you stop the experiment, FIS restores each subnet's original network ACL association, deletes the network ACL it created, and removes its statements from the table and stream policies. How soon DynamoDB calls from the tagged subnets succeed again after the restore, and how soon replication resumes in both directions: Awaiting test. A stop before the actions start changes nothing. If one action fails, FIS stops the other and the experiment ends `failed`. In testing, when `pauseReplication` failed, FIS stopped `blockDynamoDBTraffic` and restored the network ACL association 2 to 3 seconds later (`EXP25QSsUXmWKiyBpb4`, `EXPSfYSbWRNUUbMLup`). When `blockDynamoDBTraffic` failed before it associated its network ACL, FIS removed the pause's statements and deleted its network ACL, but DynamoDB throttled the removal calls, and both were still in place until 38 seconds after the experiment ended `failed` (`EXP4JfP6ApVX2RbGXk`). So check the subnets' network ACL associations and the table and stream policies a minute or more after a run ends, before you treat it as cleaned up. A stop condition stops the experiment the same way. A stopped experiment can't be resumed; start a new one. To check a stop condition before you rely on it, set its alarm to `ALARM` with `aws cloudwatch set-alarm-state` while a run is in progress, and check that FIS stops the experiment ([SetAlarmState](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_SetAlarmState.html)).

If FIS can't restore a subnet, for example because its `FIS-Ready` tag was removed during the run, restore it by hand. In testing, with the tag removed from one of two subnets during the fault, FIS restored the other subnet, was denied `ReplaceNetworkAclAssociation` on this one, couldn't delete its network ACL, and ended the experiment `failed` with "Unable to stop 'aws:network:disrupt-connectivity' action. Unable to delete one or more Network ACLs. FIS-managed Network ACLs changed while the action was running." The message doesn't name the subnet. The subnet stayed on FIS's network ACL, still blocking DynamoDB, until the commands below restored it (`EXPmfFHGeyzQQA4ngr`). The first command shows the network ACL the subnet is on now, its association ID and its tags; FIS's network ACL carries a `managedByFIS` tag. Re-associate the network ACL you recorded for the subnet before the run (Prerequisite 7), then delete the FIS network ACL:

```bash
aws ec2 describe-network-acls --region <YOUR REGION> \
  --filters Name=association.subnet-id,Values=<SUBNET ID> \
  --query "NetworkAcls[].{NetworkAclId:NetworkAclId,AssociationId:Associations[?SubnetId=='<SUBNET ID>']|[0].NetworkAclAssociationId,Tags:Tags}"
aws ec2 replace-network-acl-association --region <YOUR REGION> \
  --association-id <ASSOCIATION ID> --network-acl-id <ORIGINAL NETWORK ACL ID>
aws ec2 delete-network-acl --region <YOUR REGION> --network-acl-id <FIS NETWORK ACL ID>
```

Delete the FIS network ACL only once no subnet is associated with it. The deny statements in the table and stream policies stop applying at the time in their `aws:CurrentTime` condition. To remove one earlier, read the policy and its revision ID with `aws dynamodb get-resource-policy --resource-arn <TABLE OR STREAM ARN>`, remove only the statements whose `Sid` starts with `DoNotModifyFisDynamoDbPauseReplication` followed by your experiment ID, and write the rest back with `aws dynamodb put-resource-policy --resource-arn <TABLE OR STREAM ARN> --policy file://<FILE> --expected-revision-id <REVISION ID>`, so the write fails instead of overwriting a change made since you read it. Use `aws dynamodb delete-resource-policy --resource-arn <TABLE OR STREAM ARN> --expected-revision-id <REVISION ID>` only if FIS's statements are the only ones left. Removing FIS's statements while the experiment is still running ends the whole experiment, network fault included: in testing, FIS failed the experiment with "Unable to continue pausing replication of target DynamoDB tables. Fault statement in one of the resource policy was modified outside of the experiment.", then removed its statements from the other table and the streams and restored the network ACL association within 5 seconds (`EXPMjGphgaVMeMnqSr`). To end the fault early on purpose, stop the experiment instead.

Monitor these metrics during the experiment:
- DynamoDB API call success/failure rates
- Application error logs and exception counts
- Network connectivity metrics from application instances
- Circuit breaker state changes
- User experience and transaction success rates

## Safety Considerations

- Test in non-production environments first
- Limit who can add or remove the `FIS-Ready` tag on subnets and DynamoDB tables, for example with an `aws:TagKeys` condition on `ec2:CreateTags`, `ec2:DeleteTags`, `dynamodb:TagResource` and `dynamodb:UntagResource`: anyone who can add it can bring a resource into this experiment's scope, and anyone who can remove it from a subnet during a run stops FIS restoring that subnet's network ACL association
- Ensure your application can handle DynamoDB connectivity failures gracefully
- Have rollback procedures ready if manual intervention is needed
- Consider the impact on dependent services and downstream systems
- Verify that critical business processes have appropriate fallback mechanisms

## Files Included

- `dynamodb-traffic-blackhole-region-impairment-template.json` - FIS experiment template
- `dynamodb-traffic-blackhole-region-impairment-iam-policy.json` - Required IAM permissions
- `fis-iam-trust-relationship.json` - IAM trust relationship for FIS role
- `AWSFIS.json` - Template version marker

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to the DynamoDB operations your application makes from the tagged subnets.
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of losing network access to DynamoDB.
4. Adding a stop condition tied to the alarm to automatically halt the experiment if critical thresholds are breached.
5. Testing your application's failover to a replica in another Region while replication is paused.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
