# AWS Fault Injection Service Experiment: Amazon SQS VPC Endpoint Availability Zone Impairment

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

If Amazon SQS requests from one Availability Zone fail while requests from the other Availability Zones keep working, the application should detect the failure in that Availability Zone, keep serving from the healthy Availability Zones, and recover on its own when SQS requests succeed again, and:

- Your monitoring should show SQS errors for the impaired Availability Zone only, within the time your alarms allow.
- Clients in the other Availability Zones should keep sending and receiving messages with no errors and no added latency. In each of six test runs, the client in the healthy Availability Zone had no errors from the start of the experiment until two minutes after the deny statement was removed (487 to 997 calls per run), and its slowest call in that time took 167 ms.
- Messages the impaired Availability Zone could not send should be retried, buffered or rejected in the way your application is designed to, without loss of messages SQS already accepted.
- After the experiment ends, or is stopped, clients in the impaired Availability Zone should succeed again without a restart. In testing, the last denied request came 62 to 142 seconds after the deny statement was removed, and every request after it succeeded for as long as it was measured, at least 3.5 minutes in each run.

### What does this enable me to verify?

* Your monitoring can see SQS failures that affect one Availability Zone. Amazon SQS metrics in CloudWatch have a single dimension, the queue name ([SQS metric dimensions](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-available-cloudwatch-metrics.html#sqs-metric-dimensions)), so this needs application metrics or logs that record the Availability Zone.
* Your application isolates an Availability Zone whose dependency fails, for example through health checks or a zonal shift, rather than retrying the failing requests indefinitely.
* Producers retry or buffer messages they could not send, and consumers in the healthy Availability Zones take over the work.
* Clients recover without manual action once SQS requests succeed again.

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to create the IAM roles, the SSM Automation document and the FIS experiment template, and to run the experiment. Example IAM policy documents and trust policies for the FIS and SSM Automation roles are provided (`sqs-vpc-endpoint-az-impairment-fis-role-iam-policy.json`, `sqs-vpc-endpoint-az-impairment-ssm-automation-role-iam-policy.json`, `fis-iam-trust-relationship.json`, `ssm-iam-trust-relationship.json`); replace the `<YOUR ...>` placeholders in them. The trust policies let FIS and Systems Manager assume the roles only for experiments and automation runs in your account and Region. Besides the EC2 permissions, the SSM automation role can read the status of automation executions (`ssm:GetAutomationExecution`), which the automation uses to check that it hasn't been cancelled before it changes an endpoint policy.
2. You have created the SSM Automation Document from the sample provided (`sqs-vpc-endpoint-az-impairment-automation.yaml`) with the name `sqs-vpc-endpoint-az-impairment-automation`.
3. You have created the FIS Experiment Template from the sample provided (`sqs-vpc-endpoint-az-impairment-experiment-template.json`) and replaced all placeholder values (`<YOUR ...>`). `<YOUR TARGET AZ>` is the Availability Zone to impair, as a name (for example `us-east-1a`) or an ID (for example `use1-az1`).
4. Your clients reach SQS through an SQS interface VPC endpoint (`com.amazonaws.<YOUR REGION>.sqs`, or `com.amazonaws.<YOUR REGION>.sqs-fips`), and the endpoint has the `FIS-Ready=True` tag. The SSM automation role's `ec2:ModifyVpcEndpoint` permission is scoped with a `FIS-Ready=True` resource-tag condition, so an untagged endpoint is both skipped by discovery and refused the change. Clients that reach SQS over its public endpoints, for example through a NAT gateway, are not affected, because the deny statement is part of the endpoint policy.
5. The clients you want to impair run in subnets in the target Availability Zone, in the same VPC as the endpoint. The deny statement matches the source IP address of each request against the CIDR blocks of every subnet in that Availability Zone in the endpoint's VPC, and an endpoint has one policy for all its network interfaces, so it does not matter which of them a request reaches.
6. You have tagged only the endpoints you want to impair. The automation impairs every available SQS interface endpoint in the Region that carries the tag, and fails without changing anything if an endpoint that carries the tag is not in the `available` state.
7. Each target endpoint policy has room for the deny statement. An endpoint policy can't exceed 20,480 characters ([endpoint policies](https://docs.aws.amazon.com/vpc/latest/privatelink/vpc-endpoints-access.html)). In testing, the statement added 242 characters for one subnet; it grows with the number of subnets. The automation checks the size before it changes any endpoint, and changes nothing if a policy would be too large.
8. You have appropriate monitoring and observability in place to track the impact of the experiment.
9. The experiment was tested in `us-east-2` on one SQS interface endpoint with private DNS and network interfaces in three Availability Zones, with the default full-access endpoint policy and with a custom policy of two statements, and with the stop cases described in Stop Conditions. Two AWS Lambda functions in the endpoint's VPC, one in `us-east-2a` (the target) and one in `us-east-2b`, sent `SendMessage` requests about twice a second to `sqs.us-east-2.amazonaws.com` with the AWS SDK for Python (boto3). Other SQS API actions, the endpoint-specific DNS names, IPv6 clients, FIPS endpoints, several tagged endpoints, shared VPC subnets, clients in peered VPCs and other Regions weren't tested.

## How it works

This experiment makes SQS requests fail for clients in one Availability Zone. FIS has no action for SQS ([FIS actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html)), so FIS runs an SSM Automation document with the `aws:ssm:start-automation-execution` action. The document adds a deny statement to the endpoint policy of each tagged SQS interface endpoint, waits for the duration, and removes the statement again:

1. **FindTargets**: Finds the available SQS interface endpoints that carry the tag, and the CIDR blocks of the subnets in the target Availability Zone in each endpoint's VPC (IPv4, and IPv6 blocks that are associated). Nothing is changed in this step, and the run fails if no endpoint or no subnet is found.
2. **ApplyDeny**: Builds the new policy for every endpoint first, then adds this statement to each, keeping every other statement:

    ```json
    {
        "Sid": "FISDenySqsFromAvailabilityZone",
        "Effect": "Deny",
        "Principal": "*",
        "Action": "sqs:*",
        "Resource": "*",
        "Condition": {
            "IpAddress": {"aws:VpcSourceIp": ["<CIDR blocks of the target Availability Zone's subnets>"]},
            "StringEquals": {"aws:SourceVpc": "<the endpoint's VPC ID>"}
        }
    }
    ```

    Systems Manager does not stop a running script when the automation is cancelled. In a test, a script that was cancelled during a 20-second wait still made its change about 20 seconds after the cancel, 15 seconds after the cancellation steps had finished. So before each policy change, ApplyDeny checks that its automation is still running, and changes nothing more if it isn't.

3. **WaitForDuration**: Keeps the statement in place for `Duration` (default `PT10M`). The experiment template's `maxDuration` (`PT20M`) must be longer than `Duration` plus a few minutes: in testing, a `PT6M` run took 7 minutes 37 seconds from start to end.
4. **RemoveDeny**: Reads each endpoint policy, removes only the statement with that `Sid`, and keeps checking every 3 seconds for 30 seconds, removing the statement again if it reappears. That covers a policy change ApplyDeny had already started when the run was cancelled. This step runs at the end of the duration, when the automation is cancelled (which is what stopping the FIS experiment does), and when ApplyDeny or WaitForDuration fails. Because it reads the policy again, a change someone else makes to the policy during the run is kept, unless the change lands between RemoveDeny reading and writing the policy (this wasn't tested). If the statement is still present at the end, the step fails and names the endpoints to fix by hand.

Clients in the target Availability Zone receive `AccessDenied` for every SQS request through the endpoint. In testing, 99% of the denied `SendMessage` calls returned within 141 ms (median 104 ms) and the slowest took 1.1 seconds, so the client sees a fast error rather than a timeout. The test client allowed one retry (botocore `max_attempts` set to 1); other retry settings weren't tested.

The effect does not start or end at the moment the policy changes. After you update an endpoint policy, it can take a few minutes for the changes to take effect ([update a VPC endpoint policy](https://docs.aws.amazon.com/vpc/latest/privatelink/vpc-endpoints-access.html#update-vpc-endpoint-policy)). In five test runs, timed from the moment the endpoint policy changed and rounded to the nearest second:

| Run | Statement in place | First request denied | Every request denied from | Last request denied after the statement was removed |
|---|---|---|---|---|
| Full `PT6M` duration, default endpoint policy | 373 seconds | 116 seconds | 131 seconds | 92 seconds |
| Stopped, default endpoint policy | 257 seconds | 118 seconds | 164 seconds | 83 seconds |
| Stopped, custom endpoint policy | 258 seconds | 125 seconds | 168 seconds | 62 seconds |
| Full `PT6M` duration, default endpoint policy (repeat) | 373 seconds | 145 seconds | 201 seconds | 119 seconds |
| Stopped, default endpoint policy (repeat) | 263 seconds | 170 seconds | 170 seconds | 142 seconds |

In most runs, requests were allowed and denied in turn between the first denied request and the time every request was denied, and again after the statement was removed. The delays varied from run to run; the longest wait for every request to be denied came in a run that started 54 minutes after the endpoint policy had last changed. Choose a `Duration` about 3 minutes longer than the full outage you want to test: with the default `PT10M`, expect about 7 to 8 minutes in which every request from the Availability Zone is denied.

### Why an endpoint policy

The FIS action `aws:network:disrupt-connectivity` with `scope` set to `prefix-list` can also block traffic from one Availability Zone's subnets to the endpoint's IP addresses, and is the better choice if you want clients to see timeouts instead of errors. It works through network ACLs, and network ACLs don't filter traffic between addresses in the same subnet. With private DNS, the SQS hostname resolves to the endpoint's IP addresses in every Availability Zone, so a client whose subnet also holds one of the endpoint's network interfaces keeps reaching SQS through it. In testing, all of that client's requests succeeded during the fault. With a new connection for each request, they took a median of 2.1 seconds, against 132 ms for a client in another Availability Zone, because the client tried the blocked addresses first; with reused connections, 4 requests took 2.1 to 4.1 seconds and the median stayed at 7 ms. Blocking worked once the endpoint's network interface in the target Availability Zone was moved to a subnet of its own. The endpoint policy runs above were done with that network interface in the clients' subnet, the layout in which the network ACL left requests working.

To verify the experiment is working properly, check that the statement is in the endpoint policy and watch your clients' SQS errors:

```bash
aws ec2 describe-vpc-endpoints --vpc-endpoint-ids <YOUR ENDPOINT ID> \
  --query 'VpcEndpoints[0].PolicyDocument' --output text
```

### What else is affected

- Every SQS request through the tagged endpoints from the target Availability Zone's subnets is denied, from any application, not only from your test clients. This includes AWS Lambda functions attached to those subnets.
- SQS requests that don't go through the tagged endpoints are not affected, including requests to the public SQS endpoints and through endpoints that don't carry the tag.
- Other AWS services that share the endpoint's subnets are not affected, because the statement only applies to the SQS endpoint.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It ends when the automation does: when the duration ends, or when a step fails. In testing, a run whose tag matched no endpoint failed in FindTargets with `No SQS interface VPC endpoint has the tag ... Nothing was changed.`, and neither the endpoint policy nor the clients were affected.

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

Stopping the experiment cancels the automation, and the automation's `onCancel` setting sends it to the RemoveDeny step. Automation runs the cancellation workflow for a maximum of two minutes ([onCancel](https://docs.aws.amazon.com/systems-manager/latest/userguide/automation-actions.html)); for one endpoint, RemoveDeny took about 40 seconds, most of it the 30 seconds of checks. RemoveDeny handles the endpoints one after another, so with many tagged endpoints it takes longer and could run past the two minutes (several endpoints weren't tested). Don't remove the tag from an endpoint while an experiment is running: the SSM automation role can only change tagged endpoints, so RemoveDeny couldn't remove the statement (this wasn't tested). In testing, every way of ending the run left the endpoint policy the same as before it, and CloudTrail shows no change by the automation after its last removal:

| How the run was ended | What happened |
|---|---|
| FIS stop while the fault was in effect, default policy and custom policy | FIS reported the experiment stopped within a second. The statement was removed about 4 seconds after the stop request and RemoveDeny finished about 41 seconds after it. The custom policy's two statements were kept. |
| Stop condition: the alarm went to `ALARM` while the fault was in effect | FIS reported `Experiment halted by stop condition.` 1.6 seconds after the alarm changed state, and the statement was removed 5 seconds after it. |
| FIS stop while FindTargets was running | The run ended before anything was changed. |
| FIS stop as ApplyDeny started (two runs) | ApplyDeny made no change and RemoveDeny found nothing to remove. |
| FIS stop 3.5 seconds into ApplyDeny, as it made its change | The statement was added and removed again 4 seconds later. |
| The statement put back while RemoveDeny was checking, as a late ApplyDeny change would | RemoveDeny removed it again within 3 seconds. |
| Automation cancelled directly in Systems Manager (`StopAutomationExecution`, default type `Cancel`) | RemoveDeny ran and the statement was removed 3 seconds after the cancel. FIS marked the experiment failed with `Automation execution completed with status: Cancelling.` |
| `StopAutomationExecution` with type `Complete` | Systems Manager refused it (`Completion request is only supported in Interactive mode`), and the run continued and ended normally. |

Requests from the impaired Availability Zone were allowed again 62 to 142 seconds after the statement was removed in the runs where the fault had taken effect.

Because FIS reports a stopped experiment before RemoveDeny has finished, FIS does not show whether the statement was removed. Check the RemoveDeny step of the automation execution in the Systems Manager console, or the endpoint policy with the command in How it works. If RemoveDeny failed, remove the statement with the `Sid` `FISDenySqsFromAvailabilityZone` yourself, for example in the Amazon VPC console under **Endpoints**, **Actions**, **Manage policy**.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case. The default tag is `FIS-Ready=True`. The SSM automation role's `ec2:ModifyVpcEndpoint` permission requires that tag on the endpoint, so if you change `TagKey` or `TagValue` in the experiment template's `documentParameters`, change the condition in `sqs-vpc-endpoint-az-impairment-ssm-automation-role-iam-policy.json` to match; otherwise the automation finds the endpoint but the change is refused. The permission also allows other changes to a tagged endpoint, such as its subnets or private DNS setting; the automation only changes the policy.
2. Identifying business metrics tied to the work your application sends through SQS, such as send and receive errors and messages processed, recorded by your application per Availability Zone, and the queue's `ApproximateAgeOfOldestMessage`.
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of SQS failures in one Availability Zone.
4. Adding a stop condition tied to the alarm to automatically halt the experiment if critical thresholds are breached.
5. Choosing a `Duration` that allows for the few minutes the endpoint policy takes to apply, as described in How it works.
6. Running the experiment against each Availability Zone your application uses, one at a time.
7. If you add steps to the automation that change resources, having each one check that the automation is still running before it makes a change, as ApplyDeny does, because a cancelled script keeps running.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
