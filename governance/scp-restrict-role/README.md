# AWS Fault Injection Service - Service Control Policy Examples

This repository provides example Service Control Policies (SCPs) to help you implement governance and security controls when using AWS Fault Injection Service (FIS) in your AWS Organization.

These examples will need to modified prior to use for your own environment.

## Overview

In order to ensure we are limiting the fault isolation bounds we are testing, we need to ensure are IAM permissions are least privileged to only the resources we want to test. The content in this folder provide examples of:
- Restricting the modification of the IAM permissions assigned to a FIS experiment 
- Restricting the modification to VPCs or networking resources. 

These policies have conditions to allow an admin and automation to still be allowed to take these actions. 

## Security Considerations

- Always test SCPs in a non-production environment first
- Monitor policy changes using AWS CloudTrail
- Regularly review and update policies as your requirements evolve
- Ensure you maintain access to emergency response procedures

## Prerequisites

- An AWS Organization with [SCPs enabled](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps.html)
- Understanding of [AWS FIS concepts](https://docs.aws.amazon.com/fis/latest/userguide/what-is.html)
- Creation of AWS-FIS-Experiment-Executor IAM Role. This role is only allowed to execute certain actions required to inject faults into your workload and is assigned directly to experiments. This role should only be assumed by the AWS FIS service.

## Implementation Guide

1. Review the example SCPs in this repository
2. Modify the policies according to your organization's requirements
3. Test the SCPs in a non-production environment
4. Apply the SCPs to your organization using the AWS Organizations console or API
