# MySQL RDS Load Test and Failover - Session Notes

## Project Overview
This project tests MySQL RDS Multi-AZ failover behavior under high CPU load to evaluate:
- Failover time under stress
- Application connectivity during failover
- Database performance before, during, and after failover
- Overall resilience of RDS Multi-AZ configuration

## Environment Setup (Completed)
- **CloudFormation stack**: `mysql-rds-loadtest-failover`
- **VPC**: Custom VPC with public and private subnets across two AZs
- **RDS Instance**: 
  - Endpoint: `mysql-rds-loadtest-failover-rdsinstance-7lnsqbmo9icy.ck3zxsrxdcgk.us-east-1.rds.amazonaws.com`
  - Type: MySQL 8.0.41, db.t3.small
  - Configuration: Multi-AZ (Primary: us-east-1b, Secondary: us-east-1a)
  - Username: `admin`
  - Password: `DBPassword!`
  - Database: `testdb`
- **EC2 Instance**: 
  - ID: `i-06180e4904ccf5c08`
  - Type: Amazon Linux 2
  - Location: Private subnet with SSM access
- **SSM Documents**:
  - Original: `mysql-rds-loadtest-failover-SSMLoadTestDocument-zDiY3BrTEbQs`
  - Enhanced: `MySQL-RDS-HighLoad-Test`
- **FIS Experiment Template**: `EXT29t3zUsJVrxzt8`
- **Custom Scripts**:
  - High load test: `/tmp/high_load_test.sh` on EC2 instance
  - CPU monitoring: `/tmp/monitor_cpu.sh` on EC2 instance

## Load Test Development
1. **Initial Test (Baseline)**:
   - Concurrency: 10 connections
   - CPU utilization: ~37.5%
   - Duration: 5 minutes (300 seconds)

2. **Enhanced Test (Final)**:
   - Concurrency: 25 connections
   - CPU utilization: 97-98%
   - Duration: 60 minutes (3600 seconds)
   - Workload: Complex queries, table joins, continuous data insertion

3. **Load Test Script Details**:
   ```bash
   # Key operations in high_load_test.sh:
   # - Creates database and table if they don't exist
   # - Runs multiple worker processes (configurable)
   # - Each worker performs:
   #   - INSERT operations with random data
   #   - Complex SELECT queries with grouping and filtering
   #   - JOIN operations that force table scans
   #   - Continuous execution until duration expires
   ```

## Failover Test Results (2025-05-05)
- **Timeline**:
  - Test start: ~23:44:00 UTC
  - High load achieved: ~23:47:00 UTC (97-98% CPU)
  - Failover triggered: 23:59:21 UTC
  - Failover completed: 23:59:46 UTC
  - **Total failover time: 25 seconds**

- **CPU Utilization Pattern**:
  - Before failover: 97-99%
  - During failover: 3-8%
  - After failover: Climbing from ~16% back toward high utilization

- **Database Status After Failover**:
  - Endpoint: Unchanged (DNS continuity maintained)
  - New primary hostname: ip-172-17-5-173
  - Read/write status: Fully writable (innodb_read_only = 0)
  - Connections: Maintained after brief interruption

- **Events Timeline**:
  ```
  23:59:21 UTC - "Multi-AZ instance failover started"
  23:59:35 UTC - "DB instance restarted"
  23:59:39 UTC - "DB instance restarted"
  23:59:46 UTC - "Multi-AZ instance failover completed"
  23:59:46 UTC - "The user requested a failover of the DB instance"
  ```

## Current System State (2025-05-06)
- All load test processes have been stopped (confirmed)
- RDS instance is in "available" state
- CPU utilization has returned to normal levels (3-7%)
- FIS experiment has completed successfully
- RDS instance is still configured for Multi-AZ with primary in us-east-1b and secondary in us-east-1a
- All test scripts and documents remain in place for future testing

## Repository File Management
### Essential Files (Updated with Improvements):
1. **`cloudformation.yaml`** - Core CloudFormation template for infrastructure
2. **`README.md`** - Updated with performance characteristics, monitoring commands, and key findings
3. **`fis-experiment-template.json`** - Updated with concurrency of 25 and improved description
4. **`ssm-loadtest-mysql-shell-script.yaml`** - Completely rewritten with improved load testing approach

### Temporary Files (Consider Removing Later):
1. **`session-notes.md`** - This working document with testing notes
2. **`fis-experiment-template-filled.json`** - Version with actual resource ARNs
3. **`temp-loadtest-document.json`** - Temporary load test document with hardcoded values
4. **`temp-loadtest-document.yaml`** - YAML version of temporary document

## File Updates Summary (2025-05-06)
1. **`fis-experiment-template.json` Changes**:
   - Updated concurrency from 10 to 25 for higher CPU load
   - Changed description to specify "high CPU load test"
   - Maintained all placeholder variables for template usage

