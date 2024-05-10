import { Duration, Stack } from 'aws-cdk-lib';
import { Runtime } from 'aws-cdk-lib/aws-lambda';
import { NodejsFunction } from 'aws-cdk-lib/aws-lambda-nodejs';

/**
 * Builds and returns a pre-translate lambda function.
 *
 * @param stack - The stack object.
 * @returns The pre-translate lambda function.
 */
const buildPreTranslateLambda = (stack: Stack) => {
  const preTranslateLambda = new NodejsFunction(stack, `${stack.stackName}TextPreTranslateLambda`, {
    functionName: `${stack.stackName}TextPreTranslate`,
    entry: './src/functions/translate/pre_translate.ts',
    handler: 'main',
    runtime: Runtime.NODEJS_20_X,
    timeout: Duration.minutes(1),
  });

  return preTranslateLambda;
};

export { buildPreTranslateLambda };
