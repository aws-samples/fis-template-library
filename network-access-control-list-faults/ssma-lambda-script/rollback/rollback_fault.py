import logging
import boto3
import json


def rollback(events, context):
    save_for_rollback = json.loads(events['saved_configuration'])
    region = save_for_rollback["region"]

    logger = logging.getLogger(__name__)
    logger.info('Rolling back Network ACL to original configuration')
    ec2_client = boto3.client('ec2', region_name=region)

    # Rollback the initial association
    for conf in save_for_rollback["rollback_conf"]:
        ec2_client.replace_network_acl_association(
            AssociationId=conf["NewAssociationId"],
            NetworkAclId=conf["Nacl_Id"]
        )
    logger.info('Deleting the Chaos NACL')
    # delete the Chaos NACL
    ec2_client.delete_network_acl(
        NetworkAclId=save_for_rollback["chaos_nacl_id"]
    )
