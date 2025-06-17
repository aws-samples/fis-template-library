# FIS Template Library Style Guide

This document outlines the requirements, structure, and style guidelines for contributing AWS Fault Injection Service (FIS) experiment templates to this repository.

## Directory Structure Requirements

Each experiment template must follow this exact directory structure:

```
experiment-name/
├── README.md                              # Main documentation (required)
├── AWSFIS.json                           # Template version marker (required)
├── experiment-name-template.json         # FIS experiment template (required)
├── experiment-name-iam-policy.json       # IAM policy document (required)
├── fis-iam-trust-relationship.json       # Trust relationship (required)
├── experiment-name-ssm-template.json     # SSM document template (if applicable)
├── experiment-name-automation.yaml       # SSM automation document (if applicable)
└── images/                               # Screenshots and diagrams (optional)
    └── diagram.png
```

### File Naming Conventions

- **Directory name**: Use kebab-case (lowercase with hyphens): `ec2-windows-stop-iis`
- **Template files**: Follow pattern `{experiment-name}-{type}.json`
- **README**: Always `README.md` (uppercase)
- **AWSFIS marker**: Always `AWSFIS.json` (uppercase)
- **Trust relationship**: Always `fis-iam-trust-relationship.json`

## README.md Structure Requirements

### Required Sections (in order)

#### 1. Title
```markdown
# AWS Fault Injection Service Experiment: [Descriptive Title]
```

#### 2. Template Description
```markdown
This is an experiment template for use with AWS Fault Injection Service (FIS) and fis-template-library-tooling. This experiment template requires deployment into your AWS account and requires resources in your AWS account to inject faults into.
```

#### 3. Disclaimer (required - exact text)
```markdown
THIS TEMPLATE WILL INJECT REAL FAULTS! THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE
```

#### 4. Hypothesis
State the expected behavior and outcome of the experiment:
```markdown
## Hypothesis

[Clear statement about what you expect to happen and how the system should respond]
```

#### 5. Prerequisites
Detailed checklist of requirements:
```markdown
## Prerequisites

Before running this experiment, ensure that:

1. You have the necessary permissions to execute the FIS experiment and perform [specific actions].
2. The IAM role specified in the `roleArn` field has the required permissions to perform the [specific operation].
3. The [target resources] you want to target have the `FIS-Ready=True` tag.
4. [Any additional specific requirements for the experiment]
```

#### 6. How it works (optional but recommended)
Explain the technical details of what the experiment does.

#### 7. Stop Conditions
```markdown
## Stop Conditions

The experiment does not have any specific stop conditions defined. It will continue to run until manually stopped or until [completion condition].
```

#### 8. Observability and stop conditions (required - exact text)
```markdown
## Observability and stop conditions

Stop conditions are based on an AWS CloudWatch alarm based on an operational or 
business metric requiring an immediate end of the fault injection. This 
template makes no assumptions about your application and the relevant metrics 
and does not include stop conditions by default.
```

#### 9. Next Steps (required)
```markdown
## Next Steps
As you adapt this scenario to your needs, we recommend:
1. Reviewing the tag names you use to ensure they fit your specific use case.
2. Identifying business metrics tied to [relevant service/component].
3. Creating an Amazon CloudWatch metric and Amazon CloudWatch alarm to monitor the impact of [the fault].
4. Adding a stop condition tied to the alarm to automatically halt the experiment if critical thresholds are breached.
5. [Any experiment-specific recommendations]
```

#### 10. Import Experiment (required - exact text)
```markdown
## Import Experiment
You can import the json experiment template into your AWS account via cli or aws cdk. For step by step instructions on how, [click here](https://github.com/aws-samples/fis-template-library-tooling).
```

### Optional Sections
- **Description**: Brief overview of the experiment
- **Images**: Include relevant diagrams with `![Alt text](images/filename.png)`

## JSON File Requirements

### AWSFIS.json (required)
Must contain exactly:
```json
{
    "AWSFIS": {
        "template": {
            "version": "1.0"
        }
    }
}
```

