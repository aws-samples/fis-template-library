#!/usr/bin/env python3
"""
Deploy Database Connection Limit Exhaustion FIS Experiment

This script creates all required AWS resources in the correct order:
1. IAM roles and policies
2. SSM automation document
3. FIS experiment template

The script is idempotent - safe to run multiple times to apply updates.

Usage:

To build resources:
    python deploy.py --region your-region --account-id 123456789012

To delete resources:
    python deploy.py --region your-region --account-id 123456789012 --delete-resources

Requirements:
    - AWS CLI configured with appropriate credentials
    - boto3 installed: pip install boto3
"""

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("Error: boto3 is required. Install with: pip install boto3")
    sys.exit(1)


class ExperimentDeployer:
    def __init__(self, region, account_id):
        self.region = region
        self.account_id = account_id
        self.iam_client = boto3.client('iam', region_name=region)
        self.ssm_client = boto3.client('ssm', region_name=region)
        self.fis_client = boto3.client('fis', region_name=region)
        self.base_path = Path(__file__).parent
        
        # Resource names
        self.fis_role_name = 'ConnectionLimitExhaustion-FIS-Role'
        self.ssm_role_name = 'ConnectionLimitExhaustion-SSM-Automation-Role'
        self.instance_profile_name = 'SSM-Managed-Instance-Profile'
        self.instance_role_name = 'SSM-Managed-Instance-Profile-Role'
        self.ssm_document_name = 'ConnectionLimitExhaustion-Automation'
        
    def load_json_file(self, filename):
        """Load and parse JSON file"""
        file_path = self.base_path / filename
        with open(file_path, 'r') as f:
            return json.load(f)
    
    def load_yaml_file(self, filename):
        """Load YAML file as string"""
        file_path = self.base_path / filename
        with open(file_path, 'r') as f:
            return f.read()
    
    def replace_placeholders(self, content):
        """Replace placeholder values in templates"""
        if isinstance(content, str):
            content = content.replace('<YOUR AWS ACCOUNT>', self.account_id)
            content = content.replace('<YOUR REGION>', self.region)
            return content
        elif isinstance(content, dict):
            return {k: self.replace_placeholders(v) for k, v in content.items()}
        elif isinstance(content, list):
            return [self.replace_placeholders(item) for item in content]
        return content
    
    def create_or_update_role(self, role_name, trust_policy_file, policy_file, description):
        """Create or update IAM role with policy"""
        print(f"\n{'='*60}")
        print(f"Processing IAM Role: {role_name}")
        print(f"{'='*60}")
        
        trust_policy = self.load_json_file(trust_policy_file)
        policy_document = self.load_json_file(policy_file)
        policy_document = self.replace_placeholders(policy_document)
        
        # Create or update role
        try:
            self.iam_client.get_role(RoleName=role_name)
            print(f"✓ Role '{role_name}' already exists")
            
            # Update trust policy
            self.iam_client.update_assume_role_policy(
                RoleName=role_name,
                PolicyDocument=json.dumps(trust_policy)
            )
            print(f"✓ Updated trust policy for '{role_name}'")
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchEntity':
                self.iam_client.create_role(
                    RoleName=role_name,
                    AssumeRolePolicyDocument=json.dumps(trust_policy),
                    Description=description
                )
                print(f"✓ Created role '{role_name}'")
            else:
                raise
        
        # Attach inline policy
        policy_name = f"{role_name}-Policy"
        self.iam_client.put_role_policy(
            RoleName=role_name,
            PolicyName=policy_name,
            PolicyDocument=json.dumps(policy_document)
        )
        print(f"✓ Attached/updated policy '{policy_name}'")
        
        role_arn = f"arn:aws:iam::{self.account_id}:role/{role_name}"
        print(f"✓ Role ARN: {role_arn}")
        return role_arn
    
    def create_instance_profile_and_role(self):
        """Create EC2 instance profile and role for SSM"""
        print(f"\n{'='*60}")
        print(f"Processing EC2 Instance Profile: {self.instance_profile_name}")
        print(f"{'='*60}")

        trust_policy = self.load_json_file('ec2-iam-trust-relationship.json')

        try:
            self.iam_client.get_role(RoleName=self.instance_role_name)
            print(f"✓ Role '{self.instance_role_name}' already exists")

            self.iam_client.update_assume_role_policy(
                RoleName=self.instance_role_name,
                PolicyDocument=json.dumps(trust_policy)
            )
            print(f"✓ Updated trust policy for '{self.instance_role_name}'")
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchEntity':
                self.iam_client.create_role(
                    RoleName=self.instance_role_name,
                    AssumeRolePolicyDocument=json.dumps(trust_policy),
                    Description='Role for SSM-managed EC2 instances'
                )
                print(f"✓ Created role '{self.instance_role_name}'")
            else:
                raise
        
        # Attach AWS managed policy for SSM
        try:
            self.iam_client.attach_role_policy(
                RoleName=self.instance_role_name,
                PolicyArn='arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore'
            )
            print(f"✓ Attached AmazonSSMManagedInstanceCore policy")
        except ClientError as e:
            if e.response['Error']['Code'] == 'EntityAlreadyExists':
                print(f"✓ AmazonSSMManagedInstanceCore policy already attached")
            else:
                raise
        
        # Attach policy for Secrets Manager access
        secrets_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Action": [
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:DescribeSecret"
                ],
                "Resource": f"arn:aws:secretsmanager:{self.region}:{self.account_id}:secret:*"
            }]
        }
        
        self.iam_client.put_role_policy(
            RoleName=self.instance_role_name,
            PolicyName='SecretsManagerAccess',
            PolicyDocument=json.dumps(secrets_policy)
        )
        print(f"✓ Attached Secrets Manager access policy")
        
        # Create instance profile
        try:
            self.iam_client.get_instance_profile(InstanceProfileName=self.instance_profile_name)
            print(f"✓ Instance profile '{self.instance_profile_name}' already exists")
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchEntity':
                self.iam_client.create_instance_profile(
                    InstanceProfileName=self.instance_profile_name
                )
                print(f"✓ Created instance profile '{self.instance_profile_name}'")
            else:
                raise
        
        # Add role to instance profile
        try:
            self.iam_client.add_role_to_instance_profile(
                InstanceProfileName=self.instance_profile_name,
                RoleName=self.instance_role_name
            )
            print(f"✓ Added role to instance profile")
        except ClientError as e:
            if e.response['Error']['Code'] == 'LimitExceeded':
                print(f"✓ Role already added to instance profile")
            else:
                raise
    
    def create_or_update_ssm_document(self):
        """Create or update SSM automation document"""
        print(f"\n{'='*60}")
        print(f"Processing SSM Document: {self.ssm_document_name}")
        print(f"{'='*60}")
        
        content = self.load_yaml_file('database-connection-limit-exhaustion-automation.yaml')
        content = self.replace_placeholders(content)
        
        try:
            # Try to update existing document
            response = self.ssm_client.update_document(
                Content=content,
                Name=self.ssm_document_name,
                DocumentVersion='$LATEST',
                DocumentFormat='YAML'
            )
            print(f"✓ Updated SSM document '{self.ssm_document_name}'")
            
            # Set as default version
            new_version = response['DocumentDescription']['DocumentVersion']
            self.ssm_client.update_document_default_version(
                Name=self.ssm_document_name,
                DocumentVersion=new_version
            )
            print(f"✓ Set version {new_version} as default")
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'InvalidDocument':
                # Document doesn't exist, create it
                self.ssm_client.create_document(
                    Content=content,
                    Name=self.ssm_document_name,
                    DocumentType='Automation',
                    DocumentFormat='YAML'
                )
                print(f"✓ Created SSM document '{self.ssm_document_name}'")
            elif e.response['Error']['Code'] == 'DuplicateDocumentContent':
                print(f"✓ No changes to SSM document '{self.ssm_document_name}', proceeding")
                return
            else:
                raise
        
        doc_arn = f"arn:aws:ssm:{self.region}:{self.account_id}:document/{self.ssm_document_name}"
        print(f"✓ Document ARN: {doc_arn}")
        return doc_arn
    
    def create_or_update_fis_template(self):
        """Create or update FIS experiment template"""
        print(f"\n{'='*60}")
        print(f"Processing FIS Experiment Template")
        print(f"{'='*60}")
        
        template = self.load_json_file('database-connection-limit-exhaustion-experiment-template.json')
        template = self.replace_placeholders(template)
        
        # Update role ARN
        template['roleArn'] = f"arn:aws:iam::{self.account_id}:role/{self.fis_role_name}"
        
        # Update SSM document ARN in actions
        doc_arn = f"arn:aws:ssm:{self.region}:{self.account_id}:document/{self.ssm_document_name}"
        for action in template['actions'].values():
            if 'documentArn' in action['parameters']:
                action['parameters']['documentArn'] = doc_arn
        
        # Check if template already exists
        try:
            response = self.fis_client.list_experiment_templates()
            existing_template = None
            
            for tmpl in response.get('experimentTemplates', []):
                if tmpl.get('tags', {}).get('Name') == template['tags']['Name']:
                    existing_template = tmpl['id']
                    break
            
            if existing_template:
                print(f"✓ FIS template already exists with ID: {existing_template}")
                print(f"  Updating template...")
                
                # Update existing template
                try:
                    update_params = {
                        'id': existing_template,
                        'description': template['description'],
                        'stopConditions': template['stopConditions'],
                        'targets': template.get('targets', {}),
                        'actions': template['actions'],
                        'roleArn': template['roleArn']
                    }
                    
                    # Only include logConfiguration if it exists and is not empty
                    if template.get('logConfiguration'):
                        update_params['logConfiguration'] = template['logConfiguration']
                    
                    response = self.fis_client.update_experiment_template(**update_params)
                    print(f"✓ Successfully updated FIS experiment template: {existing_template}")
                    return existing_template
                except ClientError as e:
                    if e.response['Error']['Code'] == 'ValidationException':
                        print(f"  Note: Some template properties cannot be updated.")
                        print(f"  Template ID: {existing_template} (no changes applied)")
                        return existing_template
                    else:
                        raise
            
        except ClientError:
            pass
        
        # Create new template
        create_params = {
            'clientToken': f"deploy-{int(time.time())}",
            'description': template['description'],
            'stopConditions': template['stopConditions'],
            'targets': template.get('targets', {}),
            'actions': template['actions'],
            'roleArn': template['roleArn'],
            'tags': template['tags'],
            'experimentOptions': template.get('experimentOptions', {})
        }
        
        # Only include logConfiguration if it exists and is not empty
        if template.get('logConfiguration'):
            create_params['logConfiguration'] = template['logConfiguration']
        
        response = self.fis_client.create_experiment_template(**create_params)
        
        template_id = response['experimentTemplate']['id']
        print(f"✓ Created FIS experiment template: {template_id}")
        return template_id
    
    def delete(self):
        """Delete all resources created by this script"""
        print("\n" + "="*60)
        print("Database Connection Limit Exhaustion - Delete Resources")
        print("="*60)
        print(f"Region: {self.region}")
        print(f"Account: {self.account_id}")
        print("="*60)

        errors = []

        # Step 1: Delete FIS experiment template
        print("\n[Step 1/4] Deleting FIS Experiment Template...")
        try:
            response = self.fis_client.list_experiment_templates()
            template_id = None
            for tmpl in response.get('experimentTemplates', []):
                if tmpl.get('tags', {}).get('Name') == 'Database-connection-limit-exhaustion':
                    template_id = tmpl['id']
                    break
            if template_id:
                self.fis_client.delete_experiment_template(id=template_id)
                print(f"✓ Deleted FIS template: {template_id}")
            else:
                print("  FIS template not found, skipping")
        except ClientError as e:
            msg = f"Failed to delete FIS template: {e}"
            print(f"✗ {msg}")
            errors.append(msg)

        # Step 2: Delete SSM document
        print("\n[Step 2/4] Deleting SSM Automation Document...")
        try:
            self.ssm_client.delete_document(Name=self.ssm_document_name)
            print(f"✓ Deleted SSM document: {self.ssm_document_name}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'InvalidDocument':
                print("  SSM document not found, skipping")
            else:
                msg = f"Failed to delete SSM document: {e}"
                print(f"✗ {msg}")
                errors.append(msg)

        # Step 3: Delete IAM roles and their policies
        print("\n[Step 3/4] Deleting IAM Roles...")
        for role_name in [self.fis_role_name, self.ssm_role_name]:
            try:
                # Delete inline policies first
                policies = self.iam_client.list_role_policies(RoleName=role_name)
                for policy_name in policies['PolicyNames']:
                    self.iam_client.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
                    print(f"  ✓ Deleted inline policy '{policy_name}' from '{role_name}'")
                # Detach managed policies
                attached = self.iam_client.list_attached_role_policies(RoleName=role_name)
                for policy in attached['AttachedPolicies']:
                    self.iam_client.detach_role_policy(RoleName=role_name, PolicyArn=policy['PolicyArn'])
                    print(f"  ✓ Detached managed policy '{policy['PolicyName']}' from '{role_name}'")
                self.iam_client.delete_role(RoleName=role_name)
                print(f"✓ Deleted role: {role_name}")
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchEntity':
                    print(f"  Role '{role_name}' not found, skipping")
                else:
                    msg = f"Failed to delete role '{role_name}': {e}"
                    print(f"✗ {msg}")
                    errors.append(msg)

        # Step 4: Delete instance profile and its role
        print("\n[Step 4/4] Deleting EC2 Instance Profile...")
        try:
            # Remove role from profile before deleting
            try:
                self.iam_client.remove_role_from_instance_profile(
                    InstanceProfileName=self.instance_profile_name,
                    RoleName=self.instance_role_name
                )
                print(f"  ✓ Removed role from instance profile")
            except ClientError as e:
                if e.response['Error']['Code'] not in ('NoSuchEntity', 'LimitExceeded'):
                    raise
            self.iam_client.delete_instance_profile(InstanceProfileName=self.instance_profile_name)
            print(f"✓ Deleted instance profile: {self.instance_profile_name}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchEntity':
                print("  Instance profile not found, skipping")
            else:
                msg = f"Failed to delete instance profile: {e}"
                print(f"✗ {msg}")
                errors.append(msg)

        try:
            # Delete inline policies then the role
            policies = self.iam_client.list_role_policies(RoleName=self.instance_role_name)
            for policy_name in policies['PolicyNames']:
                self.iam_client.delete_role_policy(RoleName=self.instance_role_name, PolicyName=policy_name)
                print(f"  ✓ Deleted inline policy '{policy_name}' from '{self.instance_role_name}'")
            attached = self.iam_client.list_attached_role_policies(RoleName=self.instance_role_name)
            for policy in attached['AttachedPolicies']:
                self.iam_client.detach_role_policy(RoleName=self.instance_role_name, PolicyArn=policy['PolicyArn'])
                print(f"  ✓ Detached managed policy '{policy['PolicyName']}' from '{self.instance_role_name}'")
            self.iam_client.delete_role(RoleName=self.instance_role_name)
            print(f"✓ Deleted role: {self.instance_role_name}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchEntity':
                print(f"  Role '{self.instance_role_name}' not found, skipping")
            else:
                msg = f"Failed to delete role '{self.instance_role_name}': {e}"
                print(f"✗ {msg}")
                errors.append(msg)

        print("\n" + "="*60)
        if errors:
            print(f"✗ DELETE COMPLETED WITH {len(errors)} ERROR(S)")
            for err in errors:
                print(f"  • {err}")
        else:
            print("✓ DELETE SUCCESSFUL")
        print("="*60 + "\n")

        return len(errors) == 0

    def deploy(self):
        """Deploy all resources in correct order"""
        print("\n" + "="*60)
        print("Database Connection Limit Exhaustion - Deployment")
        print("="*60)
        print(f"Region: {self.region}")
        print(f"Account: {self.account_id}")
        print("="*60)
        
        try:
            # Step 1: Create IAM roles
            print("\n[Step 1/5] Creating IAM Roles...")
            
            self.create_or_update_role(
                self.fis_role_name,
                'fis-iam-trust-relationship.json',
                'database-connection-limit-exhaustion-fis-role-iam-policy.json',
                'Role for FIS to execute connection limit exhaustion experiments'
            )
            
            self.create_or_update_role(
                self.ssm_role_name,
                'ssm-iam-trust-relationship.json',
                'database-connection-limit-exhaustion-ssm-automation-role-iam-policy.json',
                'Role for SSM automation to manage EC2 instances and execute commands'
            )
            
            # Step 2: Create instance profile
            print("\n[Step 2/5] Creating EC2 Instance Profile...")
            self.create_instance_profile_and_role()
            
            # Wait for IAM propagation
            print("\n[Step 3/5] Waiting for IAM propagation (10 seconds)...")
            time.sleep(10)
            print("✓ IAM propagation complete")
            
            # Step 3: Create SSM document
            print("\n[Step 4/5] Creating SSM Automation Document...")
            self.create_or_update_ssm_document()
            
            # Step 4: Create FIS template
            print("\n[Step 5/5] Creating FIS Experiment Template...")
            template_id = self.create_or_update_fis_template()
            
            # Success summary
            print("\n" + "="*60)
            print("✓ DEPLOYMENT SUCCESSFUL")
            print("="*60)
            print("\nResources Created:")
            print(f"  • FIS Role: {self.fis_role_name}")
            print(f"  • SSM Role: {self.ssm_role_name}")
            print(f"  • Instance Profile: {self.instance_profile_name}")
            print(f"  • SSM Document: {self.ssm_document_name}")
            print(f"  • FIS Template: {template_id}")
            print("\n" + "="*60 + "\n")
            
            return True
            
        except Exception as e:
            print(f"\n✗ Deployment failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return False


def main():
    parser = argparse.ArgumentParser(
        description='Deploy Database Connection Limit Exhaustion FIS Experiment',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python deploy.py --region us-east-1 --account-id 123456789012
  python deploy.py --region eu-west-1 --account-id 123456789012

The script is idempotent and safe to run multiple times.
        """
    )
    
    parser.add_argument(
        '--delete-resources',
        action='store_true',
        help='Delete all resources created by this script'
    )

    parser.add_argument(
        '--region',
        required=True,
        help='AWS region (e.g., us-east-1)'
    )
    
    parser.add_argument(
        '--account-id',
        required=True,
        help='AWS account ID (12-digit number)'
    )
    
    args = parser.parse_args()
    
    # Validate account ID format
    if not args.account_id.isdigit() or len(args.account_id) != 12:
        print("Error: Account ID must be a 12-digit number")
        sys.exit(1)
    
    deployer = ExperimentDeployer(args.region, args.account_id)
    success = deployer.delete() if args.delete_resources else deployer.deploy()
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
