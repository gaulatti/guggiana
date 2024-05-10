import { Duration, Stack } from 'aws-cdk-lib';
import { Table } from 'aws-cdk-lib/aws-dynamodb';
import { Runtime } from 'aws-cdk-lib/aws-lambda';
import { NodejsFunction } from 'aws-cdk-lib/aws-lambda-nodejs';

/**
 * Builds and returns a NodejsFunction for the Polly Listener Lambda.
 *
 * @param stack - The stack object.
 * @param table - The table object.
 * @returns The Polly Listener Lambda function.
 */
const buildPollyListenerLambda = (stack: Stack, table: Table) => {
  const pollyListenerLambda = new NodejsFunction(
    stack,
    `${stack.stackName}TextToSpeechPollyListenerLambda`,
    {
      functionName: `${stack.stackName}TextToSpeechPollyListener`,
      entry: './src/functions/tts/polly_listener.ts',
      handler: 'main',
      runtime: Runtime.NODEJS_20_X,
      timeout: Duration.minutes(1),
      environment: {
        TABLE_NAME: table.tableName,
      },
    }
  );

  /**
   * Grants the Lambda function read and write access to the table.
   */
  table.grantReadWriteData(pollyListenerLambda);

  return pollyListenerLambda;
};

export { buildPollyListenerLambda };
