# AWS Fault Injection Service Experiments

This repository contains a collection of AWS Fault Injection Service (FIS) experiments designed to test the resilience and fault tolerance of your AWS resources and applications. These experiments simulate various failure scenarios to help you identify potential vulnerabilities and validate your system's ability to recover from disruptions.

## Experiment Types

The repository includes the following types of experiments:

1. **EC2 Instance Experiments**:
   - Instance Stop/Terminate: Simulate stopping or terminating EC2 instances to test auto-scaling and recovery mechanisms.

2. **Database Experiments**:
   - RDS Instance Failure: Simulate an Amazon Relational Database Service (RDS) instance failure to test database failover and recovery mechanisms.
   - DynamoDB Table Outage: Simulate a DynamoDB table outage to test application resilience and data replication strategies.

## Getting Started

To get started with these experiments, follow these steps:

1. **Prerequisites**: Ensure you have the necessary permissions and IAM roles configured to run FIS experiments in your AWS account.

2. **Setup**: Clone this repository and navigate to the desired experiment directory.

3. **Configuration**: Review the experiment configuration files (JSON or YAML) and customize them according to your specific requirements, such as target resources, actions, and stop conditions.

4. **Execution**: Use the AWS FIS console, AWS CLI, or AWS SDKs to create and run the experiment based on the provided configuration files.

5. **Monitoring**: Monitor the experiment execution and observe the impact on your resources and applications.

6. **Analysis**: Analyze the results and identify areas for improvement in your system's resilience and fault tolerance.

## Contributing

Contributions to this repository are welcome! If you have developed new FIS experiments or have suggestions for improving existing ones, please submit a pull request or open an issue.

## License

This repository is licensed under the [MIT License](LICENSE).

## Disclaimer

These experiments are designed to simulate failure scenarios in your AWS environment. While precautions have been taken to minimize potential risks, running these experiments may cause temporary disruptions or outages to your resources and applications. It is highly recommended to thoroughly review and test the experiments in a non-production environment before running them in a production setting.