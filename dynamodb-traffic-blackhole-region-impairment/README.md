# AWS Fault Injection Service Experiment: DynamoDB Traffic Blackhole Region Impairment

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

If network traffic between the tagged subnets and DynamoDB is blocked for 10 minutes, and FIS pauses replication of the tagged global table replicas for the same 10 minutes, then:

- DynamoDB calls from the tagged subnets should fail with network timeouts for the whole fault, while DynamoDB calls from other subnets and calls from the tagged subnets to other AWS services keep working.
- Writes should stop replicating to and from the tagged replicas within 5 minutes of the start (the [FIS actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html#global-table-pause-replication) allows up to 5 minutes), replicate again after the fault ends, and no successful write should be lost.
- Monitoring should detect the failure within 2-3 minutes and notify the team within 5 minutes.
- If automated failover to another Region is configured, it should complete before the 10-minute fault ends. To test a manual failover that takes longer, raise both actions' `duration` so the fault lasts until the failover should be complete.

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
   The policy lets FIS change a subnet's network ACL association, and a table's resource policy, only while the subnet or table carries `FIS-Ready=True`, so don't remove the tag from a target while an experiment runs: FIS uses the same permissions to restore it. The table condition needs attribute-based access control (ABAC) for DynamoDB tables, which is on by default in most accounts; where it's off, DynamoDB treats tables as untagged and `pauseReplication` is denied ([Enabling ABAC in DynamoDB](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/abac-enable-ddb.html)). Stream resource policies can't take the condition, because a stream doesn't inherit its table's tags ([ABAC with DynamoDB Streams](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/abac-streams.html)), so the policy lets FIS change the resource policy of any stream in the Region.
2. You have created the FIS experiment template from `dynamodb-traffic-blackhole-region-impairment-template.json`, after replacing `<YOUR AWS ACCOUNT>` and `<YOUR ROLE NAME>` in `roleArn`.
3. The EC2 subnets containing your application instances have the `FIS-Ready=True` tag, and your application reaches DynamoDB from them through the Regional endpoint, for example through a DynamoDB gateway endpoint. The deny rules cover only the CIDRs in the Region's DynamoDB prefix list. A DynamoDB interface (PrivateLink) endpoint has private IP addresses in your VPC, outside that list, so this experiment isn't expected to block traffic to it (not tested). Use subnets dedicated to the experiment: every resource with a network interface in a tagged subnet loses DynamoDB access (see [What else is affected](#what-else-is-affected)).
4. The DynamoDB global tables your application uses have the `FIS-Ready=True` tag on their replica in the Region where you run the experiment. The template pauses replication of every global table with this tag in that Region.
5. Both targets match something. The template sets `emptyTargetResolutionMode` to `fail`, so if no subnet or no global table replica in the Region carries the tag, the experiment is terminated at once with the status `failed` ([experiment options](https://docs.aws.amazon.com/fis/latest/userguide/experiment-options.html)). To run only the network part, remove the `pauseReplication` action and the `dynamodbTables` target. To see which subnets and tables a run would pick, start it once with `aws fis start-experiment --experiment-template-id <TEMPLATE ID> --experiment-options actionsMode=skip-all`; this preview doesn't check permissions ([target preview](https://docs.aws.amazon.com/fis/latest/userguide/generate-target-preview.html)).
6. The network ACL of each tagged subnet has room for the deny rules FIS adds: one in each direction for each CIDR in the Region's DynamoDB prefix list. The [FIS actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html#disrupt-connectivity) says: "When the scope is not `all`, the maximum number of entries in network ACLs is 20." In testing, the `com.amazonaws.us-east-1.dynamodb` prefix list had Awaiting test CIDRs, and the network ACL FIS created from the VPC's default network ACL had Awaiting test entries. What FIS does when the clone would go over the limit wasn't tested. To count the CIDRs in your Region:

   ```bash
   PL=$(aws ec2 describe-managed-prefix-lists --region <YOUR REGION> \
     --filters Name=prefix-list-name,Values=com.amazonaws.<YOUR REGION>.dynamodb \
     --query 'PrefixLists[0].PrefixListId' --output text)
   aws ec2 get-managed-prefix-list-entries --region <YOUR REGION> --prefix-list-id "$PL" --query 'Entries[].Cidr'
   ```

7. Your application instances are running in the tagged subnets and actively using DynamoDB.
8. You have appropriate monitoring and observability in place to track the impact.
9. Tested configuration (Awaiting test): us-east-1, with two tagged subnets on the VPC's default network ACL, a DynamoDB gateway endpoint, and multi-Region eventually consistent global tables replicated to us-west-2. Interface (PrivateLink) endpoints for DynamoDB, IPv6, network ACLs with more rules than the default one, and strongly consistent global tables weren't tested.

## How it works

The template runs two actions at the same time, each for 10 minutes by default:

- `blockDynamoDBTraffic` uses the `aws:network:disrupt-connectivity` action with `scope: dynamodb` to block all network traffic between your application subnets and the DynamoDB regional endpoints.
- `pauseReplication` uses the `aws:dynamodb:global-table-pause-replication` action to pause replication of the tagged global tables. For MREC tables, FIS adds deny statements for the DynamoDB replication service to the resource policy of the tagged replica and of its stream, creating a policy where none exists. Each statement's ID includes the experiment ID, and each carries a `DateLessThan` condition on `aws:CurrentTime`, so it stops applying at that time even if FIS never removes it. Which time FIS sets there: Awaiting test. Tables may continue to be replicated for up to 5 minutes after the action begins ([FIS actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html#global-table-pause-replication)).

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
- FIS makes its changes outside CloudFormation, so a stack that manages the subnet's network ACL association or the table's resource policy shows drift during a run, and a stack update to either during a run can overwrite the fault or FIS's restore ([drift detection](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-cfn-stack-drift.html)). Any other writer of the table's or stream's resource policy can do the same.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until both actions complete (10 minutes by default).

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

When the actions end, or when you stop the experiment, FIS restores each subnet's original network ACL association, deletes the network ACL it created, and removes its statements from the table and stream policies. How soon DynamoDB calls from the tagged subnets succeed again after the restore, and how soon replication resumes in both directions: Awaiting test. A stop before the actions start changes nothing. If one action fails, the experiment's final status, and whether FIS stops and restores the other action at once or lets it run to its end: Awaiting test. A stop condition stops the experiment the same way. A stopped experiment can't be resumed; start a new one. To check a stop condition before you rely on it, set its alarm to `ALARM` with `aws cloudwatch set-alarm-state` while a run is in progress, and check that FIS stops the experiment ([SetAlarmState](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_SetAlarmState.html)).

If FIS can't restore a subnet, for example because its `FIS-Ready` tag was removed during the run, restore it by hand. The first command shows the FIS network ACL (tagged `managedByFIS=true`) the subnet is on and the association ID. Re-associate the network ACL the subnet used before the run, as your infrastructure code or your own pre-run record names it, then delete the FIS network ACL:

```bash
aws ec2 describe-network-acls --region <YOUR REGION> \
  --filters Name=tag:managedByFIS,Values=true Name=association.subnet-id,Values=<SUBNET ID> \
  --query "NetworkAcls[].Associations[?SubnetId=='<SUBNET ID>'].[NetworkAclId,NetworkAclAssociationId][]"
aws ec2 replace-network-acl-association --region <YOUR REGION> \
  --association-id <ASSOCIATION ID> --network-acl-id <ORIGINAL NETWORK ACL ID>
aws ec2 delete-network-acl --region <YOUR REGION> --network-acl-id <FIS NETWORK ACL ID>
```

Delete the FIS network ACL only once no subnet is associated with it. The deny statements in the table and stream policies stop applying at the time in their `aws:CurrentTime` condition. To remove one earlier, read the policy with `aws dynamodb get-resource-policy --resource-arn <TABLE OR STREAM ARN>`, remove only the statements whose `Sid` starts with `DoNotModifyFisDynamoDbPauseReplication` followed by your experiment ID, and write the rest back with `aws dynamodb put-resource-policy --resource-arn <TABLE OR STREAM ARN> --policy file://<FILE>`. Use `aws dynamodb delete-resource-policy` only if FIS's statements are the only ones left.

Monitor these metrics during the experiment:
- DynamoDB API call success/failure rates
- Application error logs and exception counts
- Network connectivity metrics from application instances
- Circuit breaker state changes
- User experience and transaction success rates

## Safety Considerations

- Test in non-production environments first
- Limit who can add the `FIS-Ready` tag to subnets and DynamoDB tables, for example with an `aws:TagKeys` condition on `ec2:CreateTags` and `dynamodb:TagResource`: anyone who can add it can bring a resource into this experiment's scope
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
