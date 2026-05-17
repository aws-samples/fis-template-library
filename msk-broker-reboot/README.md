# AWS Fault Injection Service Experiment: MSK Broker Reboot

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

When an Amazon MSK broker is rebooted, Kafka producers switch to other available brokers and continue producing with minimal message loss. Consumer groups detect the broker unavailability, rebalance their partition assignments, and resume consuming within 60 seconds. Partition leaders hosted on the rebooted broker are re-elected to other brokers. The MSK cluster transitions through `REBOOTING_BROKER` state and returns to `ACTIVE` automatically within 15 minutes. No manual intervention is required.

### What does this enable me to verify?

* Kafka producer `acks` configuration and retry behavior during a single broker failure
* Consumer group rebalancing speed and partition reassignment to healthy brokers
* MSK cluster recovery time and automatic broker restart after a reboot event
* Application resilience to partition leader changes on the rebooted broker
* End-to-end Kafka client configuration (`session.timeout.ms`, `heartbeat.interval.ms`, retry policies)

## Prerequisites

Before running this experiment, ensure that:

1. You have the roles created for FIS and SSM Automation to use. Example IAM policy documents and trust policies are provided.
2. You have created the SSM Automation Document from the sample provided (`msk-broker-reboot-automation.yaml`).
3. You have created the FIS Experiment Template from the sample provided (`msk-broker-reboot-experiment-template.json`).
4. The MSK cluster is in `ACTIVE` state before starting the experiment.
5. You have identified the target broker ID using the command below.
6. Update `<YOUR MSK CLUSTER ARN>` and `BrokerId` in the experiment template with your cluster ARN and target broker ID.
7. Your Kafka producers are configured with `acks=all` and appropriate retry logic.
8. Your Kafka consumers have appropriate `session.timeout.ms` and `heartbeat.interval.ms` settings.
9. You have appropriate monitoring and observability in place to track the impact of the experiment.

```bash
# List MSK broker IDs
aws kafka list-nodes --cluster-arn <YOUR-CLUSTER-ARN> \
  --query 'NodeInfoList[].BrokerNodeInfo.[BrokerId,CurrentBrokerSoftwareInfo.KafkaVersion]' \
  --output table

# Verify cluster is ACTIVE before starting
aws kafka describe-cluster --cluster-arn <YOUR-CLUSTER-ARN> \
  --query 'ClusterInfo.State'
```

## How it works

Amazon MSK does not have a native FIS action for broker reboot. This experiment uses an SSM Automation document invoked by FIS to call the MSK `RebootBroker` API directly.

The experiment follows this sequence:

1. **Broker Reboot**: SSM Automation calls `RebootBroker` with the specified `ClusterArn` and `BrokerId`.
2. **State Transition**: The MSK cluster transitions from `ACTIVE` to `REBOOTING_BROKER`.
3. **Leader Election**: Kafka re-elects partition leaders for partitions whose leader was on the rebooted broker.
4. **Consumer Rebalance**: Consumer groups detect the partition leader changes and rebalance assignments.
5. **Wait**: The automation polls `DescribeCluster` until the cluster state returns to `ACTIVE`.
6. **Complete**: FIS marks the experiment as completed.

> **Note**: Only one broker can be rebooted at a time. Wait for the cluster to return to `ACTIVE` before rebooting another broker.

To monitor the cluster state and broker metrics during the experiment:

```bash
# Monitor MSK cluster state
watch -n 10 'aws kafka describe-cluster \
  --cluster-arn <YOUR-CLUSTER-ARN> \
  --query "ClusterInfo.State"'
```

## Stop Conditions

The experiment does not have any specific stop conditions defined. The broker reboot completes automatically when the MSK cluster returns to `ACTIVE` state.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Identifying the target broker ID using `aws kafka list-nodes` before running the experiment.
2. Verifying the MSK cluster is in `ACTIVE` state before starting the experiment.
3. Identifying business metrics tied to your Kafka cluster, such as `UnderReplicatedPartitions`, `ActiveControllerCount`, and `MessagesInPerSec`.
4. Creating Amazon CloudWatch alarms on `UnderReplicatedPartitions` and `ActiveControllerCount` to detect broker failure impact.
5. Adding a stop condition tied to a critical business alarm to automatically halt the experiment if needed.
6. Verifying your Kafka producers use `acks=all` and have retry logic with appropriate backoff.
7. Verifying your Kafka consumers have tuned `session.timeout.ms` and `heartbeat.interval.ms` for fast rebalancing.
8. Testing multiple brokers sequentially (waiting for `ACTIVE` between each) to understand cluster-wide resilience.
9. Documenting the findings from your experiment and updating your incident response procedures accordingly.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