2. **`ssm-loadtest-mysql-shell-script.yaml` Changes**:
   - Completely rewrote the load test script based on our high-performance version
   - Added proper parameters with improved defaults (concurrency of 25)
   - Implemented worker process model for better CPU load generation
   - Added complex queries and table joins that force table scans
   - Added connection monitoring during the test

3. **`README.md` Changes**:
   - Added "Performance Characteristics" section with our test findings
   - Documented the observed failover time of ~25 seconds
   - Added CPU utilization metrics for different concurrency settings
   - Expanded monitoring section with detailed commands
   - Added "Manual Testing" section with commands
   - Added "Key Findings" section summarizing test results

## Command Reference

### Load Testing
**Start high CPU load test**:
```bash
aws ssm send-command \
  --instance-ids i-06180e4904ccf5c08 \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["nohup /tmp/high_load_test.sh \"DBPassword!\" \"admin\" \"testdb\" \"25\" \"3600\" \"mysql-rds-loadtest-failover-rdsinstance-7lnsqbmo9icy.ck3zxsrxdcgk.us-east-1.rds.amazonaws.com\" > /tmp/load_test.log 2>&1 &", "echo \"Load test started\""]'
```

**Stop load test**:
```bash
aws ssm send-command \
  --instance-ids i-06180e4904ccf5c08 \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["pkill -f high_load_test.sh", "pkill -f monitor_cpu.sh", "echo \"Load test stopped\""]'
```

### Failover Testing
**Manually trigger failover**:
```bash
aws rds reboot-db-instance \
  --db-instance-identifier mysql-rds-loadtest-failover-rdsinstance-7lnsqbmo9icy \
  --force-failover \
  --region us-east-1
```

**Run FIS experiment** (includes load test + failover):
```bash
aws fis start-experiment --experiment-template-id EXT29t3zUsJVrxzt8
```

### Monitoring
**Check RDS CPU utilization**:
```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/RDS \
  --metric-name CPUUtilization \
  --dimensions Name=DBInstanceIdentifier,Value=mysql-rds-loadtest-failover-rdsinstance-7lnsqbmo9icy \
  --start-time $(date -u -d '5 minutes ago' '+%Y-%m-%dT%H:%M:%SZ') \
  --end-time $(date -u '+%Y-%m-%dT%H:%M:%SZ') \
  --period 60 \
  --statistics Average \
  --region us-east-1
```

**Check RDS events** (including failover events):
```bash
aws rds describe-events \
  --source-identifier mysql-rds-loadtest-failover-rdsinstance-7lnsqbmo9icy \
  --source-type db-instance \
  --start-time $(date -u -d '1 hour ago' '+%Y-%m-%dT%H:%M:%SZ') \
  --region us-east-1
```

**Check database connectivity and status**:
```bash
aws ssm send-command \
  --instance-ids i-06180e4904ccf5c08 \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["mysql -h mysql-rds-loadtest-failover-rdsinstance-7lnsqbmo9icy.ck3zxsrxdcgk.us-east-1.rds.amazonaws.com -u admin -pDBPassword! -e \"SELECT @@hostname, @@port, @@innodb_read_only;\" testdb"]'
```

**View FIS experiment logs**:
```bash
aws logs get-log-events \
  --log-group-name /aws/fis/experiment \
  --log-stream-name <experiment-id> \
  --region us-east-1
```

### Cleanup
```bash
aws cloudformation delete-stack --stack-name mysql-rds-loadtest-failover
```

## Key Findings and Observations
1. **Failover Performance**: Multi-AZ failover completed in 25 seconds under extreme CPU load (97-98%)
2. **Connection Handling**: Applications experience ~25 seconds of downtime during failover
3. **DNS Continuity**: The endpoint DNS name remained the same, providing connection continuity
4. **Post-Failover State**: Database returned to normal operation with no read-only mode
5. **Load Handling**: The t3.small instance handled high load but reached CPU saturation
6. **Resilience**: The Multi-AZ configuration successfully maintained data integrity during failover

## Potential Next Steps
1. Test failover with different instance sizes to compare recovery times
2. Implement connection pooling to measure impact on application availability
3. Test with different database engines (PostgreSQL, MariaDB)
4. Implement and test automated client-side retry mechanisms
5. Compare performance with Aurora MySQL's failover capabilities
6. Test with different types of workloads (read-heavy vs. write-heavy)

## References
- [RDS Multi-AZ Documentation](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.MultiAZ.html)
- [AWS FIS Documentation](https://docs.aws.amazon.com/fis/latest/userguide/what-is.html)
- [MySQL Performance Best Practices](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_BestPractices.MySQL.html)
