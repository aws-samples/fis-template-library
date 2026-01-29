# AWS Fault Injection Service Experiment: Direct Connect Virtual Interface Disconnect

This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.

**THIS TEMPLATE WILL INJECT REAL FAULTS!**

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Hypothesis

Our hybrid cloud application will maintain connectivity and performance when Direct Connect virtual interfaces are brought down, demonstrating proper failover to backup connectivity paths (VPN or secondary Direct Connect).

## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment and perform Direct Connect virtual interface operations.
2. The IAM role specified in the `roleArn` field has the required permissions to perform the virtual interface disconnect operation.
3. The Direct Connect virtual interfaces you want to target have the `FIS-Ready=True` tag.
4. You have backup connectivity configured (VPN or secondary Direct Connect) to handle traffic during the experiment.
5. CloudWatch alarms are configured to monitor application availability and performance metrics.

## How it works

This experiment uses the native FIS action `aws:directconnect:virtual-interface-disconnect` to bring down Direct Connect virtual interfaces for a specified duration. The experiment targets 1 virtual interface tagged with `FIS-Ready=True` and keeps it down for 10 minutes, forcing traffic to failover to backup connectivity paths.

## Stop Conditions

This template does not include stop conditions by default to allow users to customize based on their specific application metrics and requirements. The experiment will continue to run until manually stopped or until the duration expires.

## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or business metric requiring an immediate end of the fault injection. This template makes no assumptions about your application and the relevant metrics and does not include stop conditions by default.

## Next Steps

As you adapt this scenario to your needs, we recommend:
1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to Direct Connect connectivity and hybrid application performance.
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of Direct Connect virtual interface failures.
4. Adding a stop condition tied to the alarm to automatically halt the experiment if critical thresholds are breached.
5. Testing the experiment in a non-production environment first to validate failover mechanisms.
6. Ensuring proper backup connectivity is configured and tested before running the experiment.

## Import Experiment

You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
