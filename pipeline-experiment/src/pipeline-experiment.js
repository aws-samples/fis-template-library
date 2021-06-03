const { FisClient, StartExperimentCommand } = require("@aws-sdk/client-fis");
const { CodePipelineClient, PutJobSuccessResultCommand, PutJobFailureResultCommand } = require("@aws-sdk/client-codepipeline");
const fis = new FisClient({ region: process.env.AWS_REGION });
const codepipeline = new CodePipelineClient({ region: process.env.AWS_REGION });

exports.handler = async (event, context, callback) => {
  const jobId = event["CodePipeline.job"].id;
  const requestId = context.awsRequestId;
  const experimentTemplateId = event["CodePipeline.job"].data.actionConfiguration.configuration.UserParameters;
  const params = {
    clientToken: jobId,
    experimentTemplateId: experimentTemplateId,
  };
  try {
    const data = await fis.send(new StartExperimentCommand(params));
    const jobParams = {
      jobId: jobId,
      outputVariables: {
        experimentId: data.experiment.id,
      }
    };
    const jobData = await codepipeline.send(new PutJobSuccessResultCommand(jobParams));
    console.log("Experiment started", data);
  } catch (err) {
    const jobParams = {
      jobId: jobId,
      failureDetails: {
        message: JSON.stringify(err),
        type: "JobFailed",
        externalExecutionId: requestId,
      },
    };
    const jobData = await codepipeline.send(new PutJobFailureResultCommand(jobParams));
    console.log("Error", err);
  }
};
