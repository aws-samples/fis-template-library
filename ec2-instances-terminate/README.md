# AWS Fault Injection Service Experiment: EC2 Instance Termination

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

Our application will remain available when 25% of the EC2 instances in its Auto Scaling group are terminated: the load balancer stops sending requests to the terminated instances and Auto Scaling replaces them. Requests sent to an instance before the load balancer stops using it can fail.

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment and terminate EC2 instances.
2. The IAM role specified in the `roleArn` field has the required permissions to perform the termination operation.
3. The EC2 instances you want to target have the `FIS-Ready=True` tag. The experiment selects from the instances with this tag in the account and Region, not only from one Auto Scaling group, so tag only the instances you want to test.
4. At least four running instances have the tag. The target selects 25% of them, rounded down, so with fewer than four it selects none: the experiment terminates nothing and fails with the message "Target resolution returned empty set."

## How it works

The template has one target and one action:

- The target selects 25% (`PERCENT(25)`) of the EC2 instances in the account and Region that have the `FIS-Ready=True` tag, rounded down and chosen at random. Stopped and terminated instances are not counted.
- The `aws:ec2:terminate-instances` action terminates the selected instances, and the experiment ends when the action completes.

In testing with four instances in an Auto Scaling group behind an Application Load Balancer with default settings, and a client sending 20 requests a second through the load balancer:

- FIS terminated one instance with one `TerminateInstances` call, and each experiment ended about 12 seconds after it started.
- The load balancer kept routing requests to the instance after the termination call until Auto Scaling deregistered it from the target group, 10 to 20 seconds later, and requests stopped failing within 3 seconds after that. During that window about one request in four failed, 59 to 107 per run: 35 or 36 got an HTTP 502 response from the load balancer, and the rest got no response within the client's 5-second timeout. Every other request succeeded.
- Auto Scaling launched a replacement 12 to 21 seconds after the termination, and the replacement served its first request 49 to 59 seconds after the termination.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It ends as soon as the terminate action completes, which took about 12 seconds from the start in testing, so there is little time to stop it, and stopping it does not restore a terminated instance.

Stop conditions are based on an AWS CloudWatch alarm based on an operational or 
business metric requiring an immediate end of the fault injection. This 
template makes no assumptions about your application and the relevant metrics 
and does not include stop conditions by default.

## Next Steps
As you adapt this scenario to your needs, we recommend:
1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to the instances you are terminating.
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of the termination.
4. Adding a stop condition tied to the alarm to automatically halt the experiment if critical thresholds are breached.

## Import Experiment
You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling). 
