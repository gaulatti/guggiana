import { Duration, Stack } from 'aws-cdk-lib';
import { Table } from 'aws-cdk-lib/aws-dynamodb';
import { Runtime, StartingPosition } from 'aws-cdk-lib/aws-lambda';
import { DynamoEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import { NodejsFunction } from 'aws-cdk-lib/aws-lambda-nodejs';
import { StateMachine } from 'aws-cdk-lib/aws-stepfunctions';

/**
 * Builds and returns a trigger Lambda function for content-to-speech workflow.
 *
 * @param stack - The AWS CloudFormation stack.
 * @param table - The DynamoDB table.
 * @param stateMachine - The Step Functions state machine.
 * @returns The trigger Lambda function.
 */
const buildTriggerLambda = (stack: Stack, table: Table, stateMachine: StateMachine) => {
  /**
   * Creates a new trigger Lambda function.
   */
  const triggerLambda = new NodejsFunction(stack, `${stack.stackName}ContentToSpeechTrigger`, {
    functionName: `${stack.stackName}ContentToSpeechTrigger`,
    entry: './src/functions/workflows/content-to-speech/trigger.ts',
    handler: 'main',
    runtime: Runtime.NODEJS_20_X,
    timeout: Duration.minutes(1),
    environment: {
      STATE_MACHINE_ARN: stateMachine.stateMachineArn,
      TABLE_NAME: table.tableName,
    },
  });

  /**
   * Grants the state machine permission to start the execution.
   */
  stateMachine.grantStartExecution(triggerLambda);

  /**
   * Grants the Lambda function read and write access to the table.
   */
  table.grantReadWriteData(triggerLambda);

  /**
   * Adds a DynamoDB event source to the Lambda function.
   */
  triggerLambda.addEventSource(
    new DynamoEventSource(table, {
      batchSize: 1,
      startingPosition: StartingPosition.LATEST,
    })
  );

  return triggerLambda;
};

export { buildTriggerLambda };