### Experiment Template JSON Structure
Required fields:
- `description`: Clear, concise description
- `targets`: Properly configured resource targeting
- `actions`: Well-defined actions with appropriate parameters
- `stopConditions`: At minimum `[{"source": "none"}]`
- `roleArn`: Parameterized with `<YOUR AWS ACCOUNT>` and `<YOUR ROLE NAME>`
- `tags`: Include experiment identification tags
- `experimentOptions`: Include `accountTargeting` and `emptyTargetResolutionMode`

### Parameterization Standards
Use these exact placeholders:
- `<YOUR REGION>`: For AWS region
- `<YOUR AWS ACCOUNT>`: For AWS account ID
- `<YOUR ROLE NAME>`: For IAM role names
- Other descriptive placeholders in angle brackets as needed

### Resource Targeting Requirements
- Use consistent tagging strategy: `FIS-Ready=True`
- Include appropriate resource conditions
- Use descriptive target names

## IAM Policy Requirements

### Policy Structure
- **Version**: Must be `"2012-10-17"`
- **Statements**: Organized by service and action type
- **Resources**: Specific resource ARNs where possible
- **Conditions**: Include resource tag conditions for security

### Required Permissions Categories
1. **FIS permissions**: `fis:StartExperiment`, `fis:GetExperimentSummary`, etc.
2. **Service-specific permissions**: Based on the fault being injected
3. **CloudWatch Logs**: For experiment logging
4. **Resource conditions**: Tag-based restrictions

### Security Best Practices
- Use least privilege principle
- Include resource tag conditions: `"aws:ResourceTag/FIS-Ready": "True"`
- Scope permissions to necessary resources only
- Use specific resource ARNs when possible

## Trust Relationship Requirements

Use exactly this format:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "fis.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
        }
    ]
}
```

## SSM Document Requirements

When experiments use AWS Systems Manager (SSM) documents for custom fault injection, follow these comprehensive best practices:

### Document Structure

#### Modular Design
Break documents into distinct, logical steps for better error handling and reusability:
```json
"mainSteps": [
    {
        "action": "aws:runPowerShellScript",
        "name": "ValidatePrerequisites",
        "onFailure": "exit"
    },
    {
        "action": "aws:runPowerShellScript", 
        "name": "ExecuteFaultInjection",
        "onFailure": "exit"
    },
    {
        "action": "aws:runPowerShellScript",
        "name": "RestoreService",
        "isFinalStep": true
    }
]
```

#### Parameter Definitions
Define clear, validated parameters:
```json
"parameters": {
    "ServiceName": {
        "type": "String",
        "default": "DefaultAppPool",
        "description": "Name of the service to target",
        "allowedPattern": "^[a-zA-Z0-9_-]{1,50}$"
    },
    "DurationSeconds": {
        "type": "String",
        "default": "300",
        "description": "Duration in seconds for the fault injection",
        "allowedPattern": "^[1-9][0-9]{0,3}$"
    }
}
```

### Cross-Platform Support

#### OS Detection
Implement OS detection for cross-platform compatibility:
```bash
# Detect Amazon Linux
if [ -f "/etc/system-release" ] && grep -i 'Amazon Linux' /etc/system-release; then
    if ! grep -Fiq 'VERSION_ID="2023"' /etc/os-release; then
        # Amazon Linux 2 or earlier
        yum -y install <package>
    elif grep -Fiq 'ID="amzn"' /etc/os-release && grep -Fiq 'VERSION_ID="2023"' /etc/os-release; then
        # Amazon Linux 2023
        yum -y install <package>
    fi
# Detect CentOS/RHEL
elif grep -Fiq 'ID="centos"' /etc/os-release || grep -Fiq 'ID="rhel"' /etc/os-release; then
    yum -y install <package>
