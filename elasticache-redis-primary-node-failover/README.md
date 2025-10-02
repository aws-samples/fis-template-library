# ElastiCache Redis Primary Node Failover

This experiment forces a Redis primary node failover to test automatic failover mechanisms and application resilience.

## What It Does

1. **Identifies Current Primary**: Finds the current primary node and selects a replica to promote
2. **Forces Failover**: Uses `modify_replication_group` to promote a replica to primary
3. **Monitors Completion**: Tracks cluster status until failover completes
4. **Verifies Result**: Confirms the new primary is active

## Expected Behavior

- **Duration**: 1-3 minutes for complete failover
- **Cluster Status**: Changes from "available" → "modifying" → "available"
- **True Failover**: Actually changes which node is primary
- **Application Impact**: Brief connection disruption during DNS update

## Prerequisites

1. **Redis Cluster**: Multi-AZ with `AutomaticFailover=enabled`
2. **Multiple Nodes**: At least 1 primary + 1 replica
3. **Cluster Tag**: Must have `FIS-Ready=True` tag
4. **IAM Roles**: Both FIS and SSM execution roles configured

## Key Differences from Reboot Test

- ✅ **True Failover**: Actually promotes replica to primary
- ✅ **Role Change**: Primary and replica roles swap
- ✅ **DNS Update**: Master endpoint points to new primary
- ✅ **Longer Duration**: Takes 1-3 minutes vs 20 seconds for reboot

## Automation Steps

1. **triggerPrimaryFailover**: Forces failover by promoting replica
2. **monitorFailoverCompletion**: Monitors until new primary is active

## Current Status

🚧 **New** - Ready for testing and validation
