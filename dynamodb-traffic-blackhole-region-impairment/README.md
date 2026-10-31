# AWS Fault Injection Service Experiment: DynamoDB Traffic Blackhole Region Impairment

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

If network traffic between the tagged subnets and DynamoDB is blocked and replication of the tagged global tables is paused for 10 minutes, DynamoDB calls from those subnets should fail with network timeouts, while calls from other subnets and calls to other AWS services keep working. Monitoring should detect the failure within 2-3 minutes and notify the team within 5 minutes. If automated failover to another Region is configured, it should complete before the 10-minute fault ends. To test a manual failover that takes longer, raise both actions' `duration` so the fault lasts until the failover should be complete.

### What does this enable me to verify?

* Network-level DynamoDB connectivity monitoring and alerting works correctly
* Application timeout and retry logic handles network failures appropriately  
* Circuit breaker patterns function as expected for DynamoDB connectivity issues
* Graceful degradation or failover mechanisms activate when DynamoDB is unreachable
* Error handling and user experience during complete DynamoDB network blackouts
* Recovery behavior when network connectivity is restored

## Prerequisites

Before running this experiment, ensure that:

1. You have created the IAM role for FIS from `fis-iam-trust-relationship.json` and `dynamodb-traffic-blackhole-region-impairment-iam-policy.json`, after replacing `<YOUR REGION>` and `<YOUR AWS ACCOUNT>` in the policy. The policy covers multi-Region eventually consistent (MREC) global tables. For multi-Region strongly consistent (MRSC) global tables, also allow `dynamodb:InjectError`, which the [FIS actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html#global-table-pause-replication) lists for them.
2. You have created the FIS experiment template from `dynamodb-traffic-blackhole-region-impairment-template.json`, after replacing `<YOUR AWS ACCOUNT>` and `<YOUR ROLE NAME>` in `roleArn`.
3. The EC2 subnets containing your application instances have the `FIS-Ready=True` tag, and your application reaches DynamoDB from them through the Regional endpoint, for example through a DynamoDB gateway endpoint. Use subnets dedicated to the experiment: every resource with a network interface in a tagged subnet loses DynamoDB access (see [What else is affected](#what-else-is-affected)).
4. The DynamoDB global tables your application uses have the `FIS-Ready=True` tag on their replica in the Region where you run the experiment. The template pauses replication of every global table with this tag in that Region.
5. Both targets match something. The template sets `emptyTargetResolutionMode` to `fail`, so if no subnet or no global table replica in the Region carries the tag, the experiment fails before it changes anything ([experiment options](https://docs.aws.amazon.com/fis/latest/userguide/experiment-options.html)). To run only the network part, remove the `pauseReplication` action and the `dynamodbTables` target.
6. The network ACL of each tagged subnet has room for the deny rules FIS adds: one in each direction for each CIDR in the Region's DynamoDB prefix list. The [FIS actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html#disrupt-connectivity) says: "When the scope is not `all`, the maximum number of entries in network ACLs is 20." In testing, the `com.amazonaws.us-east-1.dynamodb` prefix list had 8 CIDRs, and the network ACL FIS created from the VPC's default network ACL had 20 entries. To count the CIDRs in your Region:

   ```bash
   PL=$(aws ec2 describe-managed-prefix-lists --region <YOUR REGION> \
     --filters Name=prefix-list-name,Values=com.amazonaws.<YOUR REGION>.dynamodb \
     --query 'PrefixLists[0].PrefixListId' --output text)
   aws ec2 get-managed-prefix-list-entries --region <YOUR REGION> --prefix-list-id "$PL" --query 'Entries[].Cidr'
   ```

7. Your application instances are running in the tagged subnets and actively using DynamoDB.
8. You have appropriate monitoring and observability in place to track the impact.
9. The experiment was tested in us-east-1, with two tagged subnets on the VPC's default network ACL, a DynamoDB gateway endpoint, and multi-Region eventually consistent global tables replicated to us-west-2. Interface (PrivateLink) endpoints for DynamoDB, IPv6, network ACLs with more rules than the default one, and strongly consistent global tables weren't tested.

## How it works

The template runs two actions at the same time, each for 10 minutes by default:

- `blockDynamoDBTraffic` uses the `aws:network:disrupt-connectivity` action with `scope: dynamodb` to block all network traffic between your application subnets and the DynamoDB regional endpoints.
- `pauseReplication` uses the `aws:dynamodb:global-table-pause-replication` action to pause replication of the tagged global tables. Tables may continue to be replicated for up to 5 minutes after the action begins ([FIS actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html#global-table-pause-replication)).

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

**Measured behavior**: In four live tests in the configuration that Prerequisite 9 describes, with a Lambda function in the tagged subnets that called DynamoDB once a second with a 1-second connect timeout, a 2-second read timeout and no retries:
- FIS created one network ACL tagged `managedByFIS=true` for both subnets. It kept the original allow rule (renumbered from 100 to 155) and added a deny rule in each direction for each of the 8 CIDRs in the `com.amazonaws.us-east-1.dynamodb` prefix list.
- DynamoDB calls from the tagged subnets failed with network timeouts within 5 seconds of the association. They succeeded again within 2 seconds of FIS restoring the original association, both when the action ended and when the experiment was stopped.
- During the fault, an S3 call through an S3 gateway endpoint in the same subnets kept working, and so did DynamoDB calls from an untagged subnet that uses the same network ACL.
- Replication from us-east-1 to us-west-2 stopped within seconds. Replication into us-east-1 continued for up to 3.6 minutes. Both directions resumed within 4.6 minutes after the pause ended or the experiment was stopped, and no successful write was lost.

### What else is affected

- The experiment targets every subnet in the Region tagged `FIS-Ready: True`, and every resource with a network interface in those subnets loses DynamoDB connectivity, whether or not it belongs to your application. Other experiments in this library use the same tag on subnets, so a subnet you tagged for one of them is a target here too.
- It also targets every DynamoDB global table replica tagged `FIS-Ready: True` in the Region where it runs, and pauses its replication. Every reader of those tables' replicas in other Regions sees data that stops changing, whatever subnet it runs in.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until both actions complete (10 minutes by default).

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

When the actions end, or when you stop the experiment, FIS restores each subnet's original network ACL association, deletes the network ACL it created, and removes its statements from the table and stream policies. In testing, DynamoDB calls from the tagged subnets succeeded again within 2 seconds of the restore, and replication resumed in both directions within 4.6 minutes. A stop condition stops the experiment the same way. A stopped experiment can't be resumed; start a new one. To check a stop condition before you rely on it, set its alarm to `ALARM` with `aws cloudwatch set-alarm-state` while a run is in progress, and check that FIS stops the experiment ([SetAlarmState](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_SetAlarmState.html)).

Monitor these metrics during the experiment:
- DynamoDB API call success/failure rates
- Application error logs and exception counts
- Network connectivity metrics from application instances
- Circuit breaker state changes
- User experience and transaction success rates

## Safety Considerations

- Test in non-production environments first
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
