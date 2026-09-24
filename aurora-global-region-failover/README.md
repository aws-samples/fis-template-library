# Aurora Global Database Regional Failover

This experiment performs Aurora Global Database regional failover/switchover to test disaster recovery procedures and measure RTO/RPO.

## Hypothesis

When an Aurora Global Database performs a regional failover/switchover, the secondary Region cluster is promoted to primary and the application resumes read/write operations against the new primary within a recovery time objective (RTO) of 5 minutes, with a recovery point objective (RPO) of zero for a planned switchover (no data loss). A CloudWatch alarm on application error rate or database connection failures returns to its OK state within 5 minutes of the promotion completing.

## Prerequisites

- Aurora Global Database with primary and secondary clusters
- Global cluster tagged with `FIS-Ready: True`
- IAM roles for FIS and SSM automation

## Failover Types

- **Switchover** (default): Planned operation with no data loss for maintenance or testing
- **Failover**: Emergency operation allowing data loss for disaster recovery

## Files

- `aurora-global-region-failover-automation.yaml` - SSM automation document
- `aurora-global-region-failover-experiment-template.json` - FIS experiment template
- `aurora-global-region-failover-fis-role-iam-policy.json` - IAM policy for FIS role
- `aurora-global-region-failover-ssm-automation-role-iam-policy.json` - IAM policy for SSM role
- `fis-iam-trust-relationship.json` - Trust relationship for FIS role
- `ssm-iam-trust-relationship.json` - Trust relationship for SSM role

## Setup

1. Create IAM roles:
   ```bash
   aws iam create-role --role-name <FIS-ROLE-NAME> --assume-role-policy-document file://fis-iam-trust-relationship.json
   aws iam put-role-policy --role-name <FIS-ROLE-NAME> --policy-name <FIS-POLICY-NAME> --policy-document file://aurora-global-region-failover-fis-role-iam-policy.json
   
   aws iam create-role --role-name <SSM-ROLE-NAME> --assume-role-policy-document file://ssm-iam-trust-relationship.json
   aws iam put-role-policy --role-name <SSM-ROLE-NAME> --policy-name <SSM-POLICY-NAME> --policy-document file://aurora-global-region-failover-ssm-automation-role-iam-policy.json
   ```

2. Create SSM automation document:
   ```bash
   aws ssm create-document --name aurora-global-region-failover-automation --document-type Automation --content file://aurora-global-region-failover-automation.yaml --document-format YAML
   ```

3. Update experiment template with your values and create:
   ```bash
   # Edit aurora-global-region-failover-experiment-template.json with your account/region/cluster details
   aws fis create-experiment-template --cli-input-json file://aurora-global-region-failover-experiment-template.json
   ```

## Parameters

- `globalClusterIdentifier`: Aurora Global Database cluster identifier (required)
- `failoverType`: "switchover" for planned operations or "failover" for emergency with data loss (default: "switchover")
- `AutomationAssumeRole`: IAM role ARN for automation execution (required)

## Usage

Run the FIS experiment to perform a managed failover/switchover of the Aurora Global Database:

```bash
aws fis start-experiment --experiment-template-id <TEMPLATE-ID>
```

The experiment will automatically detect the secondary cluster and promote it to primary based on the configured failover type.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until the failover/switchover automation completes.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or 
business metric requiring an immediate end of the fault injection. This 
template makes no assumptions about your application and the relevant metrics 
and does not include stop conditions by default.

## Next Steps
As you adapt this scenario to your needs, we recommend:
1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to the Aurora Global Database and the applications that depend on it.
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of the regional failover/switchover.
4. Adding a stop condition tied to the alarm to automatically halt the experiment if critical thresholds are breached.
5. Confirming your recovery time objective (RTO) and recovery point objective (RPO) targets against the observed failover/switchover behavior.

## Import Experiment
You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
