# Contributing Guidelines

Thank you for your interest in contributing to our project. Whether it's a bug report, new feature, correction, or additional
documentation, we greatly value feedback and contributions from our community.

Please read through this document before submitting any issues or pull requests to ensure we have all the necessary
information to effectively respond to your bug report or contribution.


## Reporting Bugs/Feature Requests

We welcome you to use the GitHub issue tracker to report bugs or suggest features.

When filing an issue, please check existing open, or recently closed, issues to make sure somebody else hasn't already
reported the issue. Please try to include as much information as you can. Details like these are incredibly useful:

* A reproducible test case or series of steps
* The version of our code being used
* Any modifications you've made relevant to the bug
* Anything unusual about your environment or deployment


## Contributing FIS Experiment Templates

This repository contains AWS Fault Injection Service (FIS) experiment templates. When contributing new templates or modifying existing ones, please follow our comprehensive style guide.

**📋 [Read the complete FIS Template Style Guide](STYLE_GUIDE.md) before contributing**

### Template Contribution Checklist

Before submitting a FIS template, ensure you have:

- [ ] **Reviewed the style guide**: Read [STYLE_GUIDE.md](STYLE_GUIDE.md) thoroughly
- [ ] **Used the correct structure**: Follow the required directory and file naming conventions
- [ ] **Included all required files**: README.md, AWSFIS.json, template JSON, IAM policy, and trust relationship
- [ ] **Validated JSON files**: All JSON must be valid and properly formatted  
- [ ] **Included safety disclaimers**: Use exact disclaimer text as specified
- [ ] **Written comprehensive documentation**: Include hypothesis, prerequisites, and next steps
- [ ] **Followed security best practices**: IAM policies use least privilege with resource tag conditions
- [ ] **Used proper parameterization**: Replace account-specific values with `<YOUR AWS ACCOUNT>` placeholders
- [ ] **Added CloudWatch recommendations**: Include observability guidance in next steps
- [ ] **Referenced the gold standard**: Compare your template against `ec2-windows-stop-iis/` example
- [ ] **SSM document compliance**: If using SSM documents, follow comprehensive SSM best practices in the style guide

### Template Testing Requirements

Before submission, verify your template:

1. **JSON validation**: Use a JSON validator on all `.json` files
2. **Markdown validation**: Check formatting with a markdown linter  
3. **Deployment testing**: Test the template in a sandbox AWS environment
4. **Documentation accuracy**: Verify all instructions are clear and complete
5. **Security review**: Confirm IAM policies follow least privilege principles

## Contributing via Pull Requests
Contributions via pull requests are much appreciated. Before sending us a pull request, please ensure that:

1. You are working against the latest source on the *main* branch.
2. You check existing open, and recently merged, pull requests to make sure someone else hasn't addressed the problem already.
3. **For FIS templates**: You have completed the template checklist above and reviewed the [style guide](STYLE_GUIDE.md).
4. You open an issue to discuss any significant work - we would hate for your time to be wasted.

To send us a pull request, please:

1. Fork the repository.
2. Modify the source; please focus on the specific change you are contributing. If you also reformat all the code, it will be hard for us to focus on your change.
3. **For FIS templates**: Ensure your template follows the [style guide](STYLE_GUIDE.md) requirements.
4. Ensure local tests pass.
5. Commit to your fork using clear commit messages.
6. Send us a pull request, answering any default questions in the pull request interface.
7. Pay attention to any automated CI failures reported in the pull request, and stay involved in the conversation.

GitHub provides additional document on [forking a repository](https://help.github.com/articles/fork-a-repo/) and
[creating a pull request](https://help.github.com/articles/creating-a-pull-request/).


## Finding contributions to work on
Looking at the existing issues is a great way to find something to contribute on. As our projects, by default, use the default GitHub issue labels (enhancement/bug/duplicate/help wanted/invalid/question/wontfix), looking at any 'help wanted' issues is a great place to start.


## Code of Conduct
This project has adopted the [Amazon Open Source Code of Conduct](https://aws.github.io/code-of-conduct).
For more information see the [Code of Conduct FAQ](https://aws.github.io/code-of-conduct-faq) or contact
opensource-codeofconduct@amazon.com with any additional questions or comments.


## Security issue notifications
If you discover a potential security issue in this project we ask that you notify AWS/Amazon Security via our [vulnerability reporting page](http://aws.amazon.com/security/vulnerability-reporting/). Please do **not** create a public github issue.


## Licensing

See the [LICENSE](LICENSE) file for our project's licensing. We will ask you to confirm the licensing of your contribution.
