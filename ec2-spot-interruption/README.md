# AWS Fault Injection Service Experiment: EC2 Spot Instances Interrupt

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Description

Explore the impact the termination of EC2 Spot Instances. 

In this experiment we target EC2 Spot Instances in the current region that have a specific tag attached. 

## Hypothesis

When an interruption occurs on EC2 Spot Instances, instances will gracefully terminate, and applications or services running on those instances will be automatically restarted on new Spot Instances or fallback to On-Demand Instances, ensuring minimal disruption to the overall system.

Specifically, we expect the following behavior:

1. **Graceful Termination**: Upon receiving the interruption signal, EC2 Spot Instances will initiate a graceful termination process, allowing applications or services to perform any necessary cleanup tasks or save their state before terminating.

2. **Automatic Restarting**: Applications or services running on the interrupted Spot Instances are configured for automatic restart and will be automatically launched on new Spot Instances or fallback to On-Demand Instances, depending on the defined scaling policies and capacity provisioning strategies.

3. **Load Balancing and Failover**: If the applications or services are running behind a load balancer, traffic will be automatically rerouted to the newly launched instances, ensuring seamless failover and minimizing downtime.

4. **Data Persistence**: Any persistent data or state associated with the applications or services running on the interrupted Spot Instances will be successfully recovered or replicated to the new instances, ensuring data consistency and integrity.

5. **Monitoring and Alerting**: The interruption event and subsequent recovery actions will be captured by the monitoring and alerting systems, providing visibility into the system's behavior and enabling timely incident response and analysis.

By validating this hypothesis, we can demonstrate the resilience of our applications and services running on EC2 Spot Instances and ensure that they can gracefully handle interruptions while minimizing the impact on end-users or customers.

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment and perform the termination of EC2 Spot Instance
2. The IAM role specified in the `roleArn` field has the required permissions to perform the termination operation.
3. The EC2 Spot Instance you want to target have the `FIS-Ready=True` tag.

## How it works

The experiment sends an interruption signal to 25% of targeted EC2 Spot Instances using the AWS API `aws:ec2:send-spot-instance-interruptions`. This action simulates a real-world scenario where the Spot Instances are interrupted due to changes in the Spot market or capacity constraints.

`durationBeforeInterruption`: A duration of 4 minutes (PT4M) is set before the interruption is triggered. This allows for any necessary preparations or cleanup tasks to be executed before the interruption occurs.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until all targeted resources have been interrupted.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or 
business metric requiring an immediate end of the fault injection. This 
template makes no assumptions about your application and the relevant metrics 
and does not include stop conditions by default.

## Next Steps
As you adapt this scenario to your needs, we recommend reviewing the tag names you use to ensure they fit your specific use case, identifying business metrics tied to the instances you are stopping, creating an Amazon CloudWatch metric and Amazon CloudWatch alarm, and adding a stop condition tied to the alarm.