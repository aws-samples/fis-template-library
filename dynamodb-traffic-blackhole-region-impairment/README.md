# AWS Fault Injection Service Experiment: DynamoDB Traffic Blackhole Region Impairment

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Example Hypothesis

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

1. You have created the IAM role for FIS with the provided policy document
2. You have created the FIS Experiment Template from the sample provided
3. **Update the AWS account ID** in the template files to match your account
4. The EC2 subnets containing your application instances have the "FIS-Ready":"True" tag
5. Your application instances are running in the tagged subnets and actively using DynamoDB
6. You have appropriate monitoring and observability in place to track the impact

## How it works

This experiment uses the `aws:network:disrupt-connectivity` action with `scope: dynamodb` to block all network traffic between your application subnets and the DynamoDB regional endpoints.

### Network ACL Mechanism

FIS temporarily:
1. Clones the existing network ACL associated with target subnets
2. Adds deny rules to block DynamoDB traffic in the cloned ACL
3. Associates the modified ACL with your subnets for the experiment duration
4. Automatically restores the original ACL when the experiment completes

### Duration and Scope

- **Duration**: 10 minutes (configurable via `duration` parameter)
- **Scope**: DynamoDB regional endpoints only - other AWS services remain accessible
- **Traffic Blocked**: All inbound and outbound DynamoDB API calls from target subnets
- **Intra-subnet**: Traffic between instances in the same subnet remains unaffected

## Target Resources

This experiment targets EC2 subnets tagged with `FIS-Ready: True`. All instances in these subnets will lose DynamoDB connectivity during the experiment.

## Stop Conditions

The experiment includes basic stop conditions. Consider adding CloudWatch alarms for:
- Application error rates exceeding thresholds
- Critical business metrics falling below acceptable levels
- Infrastructure health checks failing

## Observability Recommendations

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
