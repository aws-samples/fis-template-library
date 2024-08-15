# AWS Fault Injection Service Experiment: Stopping IIS on Windows EC2 Instance

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE

## Hypothesis

Our application will remain available and resilient when IIS (Internet Information Services) is stopped on one of our Windows EC2 instances, simulating a scenario where the web server crashes or fails to start.

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment and perform actions on Windows EC2 instances.
2. The IAM role specified in the `roleArn` field has the required permissions to perform the IIS stopping operation.
3. The Windows EC2 instances you want to target have the `FIS-Ready=True` tag.
4. SSM Agent is installed and running on the target Windows EC2 instances.
5. The IAM role associated with the EC2 instances has the necessary permissions for SSM.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until the IIS stopping action has been completed on the targeted resources.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or 
business metric requiring an immediate end of the fault injection. This 
template makes no assumptions about your application and the relevant metrics 
and does not include stop conditions by default.

## Next Steps
As you adapt this scenario to your needs, we recommend:
1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to the IIS service availability.
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of stopping IIS.
4. Adding a stop condition tied to the alarm to automatically halt the experiment if critical thresholds are breached.
5. Implementing proper logging and monitoring to track the behavior of your application when IIS is stopped.

## Import Experiment
You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling). 
