# AWS Fault Injection Service Experiment: DynamoDB Region Impairment

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

If reads and writes on my DynamoDB global table are denied in the target Region for 10 minutes while replication to and from that Region is paused, the share of failed user requests should not exceed `<your threshold>`, an alarm should notify the on-call team within 5 minutes, and the application should serve reads and writes from a replica in another Region within 2 minutes. After access is restored and replication resumes, the application should return to normal cross-Region operation within 5 minutes.

The hypothesis is false if any of these doesn't hold: the error rate your application measures in the target Region exceeds your threshold for longer than your failover target, no alarm reaches the on-call team within 5 minutes of the first refused request, or writes made in the other Region during the run don't appear in the target Region within 5 minutes of the end of the pause. For the fault to cause the behavior, your application must have a path to fail over to a replica Region, and your alarm must watch an application metric such as the error rate of DynamoDB calls in the target Region. In testing, the measured numbers didn't match this hypothesis in two places. DynamoDB applied the deny gradually: some requests still succeeded now and then until 2.4 to 4.4 minutes after the deny was added (in one run, only PartiQL requests after 1.4 minutes), so in the runs that kept the deny for 10 minutes or more, every request was refused for only about 6.5 to 8.1 minutes (see Eventual consistency). And replication didn't always catch up within 5 minutes: when runs on the same table followed each other closely, writes reached the target Region up to 21 minutes after the pause ended, and in a run on its own, two writes made in the other Region during the pause were still missing in the target Region 4.9 minutes after the pause ended and had arrived about 6 minutes after it (see Replication).

### What does this enable me to verify?

* Appropriate customer experience metrics and observability of DynamoDB global tables is in place (were you able to detect there was a problem?)
* Alarms are configured correctly (were the right people notified and/or automations triggered?)
* Your app gracefully fails over to the healthy region and customers can continue using the application
* Your circuit breaker (if any) works as expected for regional failures
* Recovery controls (if any) work as expected when the region comes back online
* Cross-region replication monitoring and alerting functions correctly

## Prerequisites

Before running this experiment, ensure that:

1. You have created the IAM role for FIS from `dynamodb-region-impairment-fis-role-iam-policy.json` and `fis-iam-trust-relationship.json`, and the IAM role for SSM Automation from `dynamodb-region-impairment-ssm-automation-role-iam-policy.json` and `ssm-iam-trust-relationship.json`.
2. You have created an SSM Automation document named `DynamoDB-Region-Impairment` from `dynamodb-region-impairment-automation.yaml`. The FIS role policy and the template use this name.
3. You have created the FIS experiment template from `dynamodb-region-impairment-experiment-template.json`, and replaced `<YOUR REGION>`, `<YOUR AWS ACCOUNT>`, `<YOUR TABLE NAME>`, `<YOUR ROLE NAME>` and `<YOUR SSM AUTOMATION ROLE NAME>` in the template, in both policy files and in both trust files.
4. The DynamoDB global table (version 2019.11.21) you want to target has the `FIS-Ready=True` tag on its replica in the target Region. The pause action targets every global table with this tag in the Region, but the SSM document blocks only the table named in `tableName`, and fails before it changes anything if that table doesn't have the tag. Tag only that table. To block more tables, add one SSM action per table, add each table's ARN to the `Resource` of the `AllowReadTable` and `AllowTablePolicyChanges` statements in `dynamodb-region-impairment-ssm-automation-role-iam-policy.json` (as a list), and add each table's ARN and its stream ARN (`table/<name>/stream/*`) to the `AllowPauseReplicationOnTargetTable` statement in `dynamodb-region-impairment-fis-role-iam-policy.json`. The FIS role can change only the policies of the tables and streams that statement names, so if another table carries the tag, the pause action is denied on it and the experiment fails.
5. Only the people who may run fault experiments can add the `FIS-Ready` tag to DynamoDB tables: the tag selects the pause action's targets, and the SSM document changes only a table that has it. Neither role's policy needs the tag, because in an earlier test DynamoDB refused every policy write from a role whose permission to write that policy depended on a resource tag ("The new resource policy will not allow you to update the resource policy in the future"). Instead, each role can change only the policies of the table its policy names: the FIS role that table's and its stream's, the SSM role that table's.
6. You have appropriate monitoring and observability in place to track the impact of the experiment.
7. To run the README's check and manual removal commands, you have AWS CLI version 2 (the commands use `--no-cli-pager`) and python3.
8. The table is a multi-Region eventually consistent (MREC) global table. Multi-Region strong consistency (MRSC) global tables aren't supported: the pause action needs `dynamodb:InjectError` for them ([actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html)), and the FIS role doesn't grant it.
9. Tested scope: MREC global tables with one replica, on-demand capacity, a stream, a sort key, a global and a local secondary index, with and without a resource policy before the run, in eu-west-3 with the replica in eu-north-1, and in eu-west-2 with the replica in eu-central-1. More than one replica Region has not been tested.

