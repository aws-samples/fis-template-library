# Aurora Global Database Regional Failover

This experiment performs Aurora Global Database regional failover/switchover to test disaster recovery procedures and measure RTO/RPO.

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
