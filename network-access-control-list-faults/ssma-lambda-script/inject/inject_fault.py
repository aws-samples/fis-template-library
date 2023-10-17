import logging
import boto3
import time
import json


def create_chaos_nacl(ec2_client, vpc_id):
    logger = logging.getLogger(__name__)
    logger.info('Create a Chaos Network ACL')
    # Create a Chaos Network ACL
    chaos_nacl = ec2_client.create_network_acl(
        VpcId=vpc_id,
    )
    associations = chaos_nacl['NetworkAcl']
    chaos_nacl_id = associations['NetworkAclId']
    time.sleep(5)
    # Tagging the new network ACL for visibility reason and help manual rollback if necessary
    ec2_client.create_tags(
        Resources=[
            chaos_nacl_id,
        ],
        Tags=[
            {
                'Key': 'Name',
                'Value': 'chaos-nacl'
            },
        ]
    )
    # Create Egress and Ingress rule blocking all inbound and outbound traffic
    # Egress
    ec2_client.create_network_acl_entry(
        CidrBlock='0.0.0.0/0',
        Egress=True,
        PortRange={'From': 0, 'To': 65535, },
        NetworkAclId=chaos_nacl_id,
        Protocol='-1',
        RuleAction='deny',
        RuleNumber=100,
    )

    # Ingress
    ec2_client.create_network_acl_entry(
        CidrBlock='0.0.0.0/0',
        Egress=False,
        PortRange={'From': 0, 'To': 65535, },
        NetworkAclId=chaos_nacl_id,
        Protocol='-1',
        RuleAction='deny',
        RuleNumber=101,
    )
    return chaos_nacl_id


def get_subnets_to_chaos(ec2_client, vpc_id, az_name):
    logger = logging.getLogger(__name__)
    logger.info('Getting the list of subnets to fail')
    # Describe the subnet so you can see if it is in the AZ
    subnets_response = ec2_client.describe_subnets(
        Filters=[
            {
                'Name': 'availability-zone',
                'Values': [az_name]
            },
            {
                'Name': 'vpc-id',
                'Values': [vpc_id]
            }
        ]
    )
    subnets_to_chaos = [
        subnet['SubnetId'] for subnet in subnets_response['Subnets']
    ]
    return subnets_to_chaos


def get_nacls_to_chaos(ec2_client, subnets_to_chaos):
    logger = logging.getLogger(__name__)
    logger.info('Getting the list of NACLs to blackhole')

    # Find network acl associations mapped to the subnets_to_chaos
    acls_response = ec2_client.describe_network_acls(
        Filters=[
            {
                'Name': 'association.subnet-id',
                'Values': subnets_to_chaos
            }
        ]
    )
    network_acls = acls_response['NetworkAcls']

    # saving initial nacl association so it can be reverted
    nacl_ids = []
    for nacl in network_acls:
        for nacl_association in nacl['Associations']:
            if nacl_association['SubnetId'] in subnets_to_chaos:
                nacl_association_id, nacl_id = nacl_association[
                    'NetworkAclAssociationId'], nacl_association['NetworkAclId']
                nacl_ids.append((nacl_association_id, nacl_id))

    return nacl_ids


def apply_chaos_config(ec2_client, nacl_ids, chaos_nacl_id):
    logger = logging.getLogger(__name__)
    logger.info('Saving original config & applying new chaos config')
    save_for_rollback = []
    # Modify the association of the subnets_to_chaos with the Chaos NetworkACL
    for nacl_association_id, nacl_id in nacl_ids:
        response = ec2_client.replace_network_acl_association(
            AssociationId=nacl_association_id,
            NetworkAclId=chaos_nacl_id
        )
        save_for_rollback.append(
            {
                "NewAssociationId": response['NewAssociationId'],
                "Nacl_Id": nacl_id
            }
        )
    return save_for_rollback


def inject_fault(events, context):

    region = events['Region']
    az_name = events['AvailabilityZone']
    vpc_id = events['VPCId']

    logger = logging.getLogger(__name__)
    logger.info('Setting up ec2 client for region %s ', region)
    ec2_client = boto3.client('ec2', region_name=region)
    chaos_nacl_id = create_chaos_nacl(ec2_client, vpc_id)
    subnets_to_chaos = get_subnets_to_chaos(ec2_client, vpc_id, az_name)
    nacl_ids = get_nacls_to_chaos(ec2_client, subnets_to_chaos)

    # Saving initial association for rollback
    save_for_rollback = apply_chaos_config(ec2_client, nacl_ids, chaos_nacl_id)
    return json.dumps(
        {
            "region": region,
            "rollback_conf": save_for_rollback,
            "chaos_nacl_id": chaos_nacl_id
        }
    )
