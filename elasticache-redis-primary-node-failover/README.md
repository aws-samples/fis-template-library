# AWS Fault Injection Service Experiment: ElastiCache Redis Primary Node Failover

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Example Hypothesis

When the Redis primary node fails over to a replica, applications should detect the failover and reconnect to the new primary within 30 seconds. Connection pooling should handle the DNS endpoint changes gracefully, and no data should be lost during the transition. Application performance should return to normal within 60 seconds of failover completion.

### What does this enable me to verify?

* Appropriate Redis connection monitoring and observability is in place (were you able to detect the failover?)
* Alarms are configured correctly for primary node changes (were the right people notified?)
* Your application handles Redis primary node changes gracefully
* Connection pooling and DNS resolution work correctly during failover
* Recovery controls and reconnection logic work as expected

## Prerequisites

Before running this experiment, ensure that:

1. You have the roles created for FIS and SSM Automation to use. Example IAM policy documents and trust policies are provided.
2. You have created the SSM Automation Document from the sample provided (elasticache-redis-primary-node-failover-automation.json)
3. You have created the FIS Experiment Template from the sample provided (elasticache-redis-primary-node-failover-experiment-template.json)
4. The ElastiCache Redis cluster(s) you want to target have the "FIS-Ready":"True" tag and value
5. Your Redis cluster has Multi-AZ enabled with `AutomaticFailover=enabled`
6. Your cluster has at least 1 primary + 1 replica node
7. You have appropriate monitoring and observability in place to track the impact of the experiment.

## How it works

This experiment forces a Redis primary node failover by using the ElastiCache TestFailover API to promote a replica node to primary. The experiment follows this sequence:

1. **Dynamic Discovery**: Scans all ElastiCache replication groups to find clusters tagged with "FIS-Ready":"True"
2. **Validation**: Ensures the cluster has `AutomaticFailover=enabled` and is in `available` status
3. **Failover Trigger**: Uses `test_failover` API to promote a replica to primary role
4. **DNS Update**: ElastiCache automatically updates the master endpoint to point to the new primary
5. **Role Swap**: The former primary becomes a replica, and the replica becomes the new primary

The failover is implemented using an SSM Automation Document invoked by FIS. The SSM Automation Document uses the ElastiCache TestFailover API to trigger the failover process, which automatically promotes a replica to primary and updates the DNS endpoint.

To verify the experiment is working properly, you can monitor the primary node before and after:

```bash
# Check current primary before experiment
aws elasticache describe-replication-groups --replication-group-id <YOUR-CLUSTER-ID> --query 'ReplicationGroups[0].NodeGroups[0].NodeGroupMembers[?CurrentRole==`primary`].CacheClusterId'

# Monitor during experiment
watch -n 5 'aws elasticache describe-replication-groups --replication-group-id <YOUR-CLUSTER-ID> --query "ReplicationGroups[0].Status"'
```

During the failover, you should see the cluster status change from "available" to "modifying" and back to "available" as the primary node changes.

## Stop Conditions

The experiment does not have any specific stop conditions defined. The failover completes automatically when the TestFailover operation finishes and the cluster returns to "available" status.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to your Redis operations, such as cache hit rates and application response times.
3. Creating Amazon CloudWatch metrics and alarms to monitor Redis failover impact.
4. Adding stop conditions tied to critical business metrics to automatically halt the experiment if needed.
5. Implementing appropriate connection retry logic in your application to handle primary node changes.
6. Testing your application's Redis connection pooling and DNS resolution during failover scenarios.
7. Documenting the findings from your experiment and updating your incident response procedures accordingly.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
