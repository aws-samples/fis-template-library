import * as cdk from 'aws-cdk-lib';
import {Construct} from 'constructs';
import {
    AmazonLinuxGeneration,
    Instance,
    InstanceClass,
    InstanceSize,
    InstanceType,
    IpAddresses,
    MachineImage,
    Vpc
} from "aws-cdk-lib/aws-ec2";
import {ManagedPolicy, PolicyStatement, Role} from "aws-cdk-lib/aws-iam";
import {Alarm, ComparisonOperator, Metric, TreatMissingData} from "aws-cdk-lib/aws-cloudwatch";
import {ServicePrincipal} from "aws-cdk-lib/aws-iam";
import {CfnExperimentTemplate} from "aws-cdk-lib/aws-fis";


export class FisExampleStack extends cdk.Stack {
    constructor(scope: Construct, id: string, props?: cdk.StackProps) {
        super(scope, id, props);

        //create vpc
        const vpc = new Vpc(this, "fis-demo-vpc", {
            ipAddresses: IpAddresses.cidr('10.0.0.0/16')
        });

        const ssmRole = new Role(this, 'ssm-instance-role', {
            assumedBy: new cdk.aws_iam.ServicePrincipal('ec2.amazonaws.com'),
            managedPolicies: [ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore')]
        });

        const instances = [];

        for (let i = 0; i < 6; i++) {
            // didnt find a way to automatically balance between AZs
            const spreadSubnet = vpc.privateSubnets[i % 2 == 0 ? 0 : 1];
            const instance = new Instance(this, `instance-${i}`, {
                vpc: vpc,
                instanceType: InstanceType.of(InstanceClass.BURSTABLE3_AMD, InstanceSize.NANO),
                machineImage: MachineImage.latestAmazonLinux2(),
                vpcSubnets: {subnets: [spreadSubnet]},
                role: ssmRole
            });
            cdk.Tags.of(instance).add('FIS-Target', 'true');
            instances.push(instance);
        }

        const targetInstance = instances[0];
        const targetInstanceId = targetInstance.instanceId;

        const alarm = new Alarm(this, 'cw-alarm', {
            alarmName: 'NetworkInAbnormal',
            metric: new Metric({
                metricName: 'NetworkIn',
                namespace: 'AWS/EC2',
            }).with({
                period: cdk.Duration.seconds(60)
            }),
            threshold: 10,
            evaluationPeriods: 1,
            treatMissingData: TreatMissingData.NOT_BREACHING,
            comparisonOperator: ComparisonOperator.LESS_THAN_THRESHOLD,
            datapointsToAlarm: 1,
        })

        const role = new Role(this, 'fis-role', {
            managedPolicies: [
                // TODO restrict to ec2:StartInstances and ec2:StopInstances
                ManagedPolicy.fromAwsManagedPolicyName('AmazonEC2FullAccess'),
                ManagedPolicy.fromAwsManagedPolicyName('CloudWatchLogsFullAccess')
            ],
            assumedBy: new ServicePrincipal('fis.amazonaws.com'),
        });

        role.addToPolicy(new PolicyStatement({
            resources: ['*'],
            actions: ['ssm:SendCommand', 'ssm:ListCommands', 'ssm:CancelCommands'],
        }))

        const action = {
            actionId: 'aws:ec2:stop-instances',
            parameters: {startInstancesAfterDuration: 'PT1M'},
            targets: {Instances: 'instanceTargets'}
        }

        const cpuStressAction = {
            actionId: 'aws:ssm:send-command',
            description: 'burn cpu vis SSM',
            parameters: {
                documentArn: `arn:aws:ssm:${this.region}::document/AWSFIS-Run-CPU-Stress`,
                documentParameters: JSON.stringify({DurationSeconds: '120'}),
                duration: 'PT2M'
            },
            targets: {Instances: 'instanceTargets'}
        }

        const target: CfnExperimentTemplate.ExperimentTemplateTargetProperty = {
            resourceType: 'aws:ec2:instance',
            selectionMode: 'ALL',
            resourceArns:
                [
                    `arn:aws:ec2:${this.region}:${this.account}:instance/${targetInstanceId}`
                ]
        }

        const template = new CfnExperimentTemplate(this, 'fis-template-demo-stop-instance', {
            description: 'Demo for Stopping and Starting a single instance via instance id',
            roleArn: role.roleArn,
            stopConditions: [
                {source: 'none'}
            ],
            tags: {Name: 'StopStartInstance'},
            actions: {
                'instanceActions': action
            },
            targets: {
                'instanceTargets': target
            }
        });

        const templateWithAlarm = new CfnExperimentTemplate(this, 'fis-template-demo-stop-instance-with-alarm', {
            description: 'Demo for Stopping and Starting a single instance via instance id and abort by alarm',
            roleArn: role.roleArn,
            stopConditions: [{
                source: 'aws:cloudwatch:alarm',
                value: alarm.alarmArn
            }],
            tags: {Name: 'AbortExperimentByAlarm'},
            actions: {
                'instanceActions': {
                    ...action,
                    parameters: {startInstancesAfterDuration: 'PT10M'},
                }
            },
            targets: {
                'instanceTargets': target
            }
        });

        const templateWithAzFilter = new CfnExperimentTemplate(this, 'fis-template-demo-stop-instances-in-az', {
            description: 'Demo for Stopping and Starting all instances in an AZ',
            roleArn: role.roleArn,
            stopConditions: [
                {source: 'none'}
            ],
            tags: {Name: 'StopInstancesInAz'},
            actions: {
                'instanceActions': action
            },
            targets: {
                'instanceTargets': {
                    resourceType: 'aws:ec2:instance',
                    selectionMode: 'ALL',
                    resourceTags: {
                        'FIS-Target': 'true'
                    },
                    filters: [
                        {
                            path: 'Placement.AvailabilityZone',
                            values: [targetInstance.instanceAvailabilityZone]
                        },
                        {
                            path: 'State.Name',
                            values: ['running']
                        }
                    ]

                }
            }
        });


        const templateCpuStress = new CfnExperimentTemplate(this, 'fis-template-demo-cpu-stress', {
            description: 'Demo for injecting CPU stress via SSM',
            roleArn: role.roleArn,
            stopConditions: [
                {source: 'none'}
            ],
            tags: {Name: 'BurnCPUViaSSM'},
            actions: {
                'instanceActions': cpuStressAction
            },
            targets: {
                'instanceTargets': target
            }
        });

        const templateStopEksWorker = new CfnExperimentTemplate(this, 'fis-template-demo-stop-eks-node', {
            description: 'Demo for terminating an eks worker',
            roleArn: role.roleArn,
            stopConditions: [
                {source: 'none'}
            ],
            tags: {Name: 'Terminate EKS Worker'},
            actions: {
                'instanceActions': {
                    actionId: 'aws:eks:terminate-nodegroup-instances',
                    description: 'Terminate EKS NodeGroup Instance',
                    parameters: {
                        instanceTerminationPercentage: "50"
                    },
                    targets: {Nodegroups: 'nodeGroupTarget'}
                }
            },
            targets: {
                'nodeGroupTarget': {
                    resourceType: 'aws:eks:nodegroup',
                    selectionMode: 'ALL',
                    // TODO make this configurable via either CDK's context or CfnParameter
                    resourceTags: {
                        'eksctl.cluster.k8s.io/v1alpha1/cluster-name': 'eks-demo'
                    }
                }
            }
        });

        const killContainerScript = 'sudo docker kill $(sudo docker ps -f name=k8s_ecsdemo-frontend -q)';
        const killContainerAction = {
            actionId: 'aws:ssm:send-command',
            description: 'Kill the frontend container',
            parameters: {
                documentArn: `arn:aws:ssm:${this.region}::document/AWS-RunShellScript`,
                documentParameters: JSON.stringify(
                    {commands: killContainerScript}),
                duration: 'PT1M'
            },
            targets: {Instances: 'workerNodesTarget'}
        }

        const workerNodesTarget: CfnExperimentTemplate.ExperimentTemplateTargetProperty = {
            resourceType: 'aws:ec2:instance',
            resourceTags: {
                // TODO make this configurable via CDK's context or CfnParameter
                Name: 'eks-demo-nodegroup-Node'
            },
            selectionMode: 'ALL',
            filters: [
                {
                    path: 'State.Name',
                    values: ['running']
                }
            ]
        }


        const templateKillContainer = new CfnExperimentTemplate(this, 'fis-template-demo-kill-container', {
            description: 'Demo for killing a docker container on an EKS worker',
            roleArn: role.roleArn,
            stopConditions: [
                {source: 'none'}
            ],
            tags: {Name: 'Kill Container on EKS Worker'},
            actions: {
                'instanceActions': killContainerAction
            },
            targets: {
                'workerNodesTarget': workerNodesTarget
            }
        });

    }
}
