# AWS Fault Injection Service Experiment: Aurora Cluster CPU Overload and Failover

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Description

This experiment simulates CPU overload on an Aurora PostgreSQL cluster and then initiates a failover to test the resilience of your database infrastructure under stress conditions.

## Hypothesis

High CPU load on an Aurora cluster will cause degraded performance, but a subsequent failover will restore normal operation with minimal disruption to application functionality. The system should automatically recover and continue processing requests after the failover completes.

## Prerequisites

Before running this experiment, ensure that:

1. You have an Aurora PostgreSQL cluster tagged with `FIS-Ready=True`
2. You have an EC2 instance tagged with `FIS-Ready=True` that can connect to the Aurora cluster
3. The Aurora cluster is configured for Multi-AZ deployment with writer and reader instances
4. You have created the required IAM role with the provided policy document
5. You have deployed the SSM document for load testing
6. You have configured appropriate CloudWatch monitoring and alarms

## How it works

This experiment simulates a high CPU load scenario followed by an Aurora DB cluster failover:

1. **Baseline establishment**: 5-minute delay to establish baseline metrics
2. **CPU load generation**: SSM document executes CPU-intensive queries on the Aurora cluster
3. **Failover initiation**: After the delay, promotes an Aurora Replica to be the primary writer
4. **Impact observation**: Load test continues to observe failover impact on performance

The experiment targets resources with the `FIS-Ready=True` tag for safety and control.

## Observability and stop conditions

This template does not include stop conditions by default. You should add CloudWatch alarms based on your specific operational metrics to automatically halt the experiment if critical thresholds are breached.

## Files included

- `aurora-cluster-failover-template.json`: Main FIS experiment template
- `aurora-cluster-failover-iam-policy.json`: Required IAM permissions
- `aurora-cluster-failover-ssm-template.json`: SSM document for load testing
- `fis-iam-trust-relationship.json`: IAM trust policy for FIS service
- `examples/`: Infrastructure examples and deployment guidance

## Next steps

1. Review and customize the experiment parameters for your environment
2. Set up CloudWatch monitoring and create appropriate alarms
3. Add stop conditions based on your operational metrics
4. Test the experiment in a non-production environment first
5. Create a CloudWatch dashboard to visualize experiment effects

## Import experiment

You can import the JSON experiment template into your AWS account via CLI or AWS CDK. For step-by-step instructions, see the [fis-template-library-tooling](https://github.com/aws-samples/fis-template-library-tooling) repository.
