# AWS Fault Injection Service Experiment: EC2 Spot Instances Interrupt

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Description

Explore the impact of EC2 Spot Instance interruptions.

In this experiment we target every running EC2 Spot Instance in the current account and Region that has the `FIS-Ready=True` tag.

## Hypothesis

If the targeted EC2 Spot Instances run in an Auto Scaling group behind a load balancer, our application will recover without manual action when they are interrupted: each instance uses the two-minute interruption notice to finish or hand off its work, Auto Scaling launches replacement instances, and the load balancer sends requests to the replacements. Because the experiment interrupts every targeted Spot Instance at the same time, we expect requests to fail until the first replacement is serving.

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment and send interruptions to EC2 Spot Instances.
2. The IAM role specified in the `roleArn` field has the required permissions to send the Spot Instance interruptions.
3. The EC2 Spot Instances you want to target have the `FIS-Ready=True` tag. The experiment interrupts every running Spot Instance with this tag in the account and Region, not only the instances in one Auto Scaling group, so tag only the instances you want to test. On-Demand Instances with the tag are not targeted.
4. At least one running Spot Instance has the tag. The template sets `emptyTargetResolutionMode` to `fail`, so otherwise the experiment interrupts nothing and fails with the message "Target resolution returned empty set."

## How it works

The template has one target and one action:

- The target selects all (`ALL`) running EC2 Spot Instances in the account and Region that have the `FIS-Ready=True` tag. On-Demand Instances and instances that are not running are not selected.
- The `aws:ec2:send-spot-instance-interruptions` action calls the EC2 `SendSpotInstanceInterruptions` API for the selected instances with `durationBeforeInterruption` set to two minutes (`PT2M`). Each instance gets an EC2 instance rebalance recommendation and a Spot Instance interruption notice right away, and EC2 interrupts the instance two minutes later. The experiment ends when the action completes, before the instances are interrupted.

In testing with four t3.micro Spot Instances in an Auto Scaling group (ELB health checks, 120-second grace period) behind an Application Load Balancer with default target group settings, and a client sending 20 requests a second through the load balancer:

- FIS interrupted all four instances with one `SendSpotInstanceInterruptions` call, and each experiment ended about 12 seconds after it started. The instances got the rebalance recommendation and the interruption notice within 2 seconds of the call, and EC2 started terminating them about 2 minutes (123 seconds) after the notice. Amazon EventBridge received the rebalance recommendation, the interruption warning and the state changes for every instance.
- With Capacity Rebalancing off, the last request to an old instance succeeded about 114 seconds after the notice, about 9 seconds before EC2 started terminating the instances. After that, no request succeeded until the first replacement served one: 42 to 122 seconds in three runs, with 831 to 2,437 failed requests. Auto Scaling replaced the instances one at a time, 2 minutes apart, so after EC2 started terminating the instances it took about 7 minutes or longer to get back to four healthy instances.
- With Capacity Rebalancing on, Auto Scaling took all four instances out of service as soon as the notice arrived and launched four replacements at once. No request succeeded for 17 seconds, from when the load balancer stopped sending requests to the old instances until the first replacement served one, and the two runs had 364 and 367 failed requests in total. This gap came right after the notice, not at the interruption: the replacements were healthy about 75 seconds before EC2 interrupted the old instances.
- The failed requests got HTTP 503 or HTTP 502 responses from the load balancer.

Your timings depend on your instance launch time, health checks and load balancer settings.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It ends as soon as the interruption action completes, about 12 seconds after the start in testing and about 2 minutes before EC2 interrupts the instances. In testing, a stop request sent 20 seconds after the start was rejected because the experiment had already ended, and EC2 still interrupted the instances on schedule. Once the experiment has ended, stopping it cannot cancel the interruption.

Stop conditions are based on an AWS CloudWatch alarm based on an operational or 
business metric requiring an immediate end of the fault injection. This 
template makes no assumptions about your application and the relevant metrics 
and does not include stop conditions by default.

## Next Steps
As you adapt this scenario to your needs, we recommend:
1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to the instances you are interrupting.
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of the interruption.
4. Adding a stop condition tied to the alarm to automatically halt the experiment if critical thresholds are breached. This experiment ends about 2 minutes before the instances are interrupted, so an alarm on the interruption's impact goes off after the experiment has ended and cannot stop it, but it still shows the impact.
5. Changing the target's `selectionMode` to `COUNT(n)` or `PERCENT(n)` if you want to interrupt only some of the tagged Spot Instances.
6. Testing with Capacity Rebalancing turned on if your Auto Scaling group uses Spot Instances. In testing it replaced the instances before the interruption and shortened the time without a successful request to 17 seconds, from 42 to 122 seconds with it off; that shorter gap came right after the interruption notice.

## Import Experiment
You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling). 