## How it works

This experiment simulates a regional outage of one DynamoDB table's data plane by combining two actions that start together: it refuses reads and writes on the table in the target Region, and pauses replication to and from that Region. Control-plane calls, backups, exports, the table's stream and other tables keep working (see What else is affected).

### Actions

**1. Native FIS action (`aws:dynamodb:global-table-pause-replication`)**
- Pauses replication into and out of the `FIS-Ready` global tables in the Region, by adding deny statements to each table's and stream's resource policy. The FIS role can change only the policies of the table and stream it names, so if another table has the tag, the pause is denied on it and the experiment fails (Prerequisites 4). The statement IDs start with `DoNotModifyFisDynamoDbPauseReplication` and contain the experiment ID.
- Duration: 15 minutes, so the pause outlasts the deny even with the slowest setup the automation allows.
- FIS gives its statements an expiry time, and removes them when the action ends or the experiment is stopped. In testing, with the 15-minute pause, the expiry was 22 minutes after FIS wrote them.

**2. Custom SSM Automation (`blockDynamoDBAccess`)**
- Denies these actions on the named table and each of its indexes in the target Region: `GetItem`, `BatchGetItem`, `Query`, `Scan`, `PutItem`, `UpdateItem`, `DeleteItem`, `BatchWriteItem`, `ConditionCheckItem` and the four PartiQL actions. [Transactions are authorized by the same actions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis-iam.html), so they are refused too.
- Denies every principal except the DynamoDB replication service-linked role, so replication stays under the pause action's control.
- Duration: 10 minutes (the `duration` parameter, PT1M to PT11H50M).

The automation runs these steps:

1. `waitForFISAction` waits 10 seconds.
2. `applyDenyPolicy` reads the table's tags and fails unless it has `FIS-Ready=True`. It then waits up to 40 seconds for a pause statement from FIS whose own expiry is still in the future, and fails if none appears, so the block doesn't start before the pause. It waits 15 more seconds, because DynamoDB blocks policy updates for 15 seconds after each update. It then adds one statement, `FISDenyAccess` followed by the automation execution ID without hyphens, and keeps every other statement, retrying until 90 seconds after the step started. It writes the statement only into a version of the policy that still holds an unexpired pause statement, with `ExpectedRevisionId`, so DynamoDB accepts the write only while that version is current: once FIS has removed its pause statements, the deny can't be added. The statement carries a `DateLessThan` condition on `aws:CurrentTime`, set to the time the step builds it (at most about 40 seconds before the write) plus `duration` plus 2 minutes, so it stops applying at that time even if nothing removes it. Before each read and write, the step checks its own automation execution, and adds nothing more once SSM reports it as being cancelled. If the step ends without success after it has sent a write, for example because the execution was cancelled or a reply was lost, it removes its statement if it's there and keeps reading until 10 reads in a row, 5 seconds apart, don't show it, for up to 70 seconds; the error says whether it confirmed that. In testing, SSM didn't stop a cancelled step's script: the script's own status check stopped it, within 10 seconds of the stop when no write was in flight (about 15 seconds in earlier tests; see Stop Conditions).
3. `waitForDuration` waits for `duration`.
4. `checkDenyPresent` fails the run if this run's statement was removed before the planned end, so a fault cut short isn't reported as a success. It also fails if 3 reads of the policy all fail.
5. `cleanupPolicy` removes only this run's statement and keeps every other one. It deletes the policy only when no other statement is left. It ends after 10 reads in a row, 5 seconds apart, without the statement, and fails within its 115-second timeout if it can't confirm that, with the statement and its expiry in the error.

