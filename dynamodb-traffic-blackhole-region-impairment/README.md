# AWS Fault Injection Service Experiment: DynamoDB Traffic Blackhole Region Impairment

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

When network connectivity to DynamoDB is completely blocked from my application subnets, monitoring systems should detect the connectivity failure within 2-3 minutes and trigger alerts. The DevOps team should be notified within 5 minutes through our alerting channels. If automated failover is configured, it should activate within 10 minutes. For manual intervention, the team should acknowledge the incident within 15 minutes and complete failover procedures within 30-45 minutes. All DynamoDB operations should fail with network timeout errors during the 10-minute impairment period.

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
3. The EC2 subnets containing your application instances have the `FIS-Ready=True` tag, and your application reaches DynamoDB from them through the Regional endpoint, for example through a DynamoDB gateway endpoint.
4. The DynamoDB global tables your application uses have the `FIS-Ready=True` tag on their replica in the Region where you run the experiment. The template pauses replication of every global table with this tag in that Region.
5. The network ACL of each tagged subnet has room for the deny rules FIS adds. The [FIS actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html#disrupt-connectivity) says: "When the scope is not `all`, the maximum number of entries in network ACLs is 20."
6. Your application instances are running in the tagged subnets and actively using DynamoDB.
7. You have appropriate monitoring and observability in place to track the impact.

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
- **Traffic Blocked**: All inbound and outbound DynamoDB API calls from target subnets
- **Intra-subnet**: Traffic between instances in the same subnet remains unaffected
- **Replication**: Paused for every global table tagged `FIS-Ready=True` in the Region where the experiment runs

**Measured behavior**: In four live tests in us-east-1, with two tagged subnets on the VPC's default network ACL, a DynamoDB gateway endpoint, and global tables replicated to us-west-2:
- FIS created one network ACL tagged `managedByFIS=true` for both subnets. It kept the original allow rule (renumbered from 100 to 155) and added a deny rule in each direction for each of the 8 CIDRs in the `com.amazonaws.us-east-1.dynamodb` prefix list.
- DynamoDB calls from the tagged subnets failed with network timeouts within 5 seconds of the association. They succeeded again within 2 seconds of FIS restoring the original association, both when the action ended and when the experiment was stopped.
- During the fault, an S3 call through an S3 gateway endpoint in the same subnets kept working, and so did DynamoDB calls from an untagged subnet that uses the same network ACL.
- Replication from us-east-1 to us-west-2 stopped within seconds. Replication into us-east-1 continued for up to 3.6 minutes. Both directions resumed within 4.6 minutes after the pause ended or the experiment was stopped, and no successful write was lost.

## Target Resources

This experiment targets EC2 subnets tagged with `FIS-Ready: True`. All instances in these subnets will lose DynamoDB connectivity during the experiment. It also targets the DynamoDB global table replicas tagged with `FIS-Ready: True` in the Region where it runs, and pauses their replication.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until both actions complete (10 minutes by default). When the actions end, or when you stop the experiment, FIS restores each subnet's original network ACL association, deletes the network ACL it created, and removes its statements from the table and stream policies.

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

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
