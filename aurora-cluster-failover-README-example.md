# AWS Fault Injection Service Experiment: Aurora Cluster Failover

This is an experiment template for use with AWS Fault Injection Service (FIS) and 
fis-template-library-tooling. This experiment template requires deployment into 
your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Description

Explore the impact of failing over of an Amazon Aurora cluster. 

In this experiment we target an Amazon Aurora Cluster in the current region that have a specific tag attached. 

## Hypothesis

Failover of an Aurora Cluster between the reader and writer instance may cause requests to fail for a brief period of time, but requests will automatically recover, and the application will continue to function as normal after the failover.

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment and perform the failover operation on the targeted Aurora clusters.
2. The IAM role specified in the `roleArn` field has the required permissions to perform the failover operation.
3. The Aurora clusters you want to target have the `FIS-Ready=True` tag.
4. The targeted Aurora clusters are configured for Multi-AZ deployment with writer and reader instances, and proper replication is set up.

## How it works

This template simulate an Aurora DB cluster failover for a DB cluster. It will promotes one of the Aurora Replicas (read-only instances) in the DB cluster to be the primary DB instance (the cluster writer). To use the scenario you must have Amazon Aurora clusters that have the tag `FIS-Ready=True`.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or 
business metric requiring an immediate end of the fault injection. This 
template makes no assumptions about your application and the relevant metrics 
and does not include stop conditions by default.

## Next Steps
As you adapt this scenario to your needs, we recommend reviewing the tag names you use to ensure they fit your specific use case, identifying business metrics tied to the instances you are stopping, creating an Amazon CloudWatch metric and Amazon CloudWatch alarm, and adding a stop condition tied to the alarm.

## Import Experiment
You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling). 