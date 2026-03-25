# AWS Fault Injection Service Experiment: ElastiCache Redis Primary Node Reboot

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Example Hypothesis

When the Redis primary node is rebooted, applications should detect the brief connection disruption and reconnect automatically within 30 seconds. Connection pooling should handle the temporary unavailability gracefully, and no data should be lost during the reboot. Application performance should return to normal within 60 seconds of the node becoming available again.

### What does this enable me to verify?

* Appropriate Redis connection monitoring and observability is in place (were you able to detect the reboot?)
* Alarms are configured correctly for node availability changes (were the right people notified?)
* Your application handles brief Redis connection disruptions gracefully
* Connection pooling and retry logic work correctly during node reboots
* Recovery controls and reconnection mechanisms work as expected

## Prerequisites

Before running this experiment, ensure that:

1. You have the roles created for FIS and SSM Automation to use. Example IAM policy documents and trust policies are provided.
2. You have created the SSM Automation Document from the sample provided (elasticache-redis-primary-node-reboot-automation.yaml)
3. You have created the FIS Experiment Template from the sample provided (elasticache-redis-primary-node-reboot-experiment-template.json)
4. The ElastiCache Redis cluster(s) you want to target have the "FIS-Ready":"True" tag and value
5. Your Redis cluster has Multi-AZ enabled with `AutomaticFailover=enabled`
6. You have appropriate monitoring and observability in place to track the impact of the experiment.

## How it works

This experiment reboots the Redis primary node to test application resilience during brief connection disruptions. The experiment follows this sequence:

1. **Dynamic Discovery**: Scans all ElastiCache replication groups to find clusters tagged with "FIS-Ready":"True"
2. **Primary Identification**: Dynamically finds the current primary node using NodeGroups and CurrentRole
3. **Node Reboot**: Executes `reboot_cache_cluster` on the primary node
4. **Recovery Monitoring**: Tracks node status from "Rebooting cache cluster nodes" to "Available"

The reboot is implemented using an SSM Automation Document invoked by FIS. The SSM Automation Document identifies the primary node and reboots it, then monitors the recovery process until the node returns to available status.

To verify the experiment is working properly, you can monitor the node status and test connectivity:

```bash
# Monitor Redis connectivity during reboot
watch -n 5 'redis-cli -h <redis-endpoint> ping'

# Check node status
aws elasticache describe-replication-groups --replication-group-id <YOUR-CLUSTER-ID> --query 'ReplicationGroups[0].NodeGroups[0].NodeGroupMembers[?CurrentRole==`primary`].CacheNodeStatus'

# Monitor application health
curl -I https://<your-app>/health
```

During the experiment, you should see the node status change from "Available" to "Rebooting cache cluster nodes" and back to "Available" within 1-3 minutes.

## Stop Conditions

The experiment does not have any specific stop conditions defined. The reboot completes automatically when the node returns to "Available" status.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to your Redis operations, such as connection counts and application response times.
3. Creating Amazon CloudWatch metrics and alarms to monitor Redis node availability and connection health.
4. Adding stop conditions tied to critical business metrics to automatically halt the experiment if needed.
5. Implementing appropriate connection retry logic in your application to handle brief node unavailability.
6. Testing your application's Redis connection pooling and recovery mechanisms.
7. Documenting the findings from your experiment and updating your incident response procedures accordingly.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
