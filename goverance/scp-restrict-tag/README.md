# AWS Fault Injection Service - Service Control Policy Examples

This repository provides example Service Control Policies (SCPs) to help you implement governance and security controls when using AWS Fault Injection Service (FIS) in your AWS Organization.

These examples will need to modified prior to use for your own environment.

## Overview

The file scp-restrict-tag.json assists in implementing tag restrictions using Service Control Policies (SCPs) is crucial for managing the AWS FIS Cross Region Scenario in a multi-account environment. Adopting a tag strategy for resilience testing enables you to::

- Enforce Tagging Standards: Ensure only approved tags are used for FIS experiments, maintaining clarity and control.
- Enhance Security: Prevent unauthorized users from targeting critical resources by using restricted tags.
- Compliance and Governance: Control which resources can be included in FIS experiments based on their tags.
- Scalable Control: Manage tag usage across multiple accounts without configuring policies individually in each account.

## Security Considerations

- Always test SCPs in a non-production environment first
- Monitor policy changes using AWS CloudTrail
- Regularly review and update policies as your requirements evolve
- Ensure you maintain access to emergency response procedures

## Prerequisites

- An AWS Organization with [SCPs enabled](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps.html)
- Understanding of [AWS FIS concepts](https://docs.aws.amazon.com/fis/latest/userguide/what-is.html)


## Implementation Guide

1. Review the example SCPs in this repository
2. Modify the policies according to your organization's requirements
3. Test the SCPs in a non-production environment
4. Apply the SCPs to your organization using the AWS Organizations console or API
