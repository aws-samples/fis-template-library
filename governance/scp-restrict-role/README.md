# AWS Fault Injection Service - Service Control Policy Examples

This repository provides example Service Control Policies (SCPs) to help you implement governance and security controls when using AWS Fault Injection Service (FIS) in your AWS Organization.

These examples will need to modified prior to use for your own environment.

## Overview
When implementing chaos engineering at scale, it's crucial to establish proper isolation boundaries for experiments. These SCPs help ensure least-privileged access by:
- Restricting network resource modifications to specific roles
- Protecting FIS IAM role configurations from unauthorized changes
- Enabling administrative and automation workflows while maintaining security

These policies have conditions to allow an admin and automation to still be allowed to take these actions. 

## SCP Examples

### Network Resource Protection SCP

This SCP restricts network-related modifications to authorized roles only.

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowAccessToASpecificRole",
            "Effect": "Deny",
            "Action": [
                "ec2:CreateNetworkAcl",
                "ec2:CreateNetworkAclEntry",
                "ec2:DeleteNetworkAcl",
                "ec2:CreateTags",
                "ec2:DescribeNetworkAcls",
                "ec2:DescribeManagedPrefixLists",
                "ec2:DescribeSubnets",
                "ec2:DescribeVpcs",
                "ec2:ReplaceNetworkAclAssociation",
                "ec2:GetManagedPrefixListEntries"
            ],
            "Resource": "*",
            "Condition": {
                "ArnEquals": {
                    "aws:PrincipalArn": [
                        "arn:aws:iam::*:role/AWS-FIS-Experiment-Executor",
                        "arn:aws:iam::<YOUR AWS ACCOUNT>:role/CustomerAutomationRole",
                        "arn:aws:iam::<YOUR AWS ACCOUNT>:role/CustomerNetworkAdminRole"
                    ]
                }
            }
        }
    ]
}
```

### FIS Role Protection SCP

This SCP prevents unauthorized modifications to FIS IAM roles.

To prevent changes or unwanted use of the AWS-FIS-Experiment-Executor role customer can implement an SCP policy that will prevent any principles within the organization from changing the role configuration (example: adding additional permissions or editing the trust policy) unless specifically allowed in the policy. 

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "DenyAccessToASpecificRole",
            "Effect": "Deny",
            "Action": [
                "iam:AttachRolePolicy",
                "iam:DeleteRole",
                "iam:DeleteRolePermissionsBoundary",
                "iam:DeleteRolePolicy",
                "iam:DetachRolePolicy",
                "iam:PutRolePermissionsBoundary",
                "iam:PutRolePolicy",
                "iam:UpdateAssumeRolePolicy",
                "iam:UpdateRole",
                "iam:UpdateRoleDescription"
            ],
            "Resource": [
                "arn:aws:iam::*:role/AWS-FIS-Experiment-Executor"
            ],
            "Condition": {
                "ArnNotEquals": {
                "aws:PrincipalArn":[
                    "arn:aws:iam::<YOUR AWS ACCOUNT>:role/CustomerRoleAdminRole",
                    "arn:aws:iam::<YOUR AWS ACCOUNT>:role/CustomerAutomationRole"
                ]
                }
            }   
        }
    ]
}
```

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
