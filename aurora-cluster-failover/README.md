# AWS Fault Injection Service Experiment: Failover Aurora Cluster

This AWS Fault Injection Service (FIS) experiment is designed to perform a failover operation on Amazon Aurora clusters that have the tag `FIS-Ready=True`. The experiment utilizes the `aws:rds:failover-db-cluster` action provided by FIS.

## Hypothesis

Failover of an Aurora Cluster between the reader and writer instance may cause requests to fail for a brief period of time, but requests will automatically recover, and the application will continue to function as normal after the failover.

## Expected Aurora Cluster Configuration

This experiment expects the targeted Aurora clusters to have the following configuration:

1. **Multi-AZ Deployment**: The Aurora cluster should be deployed across multiple Availability Zones (Multi-AZ) to ensure high availability.
2. **Writer and Reader Instances**: The cluster should have at least one writer instance and one reader instance. The failover operation will promote a reader instance to become the new writer instance.
3. **Replication Configuration**: The cluster should have replication properly configured, allowing for seamless failover between writer and reader instances.

## Experiment Configuration

The experiment configuration is defined in a JSON file, which includes the following sections:

### Targets

The `Clusters-Target-1` target selects all Amazon Aurora clusters that have the tag `FIS-Ready=True`. The `resourceType` is set to `aws:rds:cluster`, and the `selectionMode` is set to `ALL`.

### Actions

The `failover-aurora-cluster` action is configured to perform the `aws:rds:failover-db-cluster` operation on the selected Aurora clusters. This action will trigger a failover event for the specified clusters.

### Stop Conditions

The experiment has a single stop condition that is set to `none`. This means that the experiment will not automatically stop based on any specific conditions.

### IAM Role 

The iam-policy.json file within this directory has been provided as an example. This policy includes the following permissions:

1. **rds:FailoverDBCluster** and **rds:DescribeDBClusters**: These permissions allow the IAM role to initiate and describe the failover operation on Amazon Aurora clusters.

2. **logs:CreateLogGroup**, **logs:CreateLogStream**, and **logs:PutLogEvents**: These permissions allow the IAM role to create and write logs to Amazon CloudWatch Logs for monitoring and logging purposes during the fault injection experiment.

3. **fis:***: This permission grants full access to the AWS Fault Injection Simulator service, allowing the IAM role to create, manage, and run fault injection experiments.

Note that the `Resource` field in the policy specifies the ARNs or resource patterns that the permissions apply to. In this example, the policy grants permissions to:

- All Amazon Aurora clusters in all AWS regions and accounts (`arn:aws:rds:*:*:cluster:*`).
- CloudWatch Log groups with the prefix `/aws/fis/` in all AWS regions and accounts (`arn:aws:logs:*:*:log-group:/aws/fis/*`).
- All resources for the AWS Fault Injection Simulator service (`*`).

You can further customize the `Resource` field to restrict the permissions to specific resources or resource patterns as needed.

To use this policy, you can create a new IAM policy in the AWS Management Console or through AWS CLI/AWS SDKs, and attach it to the IAM role specified in the `roleArn` field of your fault injection service experiment.

### Experiment Options

The experiment is set to target a single AWS account (`accountTargeting: "single-account"`), and it will fail if no targets are found (`emptyTargetResolutionMode: "fail"`).

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment and perform the failover operation on the targeted Aurora clusters.
2. The IAM role specified in the `roleArn` field has the required permissions to perform the failover operation.
3. The Aurora clusters you want to target have the `FIS-Ready=True` tag.
4. The targeted Aurora clusters are configured for Multi-AZ deployment with writer and reader instances, and proper replication is set up.

## Usage

To run this experiment, you can use the AWS Fault Injection Simulator service or the AWS CLI. Follow the appropriate documentation or guidelines provided by AWS for executing FIS experiments.

## Disclaimer

This experiment is designed to trigger a failover event on Aurora clusters, which may cause temporary disruption or downtime for the affected clusters. It is recommended to thoroughly test and validate this experiment in a non-production environment before running it in a production setting.