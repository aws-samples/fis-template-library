# AWS Fault Injection Service Experiment: ElastiCache Redis Memory Stress

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Example Hypothesis

When Redis memory utilization exceeds 80%, applications should handle cache misses gracefully without performance degradation beyond acceptable thresholds. Memory pressure alerts should trigger within 2 minutes, and key eviction policies should prevent complete service failure. Applications should recover normal performance within 60 seconds after memory pressure is relieved.

### What does this enable me to verify?

* Appropriate Redis memory monitoring and observability is in place (were you able to detect memory pressure?)
* Alarms are configured correctly for memory utilization and key evictions (were the right people notified?)
* Your applications handle Redis memory pressure and cache misses gracefully
* Key eviction policies (LRU, LFU) work as expected under memory constraints
* Circuit breakers prevent cascading failures during cache miss scenarios
* Recovery controls work as expected when memory pressure is relieved

## Prerequisites

Before running this experiment, ensure that:

1. You have the roles created for FIS and SSM Automation to use. Example IAM policy documents and trust policies are provided.
2. You have created the SSM Automation Document from the sample provided (redis-memory-stress-automation.yaml)
3. You have created the FIS Experiment Template from the sample provided (redis-memory-stress-experiment-template.json)
4. The ElastiCache Redis cluster(s) you want to target have the "FIS-Ready":"True" tag and value
5. Your Redis clusters have appropriate maxmemory and eviction policies configured
6. You have appropriate monitoring and observability in place to track the impact of the experiment.

## How it works

This experiment simulates Redis memory stress by filling the cache with test data to trigger memory pressure and key eviction. The experiment follows this sequence:

1. **Dynamic Discovery**: Scans all ElastiCache replication groups to find clusters tagged with "FIS-Ready":"True"
2. **Memory Pressure**: Fills Redis with large payloads to consume available memory
3. **Sustained Load**: Maintains memory pressure for specified duration to trigger evictions
4. **Cleanup**: Removes test data to restore normal memory levels

The memory stress is implemented using an SSM Automation Document invoked by FIS. The SSM Automation Document connects to Redis and fills it with test data until memory pressure is achieved, then maintains that pressure for the specified duration.

To verify the experiment is working properly, you can monitor Redis memory usage and evictions:

```bash
# Monitor Redis memory usage
redis-cli -h <redis-endpoint> info memory

# Check key eviction stats
redis-cli -h <redis-endpoint> info stats | grep evicted

# Monitor application performance
watch -n 5 'curl -w "@curl-format.txt" -s -o /dev/null https://<your-app>/api/endpoint'
```

During the experiment, you should observe Redis memory utilization increasing to near-maximum levels and key evictions occurring based on your configured eviction policy.

## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until all actions are completed or until manually stopped.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

## Next Steps

As you adapt this scenario to your needs, we recommend:

1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to your Redis cache performance, such as cache hit rates and application response times.
3. Creating Amazon CloudWatch metrics and alarms to monitor Redis memory utilization and key eviction rates.
4. Adding stop conditions tied to critical business metrics to automatically halt the experiment if needed.
5. Implementing appropriate circuit breakers in your application to handle cache misses gracefully.
6. Testing your application's performance under various memory pressure scenarios.
7. Documenting the findings from your experiment and updating your incident response procedures accordingly.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
