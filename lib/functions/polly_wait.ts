import { Duration, Stack } from 'aws-cdk-lib';
import { Table } from 'aws-cdk-lib/aws-dynamodb';
import { Runtime } from 'aws-cdk-lib/aws-lambda';
import { NodejsFunction } from 'aws-cdk-lib/aws-lambda-nodejs';

/**
 * Builds and returns a Polly Wait Lambda function.
 *
 * @param stack - The CloudFormation stack.
 * @param table - The DynamoDB table.
 * @returns The Polly Wait Lambda function.
 */
const buildPollyWaitLambda = (stack: Stack, table: Table) => {
  const pollyWaitLambda = new NodejsFunction(
    stack,
    `${stack.stackName}TextToSpeechPollyWaitLambda`,
    {
      functionName: `${stack.stackName}TextToSpeechPollyWait`,
      entry: './src/functions/tts/polly_wait.ts',
      handler: 'main',
      runtime: Runtime.NODEJS_20_X,
      timeout: Duration.minutes(1),
      environment: {
        TABLE_NAME: table.tableName,
      }
    }
  );

  /**
   * Grants the Lambda function read and write access to the table.
   */
  table.grantReadWriteData(pollyWaitLambda);

  return pollyWaitLambda;
};

export { buildPollyWaitLambda };
