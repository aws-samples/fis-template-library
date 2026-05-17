# AWS Fault Injection Service Experiment: ElastiCache AZ Power Interruption

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

When power is interrupted to all ElastiCache nodes in a target Availability Zone, the primary node (if located in that AZ) fails over to a replica in a healthy AZ within 30 seconds. Applications using the primary endpoint reconnect automatically after the role change. Replica replacements remain blocked in the impaired AZ for the experiment duration, so the cluster operates at reduced capacity. After the power interruption ends, nodes in the target AZ rejoin the replication group and the cluster returns to full capacity.

### What does this enable me to verify?

* ElastiCache Multi-AZ automatic failover works correctly under an AZ-level power failure
* Applications handle primary endpoint changes gracefully without manual intervention
* Connection pool retry and reconnect logic functions correctly during AZ-level disruption
* Cluster behavior under reduced replica capacity while an AZ remains impaired
* CloudWatch alarms detect `ReplicationLag` spikes and `IsPrimary` role changes as expected

## Prerequisites

Before running this experiment, ensure that:

1. You have the roles created for FIS to use. An example IAM policy document and trust policy are provided.
2. You have created the FIS Experiment Template from the sample provided (elasticache-az-power-interruption-experiment-template.json).
3. The ElastiCache replication group(s) you want to target have the `FIS-Ready=True` tag.
4. Your replication group has Multi-AZ enabled with `AutomaticFailover=enabled`.
5. The replication group is **not** an ElastiCache Serverless resource — the `replicationgroup-interrupt-az-power` action does not support Serverless.
6. Update `<YOUR AVAILABILITY ZONE>` in the experiment template with the target AZ identifier (e.g., `us-east-1a`).
7. You have appropriate monitoring and observability in place to track the impact of the experiment.

## How it works

This experiment uses the native FIS action `aws:elasticache:replicationgroup-interrupt-az-power` to simulate an AZ-level power failure for ElastiCache replication groups. Unlike a node reboot or manual failover, this action blocks all replica replacements in the impaired AZ for the duration of the experiment, giving a more realistic simulation of a sustained AZ outage.

The experiment follows this sequence:

1. **Target Resolution**: FIS resolves all replication groups tagged `FIS-Ready=True` in the specified AZ.
2. **Power Interruption**: FIS interrupts power to nodes in the target AZ. If the primary is in that AZ, automatic failover promotes the replica with the least replication lag.
3. **Reduced Capacity**: Replica replacements in the impaired AZ are blocked for the experiment duration (`PT10M` by default).
4. **Recovery**: After the experiment ends, the impaired AZ is restored and nodes rejoin the replication group.

> **Note**: Resource targeting for this action supports only `resourceTags`. The `resourceArns` and `filters` selection modes are not supported.

To verify the experiment is working, monitor the primary node role change:

```bash
# Watch for role changes every 5 seconds
watch -n 5 'aws elasticache describe-replication-groups \
  --replication-group-id <YOUR-REPLICATION-GROUP-ID> \
  --query "ReplicationGroups[0].NodeGroups[].NodeGroupMembers[].[CacheClusterId,CurrentRole,PreferredAvailabilityZone]" \
  --output table'
```

## Stop Conditions

The experiment does not have any specific stop conditions defined. The AZ power interruption lasts for the configured `duration` parameter (`PT10M` by default) and recovers automatically.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Updating `<YOUR AVAILABILITY ZONE>` to match the AZ where your primary node typically runs.
3. Identifying business metrics tied to your cache layer, such as cache hit rates, connection counts, and application response times.
4. Creating Amazon CloudWatch alarms on `ReplicationLag`, `IsPrimary`, and `CurrConnections` metrics to monitor failover impact.
5. Adding a stop condition tied to a critical business alarm to automatically halt the experiment if needed.
6. Verifying your application uses the **primary endpoint** (not node-specific endpoints) so it can reconnect after a role change.
7. Testing your connection pool retry logic and reconnect timeout configuration.
8. Documenting the findings from your experiment and updating your runbooks accordingly.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
