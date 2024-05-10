import { Duration, Stack } from 'aws-cdk-lib';
import { Runtime } from 'aws-cdk-lib/aws-lambda';
import { NodejsFunction } from 'aws-cdk-lib/aws-lambda-nodejs';

/**
 * Builds and returns the pre-polly lambda function.
 *
 * @param stack - The AWS CloudFormation stack.
 * @returns The pre-polly lambda function.
 */
const buildPrePollyLambda = (stack: Stack) => {
  const prePollyLambda = new NodejsFunction(stack, `${stack.stackName}TextToSpeechPrePollyLambda`, {
    functionName: `${stack.stackName}TextToSpeechPrePolly`,
    entry: './src/functions/tts/pre_polly.ts',
    handler: 'main',
    runtime: Runtime.NODEJS_20_X,
    timeout: Duration.minutes(1),
  });

  return prePollyLambda;
};

export { buildPrePollyLambda };
