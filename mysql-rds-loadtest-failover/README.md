# AWS Fault Injection Service Experiment: MySQL RDS Load Test and Failover

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Description

This experiment tests the resilience of a Multi-AZ MySQL RDS instance by generating high CPU load and then forcing a failover. It helps validate that your applications can handle database failover events with minimal disruption.

## Hypothesis

Under high CPU load conditions, a Multi-AZ MySQL RDS instance will successfully failover from the primary to the standby instance with approximately 25 seconds of downtime. Applications using proper connection handling should automatically reconnect and continue functioning normally after the failover completes.

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment and perform the failover operation on RDS instances.
2. The IAM role specified in the `roleArn` field has the required permissions to perform the failover operation and execute SSM documents.
3. You have deployed the CloudFormation template to create the required infrastructure including a Multi-AZ MySQL RDS instance.
4. The EC2 instance used for load testing has network connectivity to the RDS instance.
5. You have reviewed the experiment parameters and adjusted them according to your specific requirements.

## How it works

This template simulates high CPU load on a MySQL RDS instance and then initiates a failover. The experiment follows this workflow:

1. **Load Generation Phase**:
   - The SSM document runs a high CPU load test on the RDS instance
   - Multiple worker processes create concurrent connections (default: 25)
   - The script monitors CPU utilization until it reaches the target (default: 80%)
   - Once target CPU is reached (or timeout occurs), the script continues running in the background

2. **Failover Phase**:
   - FIS triggers a forced failover of the RDS instance
   - The standby instance becomes the new primary
   - The database endpoint DNS name remains the same
   - Applications experience ~25 seconds of downtime during the transition

3. **Post-Failover Phase**:
   - The load test continues running for 5 minutes after the failover completes
   - This allows observation of how the new primary instance handles the load

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to your MySQL RDS instance performance.
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of high CPU load and failover.
4. Adding a stop condition tied to the alarm to automatically halt the experiment if critical thresholds are breached.
5. Customizing the experiment parameters to adjust load test concurrency and duration.
6. Testing with different instance types to understand performance characteristics under various workloads.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
