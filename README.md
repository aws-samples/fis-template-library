Chaos Engineering with AWS Fault Injection Simulator (FIS) 
==========================================================

Collection of [FIS Experiment Templates.](https://docs.aws.amazon.com/fis/latest/userguide/experiment-templates.html)
========================================

These templates let you perform fault injection experiments on resources (applications, network, and infrastructure) in the [AWS Cloud](https://aws.amazon.com).

Prerequisites:
--------------

-   [What is AWS Fault Injection Simulator?](https://docs.aws.amazon.com/fis/latest/userguide/what-is.html)
-   [Experiment templates for AWS FIS](https://docs.aws.amazon.com/fis/latest/userguide/experiment-templates.html)
-   [How AWS Fault Injection Simulator works with IAM](https://docs.aws.amazon.com/fis/latest/userguide/security_iam_service-with-iam.html)


Deployment:
--------------

### CLI

Upload an FIS experiment template to your AWS Account:
-----------------------------------------------------

``` {.sourceCode .shell}
➜ aws fis create-experiment-template --cli-input-json fileb://fis-template.json --query experimentTemplate.id

"EXTQGczsC6CZPmHa"
```


### CDK

Upload an FIS experiment template to your AWS Account:
-----------------------------------------------------

``` {.sourceCode .shell}
git clone ..
cd ..
cdk deploy
```

## License

This library is licensed under the MIT-0 License. See the LICENSE file.


