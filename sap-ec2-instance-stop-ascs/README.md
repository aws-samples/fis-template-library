# AWS Fault Injection Service Experiment: EC2 Instance Termination

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE

## Description

Explore the impact of the interruption of EC2 Instance which hosts the SAP database. 

In this experiment we target EC2 Instances in the current region that have a specific tag attached. 

## Hypothesis

When an interruption occurs on the EC2 Instances hosting the ABAP SAP Central Services (ASCS), the ASCS process will failover to the Standby EC2 instance hosting EnQue Replication Server (ERS). The failover will occur within 5-15 minutes and user can resume operations. This validates SAP application cluster configuration.

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment.
2. The IAM role specified in the `roleArn` field has the required permissions to perform the termination operation.
3. All your AWS resources are correctly tagged. 
```
    "FIS-Application": "SAP",
    "FIS-Ready": "True",
    "FIS-SAP-App-Tier": "Application",
    "FIS-SAP-Environment-Type": "Dev",
    "FIS-SAP-HA-Node": "Primary",
    "FIS-SAP-SID": "S4"
```

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until all targeted resources have been interrupted.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or 
business metric requiring an immediate end of the fault injection. This 
template makes no assumptions about your application and the relevant metrics 
and does not include stop conditions by default.

## Next Steps
As you adapt this scenario to your needs, we recommend reviewing the tag names you use to ensure they fit your specific use case, identifying business metrics tied to the instances you are stopping, creating an Amazon CloudWatch metric and Amazon CloudWatch alarm, and adding a stop condition tied to the alarm.

## Import Experiment
You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling). 