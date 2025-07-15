# AWS Fault Injection Service Experiments

This repository contains a collection of AWS Fault Injection Service (FIS) experiments designed to test the resilience and fault tolerance of your AWS resources and applications. These experiments simulate various failure scenarios to help you identify potential vulnerabilities and validate your system's ability to recover from disruptions.

## Available Experiments

Browse the experiment directories to find templates for various fault injection scenarios:

- **EC2 Instance Management**: `ec2-instances-terminate/`, `ec2-spot-interruption/`, `ec2-windows-stop-iis/`
- **Database Resilience**: `aurora-cluster-failover/`, `sap-ebs-pause-database-data/`
- **SAP Systems**: `sap-ec2-instance-stop-ascs/`, `sap-ec2-instance-stop-database/`
- **Simple Queue Service (SQS)**: `sqs-queue-impairment/`

Each experiment directory contains:
- Complete FIS experiment template (JSON)
- Required IAM policies and trust relationships
- Comprehensive README with setup instructions
- Additional automation files where applicable

## Getting Started

To use these experiments, follow these steps:

1. **Prerequisites**: Ensure you have the necessary permissions and IAM roles configured to run FIS experiments in your AWS account.

2. **Choose an Experiment**: Browse the available experiment directories and select one that matches your testing scenario.

3. **Review Documentation**: Read the experiment's README.md file thoroughly to understand prerequisites, expected behavior, and safety considerations.

4. **Configuration**: Customize the template files by replacing placeholder values (e.g., `<YOUR AWS ACCOUNT>`, `<YOUR REGION>`) with your specific AWS account information.

5. **Deploy**: Import the experiment template into your AWS account using the [FIS Template Library Tooling](https://github.com/aws-samples/fis-template-library-tooling).

6. **Execute Safely**: Run the experiment in a non-production environment first, with proper monitoring and stop conditions in place.

7. **Monitor and Analyze**: Observe the impact on your resources and analyze the results to improve your system's resilience.

## Contributing

We welcome contributions of new FIS experiment templates! 

**📋 Before contributing, please read our [Style Guide](STYLE_GUIDE.md) which details all requirements and standards.**

Key requirements for contributions:
- Follow the standardized directory structure and file naming conventions
- Include comprehensive documentation with safety disclaimers
- Provide complete IAM policies following least privilege principles
- Include observability and monitoring recommendations
- Reference the `ec2-windows-stop-iis/` directory as the gold standard example

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed contribution guidelines.

## Disclaimer

These experiments are designed to simulate failure scenarios in your AWS environment. While precautions have been taken to minimize potential risks, running these experiments may cause temporary disruptions or outages to your resources and applications. It is highly recommended to thoroughly review and test the experiments in a non-production environment before running them in a production setting.