fi
```

#### Preconditions
Use preconditions for platform-specific execution:
```json
{
    "action": "aws:runShellScript",
    "name": "LinuxCommands",
    "precondition": {
        "StringEquals": ["platformType", "Linux"]
    },
    "onFailure": "exit"
},
{
    "action": "aws:runPowerShellScript",
    "name": "WindowsCommands", 
    "precondition": {
        "StringEquals": ["platformType", "Windows"]
    },
    "onFailure": "exit"
}
```

### Code Quality Standards

#### Idempotency
Ensure scripts can run multiple times safely:
```powershell
# Check if experiment is already running
if (Test-Path -Path 'C:\temp\fis_experiment_marker.json') {
    Write-Host "ERROR: Experiment already running. Exiting."
    Exit 1
}

# Verify service exists before operations
if (-not (Get-Service -Name {{ServiceName}} -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Service {{ServiceName}} not found"
    Exit 1
}
```

#### Proper Timeouts
Set appropriate timeouts for each step:
```json
{
    "action": "aws:runShellScript",
    "name": "StopService",
    "inputs": {
        "timeoutSeconds": 60,
        "runCommand": ["#!/bin/bash", "# Script content here"]
    }
}
```

#### Comprehensive Logging
Implement structured logging throughout:
```powershell
function Write-Log {
    param($Message)
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Write-Host "[$timestamp] $Message"
}

Write-Log "Starting fault injection on service: {{ServiceName}}"
Write-Log "Duration: {{DurationSeconds}} seconds"
```

### Fault Injection Best Practices

#### State Management
Track experiment state using marker files:
```powershell
# Create experiment marker
$experimentData = @{
    StartTime = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    ServiceName = '{{ServiceName}}'
    OriginalState = $serviceState
} | ConvertTo-Json

$experimentData | Out-File -FilePath 'C:\temp\fis_experiment_marker.json'
```

#### Duration Management
Handle experiment timing properly:
```powershell
$start_time = Get-Date
$elapsed_time = ((Get-Date) - $start_time).TotalSeconds
$remaining_time = {{DurationSeconds}} - $elapsed_time

if ($remaining_time -gt 0) {
    Write-Log "Waiting for remaining time: $remaining_time seconds"
    Start-Sleep -Seconds $remaining_time
}
```

#### Service State Restoration
Ensure proper service restoration:
```powershell
try {
    Write-Log "Restoring service: {{ServiceName}}"
    Start-Service -Name {{ServiceName}}
    
    # Verify restoration
    $restoredService = Get-Service -Name {{ServiceName}}
    if ($restoredService.Status -ne 'Running') {
        throw "Failed to restore service to running state"
    }
    Write-Log "Service restored successfully"
}
catch {
    Write-Log "ERROR during restoration: $($_.Exception.Message)"
    throw
}
```

### Error Handling and Cleanup

#### Comprehensive Error Handling
Implement robust error handling during rollback:
```powershell
try {
    # Main fault injection logic
}
catch {
    Write-Log "ERROR during fault injection: $($_.Exception.Message)"
    # Attempt immediate restoration
    try {
        Start-Service -Name {{ServiceName}}
    }
    catch {
        Write-Log "CRITICAL: Failed to restore service during error handling"
    }
    throw
}
finally {
    # Cleanup that must happen regardless
    if (Test-Path -Path 'C:\temp\fis_experiment_marker.json') {
        Remove-Item -Path 'C:\temp\fis_experiment_marker.json' -Force
    }
}
```

#### Mandatory Cleanup Procedures
Always implement cleanup in finally blocks:
```bash
# Linux cleanup example
cleanup() {
    echo 'Performing cleanup operations'
    rm -f /tmp/fis_experiment_marker.json
    
    # Restore service if needed
    if ! systemctl is-active --quiet {{ServiceName}}; then
        echo 'Restoring service during cleanup'
        sudo systemctl start {{ServiceName}}
    fi
}

# Set trap for cleanup on script exit
trap cleanup EXIT
```

### Environment Configuration

#### Use AWS Environment Variables
Leverage built-in environment variables instead of hardcoding:
```bash
# Good - uses environment variable
aws ssm get-parameter --name "/app/config" --region $AWS_SSM_REGION_NAME

# Bad - hardcoded region
aws ssm get-parameter --name "/app/config" --region us-east-1
```

#### Failure Handling Strategy
Use appropriate onFailure settings:
```json
{
    "action": "aws:runShellScript",
    "name": "ValidatePrerequisites",
    "onFailure": "exit",  // Fail experiment if prerequisites not met
    "inputs": {
        "runCommand": ["# Validation logic"]
    }
}
```

### SSM Document Validation Checklist

Before submitting SSM documents, verify:

#### Structure and Logic
- [ ] Modular step design with clear separation of concerns
- [ ] Proper preconditions for platform-specific logic
- [ ] Appropriate onFailure settings for each step
- [ ] Clear parameter definitions with validation patterns

#### Cross-Platform Support
- [ ] OS detection logic implemented where needed
- [ ] Platform-specific commands properly isolated
- [ ] Environment variables used instead of hardcoded values

#### Fault Injection Quality
- [ ] Idempotency checks implemented
- [ ] State tracking with marker files
- [ ] Proper duration management
- [ ] Service state verification

#### Error Handling and Recovery
- [ ] Comprehensive try/catch blocks
- [ ] Proper cleanup in finally blocks
- [ ] Service restoration verification
- [ ] Error logging with sufficient detail

#### Code Quality
- [ ] Consistent logging throughout execution
- [ ] Appropriate timeouts set for all steps
- [ ] Clear variable naming and comments
- [ ] Input validation and sanitization

## Content Style Guidelines

### Tone and Voice
- **Professional and technical**: Clear, concise, authoritative
- **Safety-conscious**: Emphasize the real impact of fault injection
- **Instructional**: Provide clear, actionable guidance

### Language Requirements
- Use active voice where possible
- Be specific about requirements and prerequisites
- Use consistent terminology throughout
- Avoid assumptions about user knowledge

### Technical Accuracy
- All JSON must be valid and properly formatted
- Resource ARNs must follow AWS formatting standards
- Service names and actions must be accurate
- Region and account placeholders must be consistent

## Quality Checklist

Before submitting a template, verify:

### File Structure
- [ ] All required files are present
- [ ] File naming follows conventions
- [ ] Directory structure is correct

### README.md
- [ ] All required sections are present and in order
- [ ] Disclaimer text is exact and complete
- [ ] Hypothesis is clear and testable
- [ ] Prerequisites are comprehensive
- [ ] Next steps include CloudWatch recommendations
- [ ] Import link is included

### JSON Files
- [ ] All JSON files are valid (use a JSON validator)
- [ ] AWSFIS.json has correct structure
- [ ] Template includes all required fields
- [ ] IAM policy follows least privilege
- [ ] Trust relationship is correct
- [ ] Placeholders use correct format

### Content Quality
- [ ] Technical accuracy verified
- [ ] No spelling or grammar errors
- [ ] Consistent terminology used
- [ ] Safety warnings appropriate
- [ ] Instructions are clear and complete

## Examples and Templates

Refer to `ec2-windows-stop-iis/` as the gold standard example that demonstrates all requirements and best practices.

The `templates/` directory contains boilerplate files that can be used as starting points for new experiments.

## Common Mistakes to Avoid

1. **Inconsistent file naming**: Always use kebab-case for directories and follow naming patterns
2. **Missing disclaimer**: The exact disclaimer text is required for legal compliance
3. **Incomplete IAM policies**: Ensure all necessary permissions are included
4. **Invalid JSON**: Always validate JSON files before submission
5. **Missing placeholders**: Use proper parameterization for account-specific values
6. **Inadequate prerequisites**: List all requirements, including tags and permissions
7. **Missing CloudWatch recommendations**: Always include observability guidance
8. **Inconsistent tagging**: Use `FIS-Ready=True` consistently across templates

## Validation Tools

Before submitting:
1. Use a JSON validator on all `.json` files
2. Check markdown formatting with a markdown linter
3. Verify all links are functional
4. Test template deployment in a sandbox environment
5. Review against this style guide checklist
