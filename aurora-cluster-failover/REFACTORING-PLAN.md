# Aurora Cluster Failover Refactoring Plan

This document outlines the plan for refactoring the Aurora Cluster Failover experiment to align with the FIS template library standards and conventions. The refactoring should follow the same approach used for the MySQL RDS Load Test and Failover experiment.

## Objectives

1. Remove infrastructure deployment from the FIS experiment template
2. Create a clean FIS experiment that uses tag-based targeting
3. Move infrastructure examples to a separate directory
4. Ensure consistent file naming and structure with other experiments
5. Follow the style guide requirements for all files

## Required Files Structure

```
aurora-cluster-failover/
├── AWSFIS.json                                  # Template version marker
├── aurora-cluster-failover-template.json        # FIS experiment template
├── aurora-cluster-failover-iam-policy.json      # IAM policy document
├── aurora-cluster-failover-ssm-template.json    # SSM document template (if needed)
├── fis-iam-trust-relationship.json              # Trust relationship
├── README.md                                    # Main documentation
└── examples/                                    # Infrastructure examples
    ├── cloudformation-infrastructure.yaml       # Example infrastructure
    ├── infrastructure-examples.md               # Documentation for examples
    └── deploy-infrastructure.sh                 # Example deployment script
```

## Step-by-Step Refactoring Tasks

### 1. Update AWSFIS.json

Update to use the nested structure:
```json
{
    "AWSFIS": {
        "template": {
            "version": "1.0"
        }
    }
}
```

### 2. Create Clean FIS Experiment Template

- Create `aurora-cluster-failover-template.json`
- Use tag-based targeting with `FIS-Ready=True` tag only
- Use placeholder format: `<YOUR REGION>:<YOUR AWS ACCOUNT>`
- Include proper actions for Aurora cluster failover
- Keep logConfiguration section as optional
- Use consistent structure with other experiments

### 3. Create IAM Policy

- Create `aurora-cluster-failover-iam-policy.json`
- Include FIS experiment permissions
- Include Aurora-specific permissions with proper resource conditions
- Use consistent `aws:ResourceTag/FIS-Ready` condition
- Follow structure from MySQL RDS example

### 4. Create SSM Document Template (if needed)

- Create `aurora-cluster-failover-ssm-template.json` if the experiment requires SSM commands
- Follow the structure from the MySQL RDS example
- Include proper parameters and commands for Aurora

### 5. Update Trust Relationship

- Ensure `fis-iam-trust-relationship.json` matches other examples
- Use standard trust policy for FIS service

### 6. Update README.md

- Follow style guide structure exactly
- Include required sections: title, description, disclaimer, hypothesis, prerequisites, etc.
- Make prerequisites concise and focus on tag-based targeting
- Remove any references to infrastructure deployment
- Add reference to examples directory

### 7. Create Examples Directory

- Create `examples/` directory
- Move existing infrastructure code to this directory
- Update CloudFormation template to use simplified tagging (`FIS-Ready=True`)
- Create example deployment script
- Create comprehensive documentation in `infrastructure-examples.md`

### 8. Clean Up Old Files

- Remove any old files that are no longer needed
- Ensure no references to removed files remain

## Reference Examples

Use these examples as reference for the refactoring:

1. **MySQL RDS Load Test and Failover**: Recently refactored example with similar functionality
2. **EC2 Windows Stop IIS**: Baseline example for structure and conventions

## Style Guide Compliance

Ensure all files comply with the style guide requirements:

- File naming conventions (kebab-case)
- README structure with required sections
- Proper JSON formatting
- Consistent tagging approach

## Testing Recommendations

After refactoring:

1. Validate JSON syntax for all template files
2. Ensure all file references are correct
3. Verify that the experiment can be imported into AWS FIS
4. Test the example infrastructure deployment (optional)

## Additional Notes

- The Aurora experiment should focus solely on the failover operation, not infrastructure deployment
- Examples should be clear and well-documented for users to adapt
- Consider adding diagrams or visuals if helpful (optional)
- Ensure all placeholder values are clearly marked for users to replace
