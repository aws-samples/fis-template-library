# AWS Fault Injection Service Experiment: MySQL RDS Load Test and Failover

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE

## Description

This experiment tests the resilience of a Multi-AZ MySQL RDS instance by generating high CPU load and then forcing a failover. It validates that applications can handle database failover events with minimal disruption while under load conditions.

## Hypothesis

Under high CPU load conditions, a Multi-AZ MySQL RDS instance will successfully failover from the primary to the standby instance with approximately 25 seconds of downtime. Applications using proper connection handling should automatically reconnect and continue functioning normally after the failover completes.

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment and perform the failover operation on RDS instances.
2. The IAM role specified in the `roleArn` field has the required permissions to perform the failover operation and execute SSM documents.
3. The MySQL RDS instances you want to target have the `FIS-Ready=True` tag.
4. The targeted MySQL RDS instances are configured for Multi-AZ deployment with primary and standby instances.
5. You have EC2 instances tagged with `FIS-Ready=True` and `FIS-Application=MySQL-LoadTest` for running the load tests.
6. You have deployed the required SSM document for load testing (see examples directory).
7. Your EC2 instances have network connectivity to the RDS instances and proper IAM permissions for SSM and CloudWatch.

## How it works

This template simulates high CPU load on a MySQL RDS instance and then initiates a failover. The experiment follows this workflow:

1. **Load Generation Phase**:
   - FIS executes an SSM document on tagged EC2 instances
   - The SSM document runs a high CPU load test against the MySQL database
   - Multiple worker processes create concurrent connections (configurable)
   - The script monitors CPU utilization until it reaches the target threshold
   - Load continues running in the background once target is reached

2. **Failover Phase**:
   - FIS triggers a forced failover of the RDS instance
   - The standby instance becomes the new primary
   - The database endpoint DNS name remains the same
   - Applications experience brief downtime during the transition

3. **Post-Failover Phase**:
   - The load test continues running for 5 minutes after the failover completes
   - This allows observation of how the new primary instance handles the load
   - Load test is then stopped automatically

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until all actions complete successfully.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or 
business metric requiring an immediate end of the fault injection. This 
template makes no assumptions about your application and the relevant metrics 
and does not include stop conditions by default.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to your MySQL RDS instance performance.
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of high CPU load and failover.
4. Adding a stop condition tied to the alarm to automatically halt the experiment if critical thresholds are breached.
5. Customizing the experiment parameters in the SSM document to adjust load test concurrency, duration, and target CPU utilization.
6. Testing the load generation script independently before running the full FIS experiment.

## Infrastructure Examples

See the `examples/` directory for:
- Complete CloudFormation template for deploying test infrastructure
- SSM document for MySQL load testing
- Detailed setup and customization instructions

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
