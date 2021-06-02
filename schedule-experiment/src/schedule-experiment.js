const { FisClient, StartExperimentCommand } = require("@aws-sdk/client-fis");
const fis = new FisClient({ region: process.env.AWS_REGION });

const experimentTemplateId = process.env.EXPERIMENT_TEMPLATE_ID;

exports.handler = async (event, context, callback) => {
  const params = {
    clientToken: event.id,
    experimentTemplateId: experimentTemplateId,
  };
  try {
    const data = await fis.send(new StartExperimentCommand(params));
    console.log("Experiment started", data);
  } catch (err) {
    console.log("Error", err);
  }
};
