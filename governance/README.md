# Welcome to the AWS Fault Injection Service (FIS) Governance Framework. 

The content within this repository provides guidance and examples for adopting Chaos Engineering across an AWS organization in a secure and controlled manner. It focuses on implementing governance through Service Control Policies (SCPs) to manage AWS Fault Injection Service (FIS) permissions at scale. 

## Overview 
In large organizations or secure environments, application teams are typically provided with pre-approval to use AWS FIS for experimentation. At scale, this can be accomplished using Service Control Policies (SCPs) to create guardrails around FIS usage while enabling teams to validate their application's resilience. ### What are Service Control Policies (SCPs)? SCPs are JSON policies that specify the maximum permissions for an organization or organizational unit (OU) in AWS Organizations. If you enable all features in an organization, you can apply SCPs to any or all of your accounts. The SCP limits permissions for entities in member accounts, including each AWS account root user. For more information about Organizations and SCPs, see [Service control policies](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps.html) in the AWS Organizations User Guide.

## Repository Contents 
This repository provides example Service Control Policies (SCPs) and IAM configurations to help implement governance and security controls when using AWS FIS across your AWS Organization. The examples cover: 
1. Single Account Strategy  - Basic SCP examples for limiting FIS actions  - Standard IAM roles for FIS execution  - Network-specific permission examples 
2. Multi-Account Strategy  - Centralized orchestration patterns  - Cross-account role configurations  - Standardized role definitions 
3. Cross-Region Connectivity Scenarios with a decentralized approach when running Multi-region experiment with a multi-account strategy - Transit Gateway permission examples

## Key Components

### Standard Roles 
The framework defines three key roles: 
1. **AWS-FIS-Experiment-Orchestrator**: Creates and manages experiment templates 
2. **AWS-FIS-Experiment-Executor**: Executes specific fault injection actions 
3. **AWS-FIS-Experiment-Target**: Enables cross-account experiment execution 

### Implementation Strategies Two main approaches are supported: 
1. **Centralized Management** - Single orchestrator account - Centralized experiment catalog  - Standardized governance 
2. **Decentralized Management** - Account-level autonomy  - Team-specific implementations  - Local governance control ## Usage The examples contained in this repository will need to be modified prior to use in your environment. Consider the following when implementing: - Your organization's security requirements - Existing network architecture - Account structure and OU hierarchy - Required fault injection scenarios - Compliance and governance needs

## Documentation 
For detailed implementation guidance, refer to our blog series: 1. [Scaling AWS FIS Across Your Organization - Part 1](INSERT_LINK) 2. [Multi-Account Strategies - Part 2](INSERT_LINK) 3. [Cross-Region Connectivity Scenarios - Part 3](INSERT_LINK) 

## Contributing 
We welcome contributions to improve these examples and documentation. Please submit pull requests or create issues for any enhancements. ## License This library is licensed under the MIT-0 License. See the LICENSE file.
