# AWS Fault Injection Service Experiment: MySQL RDS Load Test and Failover

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE

## Hypothesis

Under high CPU load conditions, a Multi-AZ MySQL RDS instance will successfully failover from the primary to the standby instance with approximately 25 seconds of downtime. Applications using proper connection handling should automatically reconnect and continue functioning normally after the failover completes.

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment and perform the failover operation on RDS instances.
2. The IAM role specified in the `roleArn` field has the required permissions to perform the failover operation and execute SSM documents.
3. The MySQL RDS instances you want to target have the `FIS-Ready=True` tag.
4. The EC2 instances you want to use for load testing have the `FIS-Ready=True` tag.
5. The targeted MySQL RDS instances are configured for Multi-AZ deployment.
6. SSM Agent is installed and running on the target EC2 instances.
7. The IAM role associated with the EC2 instances has the necessary permissions for SSM.
8. You have deployed the SSM document template (`mysql-rds-loadtest-failover-ssm-template.json`) to your account.

## ⚠️ Database Impact Warning

**IMPORTANT**: This experiment will create test tables in your MySQL database:

### Tables Created:
- `loadtest` - Load testing table with auto-increment primary key
- Test database (if `DBName` parameter specifies a non-existing database)

### Impact:
- Tables will persist after the experiment completes
- Test data will be inserted during load testing
- No existing data will be modified or deleted
- Tables use `IF NOT EXISTS` clauses to avoid conflicts

### Cleanup:
If you need to remove the test table after the experiment, you can manually drop it:
```sql
DROP TABLE IF EXISTS loadtest;
```

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until all actions have been completed on the targeted resources.

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
5. Customizing the SSM document parameters to adjust load test concurrency, duration, and target CPU utilization.
6. Testing the load generation script independently before running the full FIS experiment.

## Infrastructure Examples

See the `examples/` directory for complete infrastructure templates and deployment guidance to help you set up the necessary resources for this experiment.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
