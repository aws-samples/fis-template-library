# AWS Fault Injection Simulator (FIS) examples

This repo contains a CloudFormation (CFN) template with examples for AWS FIS. Experiment Templates for the following Experiments are included in the CFN:
- Stopping a single instance by id
- Aborting an experiment when a CloudWatch Alarm is triggered
- Stopping all instances in a single Availability Zone
- Injecting CPU stress via ssm:send-command
- Terminate an EKS Worker Node
- Kill a Container running on an EKS Worker node via ssm:send-command


## Deployment

You can either deploy via the provided CDK stack or use the synthesized CloudFormation YAML.

The deployment will create 6 EC2 instances of type `t3a.nano` spread across two Availability Zones.

To use the EKS experiment templates you will have to have a running EKS cluster. The creation of this cluster is out of scope of the CFN. However, you can create it easily with [eksctl](https://eksctl.io/) and the following example template (make sure to tweak the region accordingly):

```yaml
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig

metadata:
  name: eks-demo
  region: eu-west-1
  version: "1.19"


managedNodeGroups:
- name: nodegroup
  desiredCapacity: 3
  instanceType: m5.large
  ssh:
    enableSsm: true
```

### Deploy via CDK:
```bash
npm install
cdk deploy
```

### Deploy via Cloudformation:

```bash
aws cloudformation create-stack --template-body file://cfn_fis_demos.yaml --stack-name fis-demo-stack --capabilities CAPABILITY_NAMED_IAM
```

## Run Experiments

### Stop Single Instance By InstanceId
Just run it via the console

### Abort experiment when alarm is raised
- start the experiment from the console
- raise the alarm via CLI: `aws cloudwatch set-alarm-state --alarm-name "NetworkInAbnormal" --state-value "ALARM" --state-reason "testing FIS"`
- note that the experiment will stop as soon as the alarm is triggered

### Stop All Instances in a single AZ
- start the experiment from the console
- note that all instances of a given AZ stop

### Inject CPU stress via SSM
- start the experiment from the console
- connect to the targeted instance via SSM (e.g. CLI: `aws ssm start-session --target $(aws ec2 describe-instances --filters "Name=tag:Name,Values=FisExampleStack/instance-0" "Name=instance-state-name,Values=running" --query "Reservations[*].Instances[*].{Instance:InstanceId}" --output text)`)
- note the high cpu load (e.g. by using the `top` command in your ssh session)

### EKS Terminate Worker Node

As of now the experiments selects a target of type `aws:eks:nodegroup` with a resource tag of `'eksctl.cluster.k8s.io/v1alpha1/cluster-name': 'eks-demo'`. You will need to make sure that such a node exists.

### EKS Kill Container

The experiment will use a ssm:send-command to directly issue a `docker kill` on all ec2-instances having a tag of `Name: eks-demo-nodegroup-Node`. You will need to make sure that such instances exist before running this experiment.

As a sample workload you can deploy the [EKS Workshops frontend application](https://www.eksworkshop.com/beginner/050_deploy/deployfrontend/). This is what is currently used for finding the container to kill. It is selected via a simple `docker ps -f name=k8s_ecsdemo-frontend -q`. You will need to make sure that such a container is running on your workers.


## Clean-Up
Delete the CloudFormation stack via CLI:
```bash
aws cloudformation delete-stack --stack-name fis-demo-stack
```

## Generated CloudFormation YAML

The CFN YAML `cfn_fis_demos.yaml` is generated via CDK's `cdk synth > cfn_fis_demos.yaml` and should not be edited manually.

## Additional samples

* [Start an AWS Fault Injection Simulator experiment on a schedule](./schedule-experiment/README.md)
* [Start an AWS Fault Injection Simulator experiment based on events](./event-trigger-experiment/README.md)
* [Include AWS Fault Injection Simulator experiments in your CI/CD pipelines](./pipeline-experiment/README.md)

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.
