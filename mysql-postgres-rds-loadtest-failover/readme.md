teps to build a Fault Injection Simulator experiment template:

1. Set up the AWS environment:
   - Launch EC2 instances for your database servers (PostgreSQL and MySQL)
   - Configure security groups and network access

2. Install and configure the databases:
   ```bash
   # For PostgreSQL
   sudo yum install postgresql postgresql-server
   sudo postgresql-setup initdb
   sudo systemctl start postgresql
   sudo systemctl enable postgresql

   # For MySQL
   sudo yum install mysql mysql-server
   sudo systemctl start mysqld
   sudo systemctl enable mysqld
   ```

3. Create a script to run the load test:
   ```bash
   #!/bin/bash

   # PostgreSQL load test
   pgbench -i -s 50 your_database_name
   pgbench -c 10 -j 2 -t 1000 your_database_name

   # MySQL load test
   sysbench oltp_read_write --table-size=1000000 --mysql-db=your_database_name --mysql-user=your_username --mysql-password=your_password prepare
   sysbench oltp_read_write --table-size=1000000 --threads=10 --time=60 --max-requests=0 --mysql-db=your_database_name --mysql-user=your_username --mysql-password=your_password run

   # CPU-intensive query
   psql -c "WITH RECURSIVE fibonacci(n, fib_n, next_fib_n) AS (
       SELECT 1, 0::numeric, 1::numeric
       UNION ALL
       SELECT n + 1, next_fib_n, fib_n + next_fib_n
       FROM fibonacci
       WHERE n < 1000000
   )
   SELECT n, fib_n FROM fibonacci;"

   # Memory-intensive query
   mysql -e "WITH RECURSIVE t(n) AS (
       SELECT 1
       UNION ALL
       SELECT n+1 FROM t WHERE n < 1000000
   )
   SELECT string_agg(CAST(n AS TEXT), ',') FROM t;"
   ```

4. Create an AWS FIS experiment template:
   ```json
   {
     "description": "Database Load Test Experiment",
     "targets": {
       "Instances": [
         {
           "resourceType": "aws:ec2:instance",
           "resourceArns": [
             "arn:aws:ec2:us-west-2:123456789012:instance/i-1234567890abcdef0"
           ],
           "selectionMode": "ALL"
         }
       ]
     },
     "actions": {
       "RunLoadTest": {
         "actionId": "aws:ssm:send-command",
         "parameters": {
           "documentArn": "arn:aws:ssm:us-west-2:123456789012:document/RunLoadTest",
           "duration": "PT5M"
         },
         "targets": {
           "Instances": "Instances"
         }
       }
     },
     "stopConditions": [
       {
         "source": "aws:cloudwatch:alarm",
         "value": "arn:aws:cloudwatch:us-west-2:123456789012:alarm:HighCPUAlarm"
       }
     ],
     "roleArn": "arn:aws:iam::123456789012:role/FISExperimentRole"
   }
   ```

5. Create an SSM document for the load test:
   ```yaml
   ---
   schemaVersion: '2.2'
   description: 'Run database load test'
   parameters: {}
   mainSteps:
   - action: 'aws:runShellScript'
     name: 'runLoadTest'
     inputs:
       timeoutSeconds: '600'
       runCommand:
       - |
         #!/bin/bash
         # Insert the load test script here
   ```

6. Set up CloudWatch alarms for monitoring:
   ```bash
   aws cloudwatch put-metric-alarm \
       --alarm-name HighCPUAlarm \
       --alarm-description "Alarm when CPU exceeds 90%" \
       --metric-name CPUUtilization \
       --namespace AWS/EC2 \
       --statistic Average \
       --period 300 \
       --threshold 90 \
       --comparison-operator GreaterThanThreshold \
       --dimensions Name=InstanceId,Value=i-1234567890abcdef0 \
       --evaluation-periods 2 \
       --alarm-actions arn:aws:sns:us-west-2:123456789012:MyTopic
   ```

7. Run the FIS experiment:
   ```bash
   aws fis start-experiment --experiment-template-id your-template-id
   ```

This setup creates an FIS experiment that runs the load test on specified EC2 instances, monitors CPU usage, and stops if a high CPU alarm is triggered. You can expand this template to include more complex scenarios and additional fault injections as needed.