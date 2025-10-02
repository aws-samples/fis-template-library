# ElastiCache Redis Primary Node Reboot

This experiment reboots the primary Redis node to test application resilience and recovery mechanisms.

## What It Does

1. **Identifies Primary Node**: Dynamically finds the current primary node using `NodeGroups` → `NodeGroupMembers` → `CurrentRole`
2. **Reboots Primary**: Executes `reboot_cache_cluster` on the primary node
3. **Monitors Recovery**: Tracks node status from "Rebooting cache cluster nodes" to "Available"
4. **Measures Timeline**: Reports exact recovery time

## Expected Behavior

- **Duration**: 1-3 minutes for small instances (t3.micro)
- **Node Status**: Changes from "Available" → "Rebooting cache cluster nodes" → "Available"
- **No Failover**: Brief reboot doesn't trigger automatic failover
- **Application Impact**: Brief connection disruption during reboot

## Prerequisites

1. **Redis Cluster**: Multi-AZ with `AutomaticFailover=enabled`
2. **Cluster Tag**: Must have `FIS-Ready=True` tag
3. **IAM Roles**: Both FIS and SSM execution roles configured

## Files

- `elasticache-redis-primary-node-reboot-automation.yaml` - SSM automation document (2 steps)
- `elasticache-redis-primary-node-reboot-experiment-template.json` - FIS experiment template
- `elasticache-redis-primary-node-reboot-fis-role-iam-policy.json` - FIS role permissions
- `elasticache-node-primary-node-reboot-ssm-role-iam-policy.json` - SSM role permissions
- `fis-iam-trust-relationship.json` - FIS role trust policy
- `ssm-iam-trust-relationship.json` - SSM role trust policy

## Setup

### 1. Create IAM Roles
```bash
# Create SSM role
aws iam create-role --role-name ElastiCache-SSM-Automation-Role \
  --assume-role-policy-document file://ssm-iam-trust-relationship.json

aws iam put-role-policy --role-name ElastiCache-SSM-Automation-Role \
  --policy-name ElastiCacheAutomationPolicy \
  --policy-document file://elasticache-node-primary-node-reboot-ssm-role-iam-policy.json

# Create FIS role
aws iam create-role --role-name ElastiCache-FIS-Role \
  --assume-role-policy-document file://fis-iam-trust-relationship.json

aws iam put-role-policy --role-name ElastiCache-FIS-Role \
  --policy-name ElastiCacheFISPolicy \
  --policy-document file://elasticache-redis-primary-node-reboot-fis-role-iam-policy.json
```

### 2. Deploy SSM Document
```bash
aws ssm create-document \
  --name "ElastiCache-Redis-Primary-Node-Reboot" \
  --document-type "Automation" \
  --document-format "YAML" \
  --content file://elasticache-redis-primary-node-reboot-automation.yaml
```

### 3. Tag Redis Cluster
```bash
aws elasticache add-tags-to-resource \
  --resource-name "arn:aws:elasticache:region:account:replicationgroup:cluster-id" \
  --tags Key=FIS-Ready,Value=True
```

### 4. Create FIS Experiment
```bash
# Update account ID in template first
aws fis create-experiment-template \
  --cli-input-json file://elasticache-redis-primary-node-reboot-experiment-template.json
```

## Usage

### Via FIS (Recommended)
```bash
aws fis start-experiment --experiment-template-id <template-id>
```

### Direct SSM Execution
```bash
aws ssm start-automation-execution \
  --document-name "ElastiCache-Redis-Primary-Node-Reboot" \
  --parameters "tagKey=FIS-Ready,tagValue=True,region=us-east-1,AutomationAssumeRole=arn:aws:iam::ACCOUNT:role/ElastiCache-SSM-Automation-Role"
```

## Automation Steps

1. **triggerNodeFailover**: Identifies and reboots primary Redis node
2. **monitorPrimaryNodeRecovery**: Monitors node status until "Available"

## Test Results

- ✅ **Primary Detection**: Correctly identifies current primary node
- ✅ **Reboot Execution**: Successfully reboots primary node
- ✅ **Recovery Monitoring**: Tracks status changes with timestamps
- ✅ **FIS Integration**: Works through complete FIS → SSM workflow

## Limitations

- **No True Failover**: Reboot is too brief to trigger automatic failover
- **Brief Outage**: Only tests short connection disruptions
- **Single Node**: Only affects the primary node, replicas remain available

## For True Failover Testing

Consider using connection-level failures instead:
- Security group isolation
- Network ACL blocking
- Manual failover via `modify-replication-group`

## Current Status

✅ **Working** - Successfully reboots primary node and monitors recovery
