# AWS Fault Injection Service Experiment: DynamoDB Region Impairment

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

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

1. You have created the IAM role for FIS from `dynamodb-region-impairment-fis-role-iam-policy.json` and `fis-iam-trust-relationship.json`, and the IAM role for SSM Automation from `dynamodb-region-impairment-ssm-automation-role-iam-policy.json` and `ssm-iam-trust-relationship.json`.
2. You have created an SSM Automation document named `DynamoDB-Region-Impairment` from `dynamodb-region-impairment-automation.yaml`.
3. You have created the FIS experiment template from `dynamodb-region-impairment-experiment-template.json`, and replaced `<YOUR REGION>`, `<YOUR AWS ACCOUNT>`, `<YOUR TABLE NAME>`, `<YOUR ROLE NAME>` and `<YOUR SSM AUTOMATION ROLE NAME>` in the template and in both policy files.
4. The DynamoDB global table (version 2019.11.21) you want to target has the `FIS-Ready=True` tag on its replica in the target Region. The pause action targets every global table with this tag, but the SSM document blocks only the table named in `tableName`. Tag only that table, or add one SSM action per table.
5. You have appropriate monitoring and observability in place to track the impact of the experiment.

## How it works

This experiment simulates a complete regional DynamoDB failure by combining two complementary actions:

### Timeline
Measured times in parentheses are from the experiment start in our tests.
- **T+0**: Both actions start. FIS adds its pause statements to the table and stream policies.
- **T+10s**: The SSM automation adds the `FISDenyAccess` statement to the table policy, after the FIS statements are in place (36 s).
- **T+10m10s**: The SSM automation removes `FISDenyAccess` (10 min 40 s).
- **T+12m**: The FIS action ends and removes its pause statements (12 min 35 s).

**Note**: The durations can be modified to fit your testing needs, but the staggered timing should be maintained to prevent race conditions and ensure proper cleanup sequencing.

**Eventual consistency**: The SSM automation blocks access with the DynamoDB `PutResourcePolicy` API. When you attach a resource-based policy using this API, [the policy application is eventually consistent](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_PutResourcePolicy.html). Increase the experiment duration to account for this: raise `duration` in the SSM action's `documentParameters`, and raise the pause action's `duration` and the SSM action's `maxDuration` by the same amount. This keeps the 2-minute recovery window, and the automation keeps the same time to clean up before `maxDuration`.

**Measured behavior**: In five live tests in us-east-1 with a us-west-2 replica:
- Replication from us-east-1 to us-west-2 stopped within seconds. Replication into us-east-1 continued for 2 to 4 minutes, within the 5 minutes that the [FIS actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html) allows.
- Replication resumed 13 seconds to 3 minutes after the pause ended or the experiment was stopped. No successful write was lost.

### Actions

**1. Native FIS Action (aws:dynamodb:global-table-pause-replication)**
- Blocks DynamoDB replication service from synchronizing data between regions
- Duration: 12 minutes
- Adds deny statements with an expiry time to the table and stream policies
- Removes its statements when the action ends or the experiment is stopped

**2. Custom SSM Automation (blockDynamoDBAccess)**
- Blocks reads and writes on the named table and its indexes in the target Region: `GetItem`, `BatchGetItem`, `Query`, `Scan`, `PutItem`, `UpdateItem`, `DeleteItem`, `BatchWriteItem`, `ConditionCheckItem` and PartiQL statements. Transactions are blocked through the same actions.
- Denies every principal except the DynamoDB replication service-linked role, so replication stays under the FIS pause action's control
- Duration: 10 minutes with 10-second initial delay to avoid race conditions
- Removes only its own statement and keeps every other statement. The removal also runs if the experiment is stopped or a step fails.

### Race Condition Prevention
Both actions change the same resource policy, and [`GetResourcePolicy` is eventually consistent](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_PutResourcePolicy.html). The SSM automation waits until the FIS statement is visible and writes with `ExpectedRevisionId`, so it cannot overwrite a newer version of the policy. DynamoDB blocks policy updates for 15 seconds after each update, so the automation retries until its write is accepted.

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

During the impairment periods, you should see "AccessDenied" errors when attempting operations on the us-east-1 table, while us-west-2 operations continue normally. Replace `id` with your table's partition key attribute. Because the policy application is eventually consistent, the first errors may not appear right away.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until both actions complete (12 minutes by default). If you stop it, FIS removes its pause statements and the SSM automation's `cleanupPolicy` step removes `FISDenyAccess`. If that step fails, remove the `FISDenyAccess` statement from the table's resource policy yourself, because until then every client stays blocked from the table.

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
