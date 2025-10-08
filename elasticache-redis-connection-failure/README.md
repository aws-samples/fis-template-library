# AWS Fault Injection Service Experiment: ElastiCache Redis Connection Failure

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Example Hypothesis

When Redis connections are disrupted, applications should gracefully handle the failure through circuit breaker mechanisms within 30 seconds. Client retry storms should be prevented, and applications should continue operating in degraded mode without cascading failures. Once Redis connectivity is restored, normal operations should resume within 60 seconds.

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
5. Your applications implement proper Redis client circuit breakers and retry logic
6. You have appropriate monitoring and observability in place to track the impact of the experiment.

## How it works

This experiment simulates Redis connection failures by modifying ElastiCache security groups to block connections for a specified duration. The experiment follows this sequence:

1. **Dynamic Discovery**: Scans all ElastiCache replication groups to find clusters tagged with "FIS-Ready":"True"
2. **Connection Disruption**: Removes security group rules to block Redis access from applications
3. **Sustained Failure**: Maintains connection disruption for specified duration to test resilience
4. **Restoration**: Restores security group rules to resume normal connectivity

The connection failure is implemented using an SSM Automation Document invoked by FIS. The SSM Automation Document modifies security group rules to block access to Redis, then restores connectivity after the specified duration.

To verify the experiment is working properly, you can monitor Redis connectivity and application behavior:

```bash
# Monitor Redis connectivity
watch -n 5 'redis-cli -h <redis-endpoint> ping'

# Check application health endpoints
curl -I https://<your-app>/health

# Monitor security group rules
aws ec2 describe-security-groups --group-ids <security-group-id> --query 'SecurityGroups[0].IpPermissions'
```

During the experiment, you should observe connection timeouts when attempting to reach Redis and applications activating circuit breakers or degraded mode operations.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until all actions are completed or until manually stopped.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to your Redis connectivity, such as cache hit rates and application error rates.
3. Creating Amazon CloudWatch metrics and alarms to monitor Redis connectivity and circuit breaker activation.
4. Adding stop conditions tied to critical business metrics to automatically halt the experiment if needed.
5. Implementing appropriate circuit breakers in your application to handle Redis unavailability gracefully.
6. Testing your application's behavior under various connection failure scenarios and durations.
7. Documenting the findings from your experiment and updating your incident response procedures accordingly.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