Steps 2 to 4 go to `cleanupPolicy` when they fail. When the experiment is stopped during steps 2 to 4, or while `cleanupPolicy` runs, `cleanupPolicyOnCancel` runs instead. It has the same script, run in its stop mode: it first waits 15 seconds, so that FIS's removal of its pause statements can land before its own first write (DynamoDB blocks policy updates for 15 seconds after each update), then removes this run's statement. It ends once 6 reads in a row, 5 seconds apart, show neither this run's statement nor an unexpired FIS pause statement. If FIS writes back a copy of the policy that still holds the deny while the step is reading, it removes the deny again. After the step ends, nothing in the document watches the policy; in testing, every FIS write to the table's and the stream's policies carried `ExpectedRevisionId`, so DynamoDB would reject a copy read before the deny was removed. If an unexpired pause statement is still there, it keeps reading until about 80 seconds after it started. It then ends with Success if this run's statement wasn't in the last 6 reads, and its output says whether the pause statement was still there and when it stops applying (the latest expiry, or "unreadable" if one can't be read). Replication stays paused until FIS removes that statement, at the latest until its expiry (in testing, 22 minutes after FIS wrote it, about 7 minutes after the planned end of the pause action). The step fails if it can't confirm that this run's statement is gone. It reads only the table's policy, not the stream's.

### Timeline
Times are from the experiment start, with the default parameters.
- **About T+12s**: FIS writes its pause statements to the table's policy and to the stream's policy, and the automation starts. FIS shows the pause action's start about 20 seconds later (T+33s in testing).
- **About T+40s to T+80s**: The automation adds its deny statement, after the FIS statements are in place (T+40s to T+41s in testing, and T+46s when the status check right before the write failed once and the step tried again). With the slowest setup the automation allows, about T+2m25s.
- **About T+11m10s to T+11m50s**: The automation removes its deny statement (T+11m09s to T+11m10s in testing).
- **About T+12m40s to T+13m20s**: The deny statement's expiry, at the latest about T+14m. It matters only if no cleanup step removed the statement.
- **About T+15m30s**: The pause action ends, and FIS removes its pause statements (T+15m33s to T+15m34s in testing).

The deny always expires before the pause ends. This leaves a recovery window of about 4 minutes, between the removal of the deny and the end of the pause, where the application can reach the table but replication is still paused (in testing, 257 to 263 seconds from the first request that worked again to the end of the pause). In testing, PartiQL requests kept being refused until 87 to 94 seconds after the removal, so for PartiQL the window was about 3 minutes (169 to 176 seconds).

**Eventual consistency**: When you attach a resource-based policy with the `PutResourcePolicy` API, [the policy application is eventually consistent](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_PutResourcePolicy.html), so the first refused requests may come some time after the statement is added, and some requests may succeed after it. In testing, the first refused request came 4 seconds to 3 minutes after the deny was added, and the first refusal of each operation type up to 3.8 minutes after it. Some requests still succeeded now and then until 2.4 to 4.4 minutes after the deny was added (in one run, only PartiQL requests after 1.4 minutes); after that, every request was refused until the deny was removed or expired. A resource policy already on the table before the run made no consistent difference. In three runs stopped 5 to 11 seconds after the deny was added, no request was refused at all; the stop path removed the deny 23 to 29 seconds after it was added. These numbers, and the other numbers about requests and replication in this README, come from a client that sent one request a second per operation type and Region, with 1-second timeouts and no retries, in 25 runs that added the deny (6 of them normal runs) in two pairs of Regions. A client with another request rate or other timeouts would measure other numbers. To give the deny more time, raise `duration` in the SSM action's `documentParameters`, and raise the pause action's `duration` and the SSM action's `maxDuration` by the same amount. This keeps the recovery window, and the automation keeps the same time to clean up before `maxDuration`. FIS accepts a `maxDuration` of at most 12 hours ([actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html)), and `maxDuration` must be `duration` plus 8 minutes, so the document accepts `duration` up to PT11H50M and rejects longer values.

**Replication**: The [FIS actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html) says replication may continue for up to 5 minutes after the pause starts. In testing, writes from the other Region kept reaching the target Region for 3.2 to 4.6 minutes after the pause started in the normal runs (2.3 to 4.7 minutes over every run that held the pause past 5 minutes), replication in each direction was back 4 seconds to about 2 minutes after the pause ended, and in the 9 runs checked no acknowledged write was lost. Writes made during the pause could take longer to arrive: in one run, two writes made in the other Region during the pause were still missing in the target Region 4.9 minutes after the pause ended and had arrived about 6 minutes after it. When runs on the same table followed each other closely, writes made at the start of one run reached the target Region 21 minutes after its pause ended, after the next run's pause. After a stop, writes from the target Region reached the other Region again 25 seconds to 2 minutes after the stop, and about 2.5 minutes after it when FIS's removal came 98 seconds after the stop (see Stop Conditions). After stops in the first 90 seconds of the pause, writes from the other Region never stopped reaching the target Region; after stops 3.7 to 12.6 minutes into the run, they reached it again 18 to 94 seconds after the stop.

