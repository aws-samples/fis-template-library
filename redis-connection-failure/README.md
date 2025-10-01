# Redis Connection Failure Resilience Testing

This experiment simulates Redis connection failures to test client-side circuit breaker behavior and application resilience when Redis becomes unavailable.

## Example Hypothesis

When Redis connections are disrupted, applications should gracefully handle the failure through circuit breaker mechanisms within 30 seconds. Client retry storms should be prevented, and applications should continue operating in degraded mode. Once Redis connectivity is restored, normal operations should resume within 60 seconds.

### What does this enable me to verify?

* Redis client circuit breaker functionality works correctly
* Applications handle Redis unavailability gracefully without cascading failures
* Client-side retry logic doesn't create amplification effects
* Monitoring and alerting detect Redis connectivity issues
* Recovery mechanisms work when Redis becomes available again
* Dependent services (like console tools) can operate independently

## How it works

This experiment simulates Redis connection failures by modifying ElastiCache security groups to block connections for a specified duration:

1. **Connection Disruption**: Removes security group rules to block Redis access
2. **Wait**: Maintains disruption for specified duration to test resilience
3. **Restoration**: Restores security group rules to resume normal connectivity

## Prerequisites

Before running this experiment, ensure that:

1. You have the roles created for FIS and SSM Automation to use
2. Your ElastiCache Redis clusters have the "FIS-Ready":"True" tag
3. **Your applications implement proper Redis client circuit breakers**
4. You have monitoring for Redis connectivity and application health
5. You have appropriate observability in place to track the impact

## Experiment Files

* `redis-connection-failure-automation.yaml` - SSM Automation Document
* `redis-connection-failure-experiment-template.json` - FIS Experiment Template  
* `redis-connection-failure-fis-role-iam-policy.json` - IAM policy for FIS role
* `redis-connection-failure-ssm-role-iam-policy.json` - IAM policy for SSM role
* `fis-iam-trust-relationship.json` - Trust policy for FIS role
* `ssm-iam-trust-relationship.json` - Trust policy for SSM role

## Testing Verification

To verify the experiment works correctly:

```bash
# Monitor Redis connectivity
redis-cli -h <redis-endpoint> ping

# Check application health endpoints
curl -I https://<your-app>/health

# Monitor circuit breaker metrics
# (depends on your monitoring setup)
```

During the experiment, you should observe:
- Circuit breakers activating when Redis becomes unavailable
- Applications continuing to serve requests (possibly with degraded functionality)
- No retry storms or cascading failures
- Proper alerting and monitoring activation
