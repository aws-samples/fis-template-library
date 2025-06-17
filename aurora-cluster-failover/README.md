# AWS Fault Injection Service Experiment: Aurora Cluster CPU Overload and Failover

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Description

This experiment simulates CPU overload on an Aurora PostgreSQL cluster and then initiates a failover to test the resilience of your database infrastructure under stress conditions.

## Hypothesis

High CPU load on an Aurora cluster will cause degraded performance, but a subsequent failover will restore normal operation with minimal disruption to application functionality. The system should automatically recover and continue processing requests after the failover completes.

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment and perform the failover operation on the targeted Aurora clusters.
2. The IAM role specified in the `roleArn` field has the required permissions to perform the failover operation and execute SSM documents.
3. You have deployed the CloudFormation template to create the required infrastructure including an Aurora PostgreSQL cluster with the `FIS-Ready=True` tag.
4. The targeted Aurora clusters are configured for Multi-AZ deployment with writer and reader instances, and proper replication is set up.
5. You have reviewed the experiment parameters and adjusted them according to your specific requirements.

## How it works

This template simulates a high CPU load scenario followed by an Aurora DB cluster failover. The experiment follows this workflow:

1. The experiment first runs a 5-minute delay action to establish baseline metrics
2. It executes an SSM document on an EC2 instance to generate load on the Aurora cluster
3. After the delay, it initiates a failover for the Aurora cluster, promoting one of the Aurora Replicas (read-only instances) to be the primary DB instance (the cluster writer)
4. The load test continues running to observe the impact of the failover on application performance

To use this scenario, you must have Amazon Aurora clusters that have the tag `FIS-Ready=True`.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to your Aurora database performance.
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of high CPU load and failover.
4. Adding a stop condition tied to the alarm to automatically halt the experiment if critical thresholds are breached.
5. Customizing the experiment parameters in the template file to adjust load test duration and intensity.
6. Creating a CloudWatch dashboard to visualize the experiment's effects on database performance.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
