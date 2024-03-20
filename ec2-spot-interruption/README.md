# AWS Fault Injection Service Experiment: Interrupt EC2 Spot Instances

This experiment simulates an interruption of EC2 Spot Instances in your AWS environment. It is designed to test the resilience of your applications and services running on Spot Instances by triggering an interruption event.

## Hypothesis

When an interruption occurs on EC2 Spot Instances, instances will gracefully terminate, and applications or services running on those instances will be automatically restarted on new Spot Instances or fallback to On-Demand Instances, ensuring minimal disruption to the overall system.

Specifically, we expect the following behavior:

1. **Graceful Termination**: Upon receiving the interruption signal, EC2 Spot Instances will initiate a graceful termination process, allowing applications or services to perform any necessary cleanup tasks or save their state before terminating.

2. **Automatic Restarting**: Applications or services running on the interrupted Spot Instances are configured for automatic restart and will be automatically launched on new Spot Instances or fallback to On-Demand Instances, depending on the defined scaling policies and capacity provisioning strategies.

3. **Load Balancing and Failover**: If the applications or services are running behind a load balancer, traffic will be automatically rerouted to the newly launched instances, ensuring seamless failover and minimizing downtime.

4. **Data Persistence**: Any persistent data or state associated with the applications or services running on the interrupted Spot Instances will be successfully recovered or replicated to the new instances, ensuring data consistency and integrity.

5. **Monitoring and Alerting**: The interruption event and subsequent recovery actions will be captured by the monitoring and alerting systems, providing visibility into the system's behavior and enabling timely incident response and analysis.

By validating this hypothesis, we can demonstrate the resilience of our applications and services running on EC2 Spot Instances and ensure that they can gracefully handle interruptions while minimizing the impact on end-users or customers.

## Targets

The experiment targets all EC2 Spot Instances that have the tag `FIS-Ready: True`.

## Actions

The experiment performs the following action:

1. **Interrupt EC2 Spot Instances**: The experiment sends an interruption signal to all targeted EC2 Spot Instances using the AWS API `aws:ec2:send-spot-instance-interruptions`. This action simulates a real-world scenario where the Spot Instances are interrupted due to changes in the Spot market or capacity constraints.

### Parameters

- `durationBeforeInterruption`: A duration of 4 minutes (PT4M) is set before the interruption is triggered. This allows for any necessary preparations or cleanup tasks to be executed before the interruption occurs.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until all targeted resources have been interrupted.

## Role ARN

### IAM Role 

The iam-policy.json file within this directory has been provided as an example. This policy includes the following permissions:

1. **ec2:SendSpotInstanceInterruptions**: Allows the IAM role to send interruption signals to EC2 Spot Instances.

2. **ec2:DescribeSpotInstanceRequests** and **ec2:DescribeInstances**: Allows the IAM role to describe Spot Instance requests and instances, which is necessary for the experiment to identify the targeted resources.

3. **logs:CreateLogGroup**, **logs:CreateLogStream**, and **logs:PutLogEvents**: Allows the IAM role to create and write logs to Amazon CloudWatch Logs for monitoring and logging purposes during the fault injection experiment.

4. **fis:***: Grants full access to the AWS Fault Injection Simulator service, allowing the IAM role to create, manage, and run fault injection experiments.

The `Resource` field is set to `*`, which grants permissions to all resources for the specified actions. However, you should review and adjust the `Resource` field based on your specific requirements and best practices for least privilege access.

You can create an IAM role with this policy and specify the role ARN in the `roleArn` field of your FIS experiment configuration.

Note: This is just an example policy, and you should review and customize it according to your specific use case and security requirements. 

## Tags

The experiment is tagged with the name `interrupt-ec2-spot`.

## Experiment Options

- `accountTargeting`: The experiment is configured to run in a single AWS account.
- `emptyTargetResolutionMode`: If no resources matching the target criteria are found, the experiment will fail.

## Usage

1. Review and customize the experiment configuration as needed.
2. Create an IAM role with the necessary permissions for the experiment.
3. Replace `<YOUR AWS ACCOUNT>` and `<YOUR ROLE NAME>` with your AWS account ID and the name of the IAM role you created.
4. Deploy the experiment using the AWS Fault Injection Service console or CLI.
5. Monitor the experiment execution and observe the impact on your applications and services running on the targeted EC2 Spot Instances.
6. Analyze the results and identify any areas for improvement in your application's resilience and fault tolerance.

Please note that this experiment may cause disruptions to your running services, so it is recommended to run it in a non-production environment or during scheduled maintenance windows.