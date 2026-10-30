# AWS Fault Injection Service Experiment: Aurora Cluster Failover

This is an experiment template for use with AWS Fault Injection Service (FIS) and 
fis-template-library-tooling. This experiment template requires deployment into 
your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Description

Explore the impact of an Amazon Aurora cluster failover.

This experiment targets every Amazon Aurora DB cluster with the `FIS-Ready=True` tag in the Region where you run it.

## Hypothesis

Failover of an Aurora Cluster between the reader and writer instance may cause requests to fail for a brief period of time, but requests will automatically recover, and the application will continue to function as normal after the failover.

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment and perform the failover operation on the targeted Aurora clusters.
2. The IAM role specified in the `roleArn` field has the required permissions to perform the failover operation. Create it from `fis-iam-trust-relationship.json` and `aurora-cluster-failover-iam-policy.json`, after replacing `<YOUR REGION>` and `<YOUR AWS ACCOUNT>` in the policy.
3. The Aurora clusters you want to target have the `FIS-Ready=True` tag. The template uses `selectionMode: ALL`, so every tagged Aurora cluster in the Region fails over. The [FIS actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html#failover-db-cluster) says this action also supports Amazon DocumentDB clusters, so tag only the clusters you mean to fail over.
4. The targeted Aurora clusters have a writer instance and at least one reader instance (Aurora Replica), in different Availability Zones.
5. You have created the FIS experiment template from `aurora-cluster-failover-template.json`, after replacing `<YOUR AWS ACCOUNT>` and `<YOUR ROLE NAME>` in `roleArn`.

## How it works

This template uses the `aws:rds:failover-db-cluster` action, which calls the Amazon RDS [FailoverDBCluster](https://docs.aws.amazon.com/AmazonRDS/latest/APIReference/API_FailoverDBCluster.html) API on each target cluster. This is a real failover, not a simulation: Aurora promotes one of the Aurora Replicas (read-only instances) in the DB cluster to be the primary DB instance (the cluster writer), and the former writer restarts as a reader. The writer and reader roles usually stay swapped after the experiment ends, so check which instance is the writer before you run the experiment again.

The action ends as soon as the API call returns, so FIS reports the experiment as completed while the failover is still in progress.

**Measured behavior**: In four live tests in us-east-1, on an Aurora PostgreSQL 17.9 cluster with one writer and one reader (`db.t4g.medium`) in two Availability Zones:
- FIS completed the action in under 0.5 seconds. Amazon RDS logged "Completed customer initiated failover" 10 to 20 seconds after the action ended.
- In three runs, a client writing every second through the cluster endpoint saw writes fail for at most 2 seconds: up to 1 second on new connections, and 2 seconds on a long-lived connection while it dropped and reconnected to the new writer. Reads through the reader endpoint failed for 5 to 6 seconds.
- In the fourth run, Aurora promoted the reader and then, about 8 seconds after logging the failover complete, made the original writer the writer again. CloudTrail shows no second API call. Writes failed in two short bursts over 15 seconds, and reads through the reader endpoint over 27 seconds.
- No acknowledged write was lost in any run.
- Both instances were `available` again within 25 seconds of RDS logging the failover complete.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until the failover action completes, which happens as soon as the FailoverDBCluster call returns. Stopping the experiment does not interrupt or undo a failover that has started: in two live tests, a stop sent 4 seconds after the failover call was rejected because the experiment had already completed, and the failover went ahead.

Stop conditions are based on an AWS CloudWatch alarm based on an operational or 
business metric requiring an immediate end of the fault injection. This 
template makes no assumptions about your application and the relevant metrics 
and does not include stop conditions by default.

## Next Steps
As you adapt this scenario to your needs, we recommend:
1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to the database operations your application runs on the targeted clusters.
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of the failover.
4. Adding a stop condition tied to the alarm. The failover action ends within a second, so a stop condition can't interrupt a failover that has started.
5. Checking how your application's connection pool and retry logic handle connections that drop during the failover.

## Import Experiment
You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling). 