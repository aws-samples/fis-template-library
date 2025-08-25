# AWS Fault Injection Service Experiment: Aurora Cluster CPU Overload and Failover

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Description

This experiment simulates CPU overload on an Aurora PostgreSQL cluster and then initiates a failover to test the resilience of your database infrastructure under stress conditions.

## Hypothesis

When high CPU load occurs on an Aurora cluster followed by a subsequent failover, the system will restore normal operation with minimal disruption, and the application's functionality will remain largely unaffected. The automatic recovery process will complete within minutes, and the system's request processing capability will maintain continuity at near 100% efficiency after the failover completes.

## Prerequisites

Before running this experiment, ensure that:

1. You have an Aurora PostgreSQL cluster tagged with `FIS-Ready=True`
2. **You have an EC2 instance tagged with `FIS-Ready=True` that serves as the load generator**
   - This instance must have network connectivity to your Aurora cluster
   - The instance must have the SSM Agent installed and running
   - The instance requires appropriate IAM permissions to execute SSM documents
   - The instance will execute CPU-intensive database queries against the Aurora cluster
3. The Aurora cluster is configured for Multi-AZ deployment with writer and reader instances
4. You have created the required IAM role with the provided policy document
5. You have deployed the SSM document for load testing
6. You have configured appropriate CloudWatch monitoring and alarms

## Architecture Overview

This experiment uses the following components:

- **Aurora PostgreSQL Cluster**: The target database that will experience CPU load and failover
- **EC2 Load Generator Instance**: Executes the SSM document to generate database load
- **SSM Document**: Contains the load testing scripts that create CPU-intensive queries
- **FIS Experiment**: Orchestrates the load generation and failover sequence

**Critical**: The EC2 instance acts as the load generator and must be able to connect to your Aurora cluster. The SSM document will be executed on this instance, not directly on the Aurora cluster.

## EC2 Instance Setup

Your EC2 instance must meet these requirements:

1. **Network Access**: Security groups must allow outbound connections to Aurora on port 5432
2. **PostgreSQL Client**: Install `postgresql-client` or equivalent for database connectivity
3. **SSM Agent**: Ensure SSM Agent is installed and the instance appears in Systems Manager
4. **IAM Role**: Attach an IAM role with `AmazonSSMManagedInstanceCore` policy
5. **Tagging**: Tag the instance with `FIS-Ready=True`

Test connectivity before running the experiment:
```bash
psql -h your-aurora-endpoint -U your-username -d your-database -c "SELECT 1;"
```

## ⚠️ Database Impact Warning

**IMPORTANT**: This experiment will create test tables in your Aurora PostgreSQL database:

### Tables Created:
- `load_test_users` - User records with status and timestamps
- `load_test_transactions` - Transaction records with foreign key relationships

### Impact:
- Tables will persist after the experiment completes
- Test data will be inserted during load testing
- No existing data will be modified or deleted
- Tables use `IF NOT EXISTS` clauses to avoid conflicts
- Indexes will be created for performance testing

### Cleanup:
If you need to remove the test tables after the experiment, you can manually drop them:
```sql
DROP TABLE IF EXISTS load_test_transactions;
DROP TABLE IF EXISTS load_test_users;
```

## How it works

This experiment simulates a high CPU load scenario followed by an Aurora DB cluster failover:

1. **Baseline establishment**: 5-minute delay to establish baseline metrics
2. **CPU load generation**: SSM document executes CPU-intensive queries on the Aurora cluster
3. **Failover initiation**: After the delay, promotes an Aurora Replica to be the primary writer
4. **Impact observation**: Load test continues to observe failover impact on performance

The experiment targets resources with the `FIS-Ready=True` tag for safety and control.

## Observability and stop conditions

This template does not include stop conditions by default. You should add CloudWatch alarms based on your specific operational metrics to automatically halt the experiment if critical thresholds are breached.

## Files included

- `aurora-cluster-failover-template.json`: Main FIS experiment template
- `aurora-cluster-failover-iam-policy.json`: Required IAM permissions
- `aurora-cluster-failover-ssm-template.json`: SSM document for load testing
- `fis-iam-trust-relationship.json`: IAM trust policy for FIS service

## Next steps

1. Review and customize the experiment parameters for your environment
2. Set up CloudWatch monitoring and create appropriate alarms
3. Add stop conditions based on your operational metrics
4. Test the experiment in a non-production environment first
5. Create a CloudWatch dashboard to visualize experiment effects

## Import experiment

You can import the JSON experiment template into your AWS account via CLI or AWS CDK. For step-by-step instructions, see the [fis-template-library-tooling](https://github.com/aws-samples/fis-template-library-tooling) repository.
