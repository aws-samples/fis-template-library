# AWS Fault Injection Service Experiment: DynamoDB Region Impairment

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Example Hypothesis

When DynamoDB experiences a complete regional failure in us-east-1 which impacts my global table application, an alarm should be raised and the DevOps team notified within 5 minutes. The application should automatically failover to the us-west-2 replica within 2 minutes. During the impairment, all read and write operations should be redirected to the healthy region. Once the regional failure is resolved, the application should resume normal cross-region operation within 5 minutes.

### What does this enable me to verify?

* Appropriate customer experience metrics and observability of DynamoDB global tables is in place (were you able to detect there was a problem?)
* Alarms are configured correctly (were the right people notified and/or automations triggered?)
* Your app gracefully fails over to the healthy region and customers can continue using the application
* Your circuit breaker (if any) works as expected for regional failures
* Recovery controls (if any) work as expected when the region comes back online
* Cross-region replication monitoring and alerting functions correctly

## Prerequisites

Before running this experiment, ensure that:

1. You have the roles created for FIS and SSM Automation to use. Example IAM policy documents and trust policies are provided.
2. You have created the SSM Automation Document from the sample provided (dynamodb-region-impairment-automation.yaml)
3. You have created the FIS Experiment Template from the sample provided (dynamodb-region-impairment-experiment-template.json)
4. **Update all region references** in the template files to match your target region (currently set to us-east-1 as an example)
5. **Update table names** in the template files to match your DynamoDB global table names
6. The DynamoDB global table(s) you want to target have the "FIS-Ready":"True" tag and value
7. You have appropriate monitoring and observability in place to track the impact of the experiment.

## How it works

This experiment simulates a complete regional DynamoDB failure by combining two complementary actions:

### Timeline
- **T+0**: Both actions start simultaneously
- **T+10s**: SSM automation applies application-blocking policy (after FIS policy is established)  
- **T+10m**: SSM automation completes and cleans up its policy statements
- **T+12m**: FIS built-in action completes and auto-expires its policy statements

**Note**: The durations can be modified to fit your testing needs, but the staggered timing should be maintained to prevent race conditions and ensure proper cleanup sequencing.

### Actions

**1. Native FIS Action (aws:dynamodb:global-table-pause-replication)**
- Blocks DynamoDB replication service from synchronizing data between regions
- Duration: 12 minutes
- Uses time-based auto-expiring resource policy statements
- Automatically cleans up when experiment completes

**2. Custom SSM Automation (blockDynamoDBAccess)**
- Blocks all application access (reads/writes) to the table in the target region
- Duration: 10 minutes with 10-second initial delay to avoid race conditions
- Uses resource policy with role exclusions for FIS, SSM, and DynamoDB service roles
- Includes proper cleanup logic to remove only its policy statements

### Race Condition Prevention
Both actions start simultaneously but modify the same DynamoDB resource policy. A 10-second sleep was added at the start of the SSM automation document to prevent race conditions - allowing the built-in FIS action to successfully apply its policy first.

### Recovery Window Testing
This creates a 2-minute recovery window (minutes 10-12) where application access is restored but replication remains paused, allowing testing of partial recovery scenarios and cross-region failover behavior.

To verify the experiment is setup and working properly, you can use the AWS CLI to attempt operations on a targeted DynamoDB table:

```bash
# Test application access (should fail during impairment)
watch -n 5 'aws dynamodb put-item --table-name my-global-table --item "{\"id\":{\"S\":\"test-$(date +%s)\"},\"message\":{\"S\":\"test message\"}}" --region us-east-1 --no-cli-pager'

# Test reads (should also fail during impairment)  
watch -n 5 'aws dynamodb get-item --table-name my-global-table --key "{\"id\":{\"S\":\"test-item\"}}" --region us-east-1 --no-cli-pager'

# Test failover region (should continue working)
watch -n 5 'aws dynamodb put-item --table-name my-global-table --item "{\"id\":{\"S\":\"test-$(date +%s)\"},\"message\":{\"S\":\"test message\"}}" --region us-west-2 --no-cli-pager'
```

During the impairment periods, you should see "AccessDenied" errors when attempting operations on the us-east-1 table, while us-west-2 operations continue normally.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until all actions are completed or until manually stopped.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to your DynamoDB global table operations, such as application transaction rates and cross-region latency.
3. Creating Amazon CloudWatch metrics and alarms to monitor:
   - Application error rates during regional failures
   - Cross-region failover time
   - Data consistency after recovery
   - Replication lag between regions
4. Adding stop conditions tied to critical business metrics to automatically halt the experiment if unacceptable impact occurs.
5. Implementing appropriate circuit breakers in your application to handle regional DynamoDB failures gracefully.
6. Testing your application's regional failover mechanisms to ensure they work as expected.
7. Validating that your monitoring can distinguish between planned chaos experiments and real outages.
8. Documenting the findings from your experiment and updating your incident response procedures accordingly.
9. Testing recovery procedures to ensure applications properly resume cross-region operations after the experiment.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