**Policy updates**: Both actions change the same resource policy, and [`GetResourcePolicy` is eventually consistent](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_PutResourcePolicy.html). The automation writes with `ExpectedRevisionId`, so it can't overwrite a newer version of the policy. It retries every rejected write until 90 seconds after the step started, except `AccessDeniedException`, `ValidationException`, `ResourceNotFoundException`, `UnrecognizedClientException` and `MissingAuthenticationTokenException`, because DynamoDB doesn't document which error it returns while it blocks policy updates after a recent update. In testing, it returned `ThrottlingException` ("An unknown error occurred" in CloudTrail for FIS's writes, and "… modified within the previous 15000 milliseconds …" to a removal run by hand), which the automation retries.

To check that the experiment is set up and working, you can use the AWS CLI version 2 to try operations on the targeted table:

```bash
# Test application access (should fail during impairment)
watch -n 5 'aws dynamodb put-item --table-name my-global-table --item "{\"id\":{\"S\":\"fis-readme-test-us-east-1\"},\"message\":{\"S\":\"$(date +%s)\"}}" --region us-east-1 --no-cli-pager'

# Test reads (should also fail during impairment)
watch -n 5 'aws dynamodb get-item --table-name my-global-table --key "{\"id\":{\"S\":\"fis-readme-test-us-east-1\"}}" --region us-east-1 --no-cli-pager'

# Test failover region (should continue working)
watch -n 5 'aws dynamodb put-item --table-name my-global-table --item "{\"id\":{\"S\":\"fis-readme-test-us-west-2\"},\"message\":{\"S\":\"$(date +%s)\"}}" --region us-west-2 --no-cli-pager'
```

During the impairment you should see `AccessDeniedException` errors in us-east-1, while us-west-2 operations continue normally. Replace `my-global-table` with your table's name, `id` with your table's partition key attribute (and add your sort key attribute to each key if the table has one), and us-east-1 and us-west-2 with your target Region and a replica Region. Because the policy application is eventually consistent, the first errors may not appear right away.

The commands write two items, `fis-readme-test-us-east-1` and `fis-readme-test-us-west-2`, which replicate to every Region. Stop the `watch` commands, and remove the items at least 10 minutes after their last write, so that a write still replicating can't bring an item back (wait longer if another run pauses replication of the same table soon after; see Replication):

```bash
for k in fis-readme-test-us-east-1 fis-readme-test-us-west-2; do aws dynamodb delete-item --table-name my-global-table --key "{\"id\":{\"S\":\"$k\"}}" --region us-west-2 --no-cli-pager; done
```

### What else is affected

- The deny has `"Principal": "*"`, so it refuses every caller of the table and its indexes in the target Region: every application, user and role, and AWS services that read or write the table's items on your behalf. Only the DynamoDB replication service-linked role is exempt.
- The deny doesn't cover control-plane calls such as `DescribeTable` or `UpdateTable`, backups and exports, or the table's stream: stream readers such as AWS Lambda triggers keep reading, and see no new records from writes in the target Region while they are refused. Records of writes replicated from other Regions can still appear until the pause takes effect (see Replication).
- The pause targets every global table with the `FIS-Ready=True` tag in the Region, and their streams. The FIS role can write only the named table's and its stream's policies, so if another table has the tag, the pause is denied on it and the experiment fails (Prerequisites 4).
- While replication is paused, adding or removing a replica of a paused table may fail ([PutResourcePolicy](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_PutResourcePolicy.html)).
- If AWS CloudFormation or the AWS CDK manages the table's resource policy, CloudFormation doesn't show either action's statements as drift, because [resource-based policies don't support drift detection](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/rbac-considerations.html). A stack update during the run that changes the policy in the template overwrites the policy and removes the statements, which ends the fault early (`checkDenyPresent` then fails the run) or removes statements cleanup expects to find. A stack update that doesn't change the policy leaves it alone (same page).
- Running two experiments on the same table at the same time is not supported. In testing, FIS refused the second experiment's pause action ("Unable to pause replication for all target DynamoDB tables. The targeted DynamoDB table is already being targeted by another active AWS FIS experiment."), so that experiment failed and its automation was cancelled before it added anything. Each run adds and removes only its own deny statement, but a run of the document without a pause action of its own, such as one started outside FIS, may accept another experiment's unexpired pause statement as its own.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until both actions complete (about 15.5 minutes by default, and at most about 18 minutes, the SSM action's `maxDuration`).

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

What a stop does, by phase:
- **In the automation's first 10 seconds** (`waitForFISAction`, about T+12s to T+22s): FIS removes its pause statements, and the automation is cancelled before it changes anything.
- **While `applyDenyPolicy` runs**: FIS removes its pause statements, and `cleanupPolicyOnCancel` removes the deny if it was added, or confirms that it isn't there, which takes at least 40 seconds. If `applyDenyPolicy` keeps running after the cancel, it can't add the deny once FIS's removal has landed, adds nothing more once SSM reports the cancel, and removes its statement if it had already sent a write. SSM reports a stopping execution as `Cancelling` ([automation statuses](https://docs.aws.amazon.com/systems-manager/latest/userguide/automation-statuses.html)). In testing, SSM didn't stop the script: its own status check stopped it before any write, within 10 seconds of the stop (about 15 seconds in earlier tests). In a test version that held the write for 10 seconds after its status check, the write went out 4 seconds after the stop and DynamoDB rejected it, because FIS had already removed the policy version it named; the script then kept reading the policy until 54 seconds after the stop and added nothing.
- **While the deny is in place**: FIS removes its pause statements, and `cleanupPolicyOnCancel` removes the deny about 17 seconds after the stop (17 to 18 seconds in testing). In testing, operations other than PartiQL worked again 6 to 31 seconds after the stop (PutItem was refused once more 38 seconds after the stop in one run and 197 seconds after it in another), and PartiQL 40 to 261 seconds after it. SSM records `applyDenyPolicy`'s end about 22 seconds after the deny is added, so a stop in that time shows that step as `Cancelled`, with the deny in place; the stop path removes it the same way. Automation runs this cancellation path for [at most two minutes](https://docs.aws.amazon.com/systems-manager/latest/userguide/automation-actions.html), and `cleanupPolicyOnCancel` has a 115-second timeout. In testing, a test version of the step whose script held until about 105 seconds after it started ended `Cancelled` 122 seconds after the stop, with its output lost; the shipped script's slowest case ends about 110 seconds after it starts.
- **While `cleanupPolicy` runs**: `cleanupPolicyOnCancel` runs the same removal in its stop mode.
- **After the automation has ended** (about T+12m15s to T+15m30s): FIS removes its pause statements. The automation has already ended, so nothing else changes.

DynamoDB blocks policy updates for 15 seconds after each one, so a stop shortly after a policy write can delay FIS's removal of its pause statements. In testing, after stops 5 to 11 seconds after the deny was added, 6 seconds after `cleanupPolicy` removed it, and 3.5 seconds after FIS's own write, FIS showed the pause action as `failed` ("Failed to restore replication for all target tables. Received an error from DynamoDB. Try again later."), and its removal from the table's policy landed 33 to 98 seconds after the stop. The longest was after the stop that followed FIS's own write, which delayed the removal from the stream's policy too; after the other stops, FIS's removal from the stream's policy landed 2 to 3 seconds after the stop. In earlier tests, after a stop in the same second as FIS's own write, FIS showed `failed` with "Unexpected state on action end. Fault statement in one of the resource policy was modified outside of the experiment." In every case the experiment showed `stopped`, and FIS's pause statements stayed until FIS removed them. After a stop 14 seconds after the deny was added, FIS's removal landed 2 seconds after the stop, and the pause action showed `stopped`. To check after a stop whether FIS's pause statements are still on the table's and the stream's policies:

```bash
TABLE_ARN=$(aws dynamodb describe-table --table-name my-global-table --region us-east-1 --query 'Table.TableArn' --output text)
STREAM_ARN=$(aws dynamodb describe-table --table-name my-global-table --region us-east-1 --query 'Table.LatestStreamArn' --output text)
for ARN in "$TABLE_ARN" "$STREAM_ARN"; do
  if OUT=$(aws dynamodb get-resource-policy --resource-arn "$ARN" --region us-east-1 --query Policy --output text 2>&1); then
    SIDS=$(echo "$OUT" | grep -o 'DoNotModifyFisDynamoDbPauseReplication[A-Za-z0-9]*' | sort -u)
    echo "$ARN: ${SIDS:-no FIS pause statement}"
  elif echo "$OUT" | grep -q PolicyNotFoundException; then
    echo "$ARN: no policy, so no FIS pause statement"
  else
    echo "$ARN: check failed: $OUT"
  fi
done
```

`GetResourcePolicy` is eventually consistent, so run the check again a few seconds later before you rely on it.

A stopped experiment can't be resumed; [start a new one](https://docs.aws.amazon.com/fis/latest/userguide/stop-experiment.html). If cleanup fails, the automation ends Failed (in earlier tests, also after a stop, while FIS showed the experiment as stopped), and the error names this run's deny statement and the time it stops applying (only "its expiry" if cleanup never read the statement). A pause statement stops applying at its own expiry (in testing, 22 minutes after FIS wrote it); FIS names it `DoNotModify`, so leave it to expire. This run's deny statement stops applying at its own expiry; in testing, no request of any type, PartiQL included, was refused after a deny's expiry.

To remove the deny sooner, to remove an expired statement from the policy text, or to remove a FIS pause statement that is still there after the experiment has ended and its expiry has passed, delete only that statement and keep the rest of the policy. Set `PREFIX` to the statement ID: for the deny, `FISDenyAccess` and 32 hexadecimal characters, as the cleanup error or `applyDenyPolicy`'s output gives it; for FIS's statements, `DoNotModifyFisDynamoDbPauseReplication` and the experiment ID, which is the shorter of the two IDs the check above prints for the table's policy and also covers that experiment's `ServicePrincipal` statement. Set `ARN` to the table's ARN, or to the stream's ARN for the stream's policy:

```bash
PREFIX=FISDenyAccess0123456789abcdef0123456789abcdef
ARN=$(aws dynamodb describe-table --table-name my-global-table --region us-east-1 --query 'Table.TableArn' --output text)
aws dynamodb get-resource-policy --resource-arn "$ARN" --region us-east-1 --output json > current.json
python3 -c 'import json,re,sys; pre=sys.argv[1]; re.fullmatch(r"FISDenyAccess[0-9a-f]{32}|DoNotModifyFisDynamoDbPauseReplicationEXP[A-Za-z0-9]{12,}", pre) or sys.exit("set PREFIX to a full statement ID"); r=json.load(open("current.json")); p=json.loads(r["Policy"]); st=p["Statement"] if isinstance(p["Statement"],list) else [p["Statement"]]; p["Statement"]=[s for s in st if not s.get("Sid","").startswith(pre)]; print(r["RevisionId"]); len(p["Statement"])<len(st) or sys.exit("no statement starts with " + pre); json.dump(p,open("restored.json","w")); print(len(st)-len(p["Statement"]), "removed,", len(p["Statement"]), "kept", file=sys.stderr); p["Statement"] or sys.exit("nothing is kept: delete the policy instead")' "$PREFIX" > revision.txt && aws dynamodb put-resource-policy --resource-arn "$ARN" --region us-east-1 --policy file://restored.json --expected-revision-id "$(cat revision.txt)"
```

If nothing is kept, delete the policy instead with `aws dynamodb delete-resource-policy --resource-arn "$ARN" --region us-east-1 --expected-revision-id "$(cat revision.txt)"`. A put or delete is rejected with `PolicyNotFoundException` if the policy changed since you read it; read it again and repeat. DynamoDB also rejects a policy write within 15 seconds of the previous one, with `ThrottlingException`, so wait 15 seconds between two removals.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to your DynamoDB global table operations, such as application transaction rates and cross-region latency.
3. Creating Amazon CloudWatch metrics and alarms to monitor:
   - Application error rates during regional failures
   - Cross-region failover time
   - Data consistency after recovery
   - Replication lag between regions
4. Adding stop conditions tied to critical business metrics to automatically halt the experiment if unacceptable impact occurs. A stop condition ends both actions as described in Stop Conditions. To test one, set its alarm to `ALARM` during a run with [`aws cloudwatch set-alarm-state`](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_SetAlarmState.html).
5. Implementing appropriate circuit breakers in your application to handle regional DynamoDB failures gracefully.
6. Testing your application's regional failover mechanisms to ensure they work as expected.
7. Validating that your monitoring can distinguish between planned chaos experiments and real outages.
8. Documenting the findings from your experiment and updating your incident response procedures accordingly.
9. Testing recovery procedures to ensure applications properly resume cross-region operations after the experiment.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
