import { Duration, Stack } from 'aws-cdk-lib';
import { Table } from 'aws-cdk-lib/aws-dynamodb';
import { Effect, PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { LayerVersion, Runtime } from 'aws-cdk-lib/aws-lambda';
import { NodejsFunction } from 'aws-cdk-lib/aws-lambda-nodejs';
import { Bucket } from 'aws-cdk-lib/aws-s3';

/**
 * Builds and returns a Lambda function for merging files.
 *
 * @param stack - The AWS CloudFormation stack.
 * @param contentTable - The DynamoDB table for content.
 * @param tasksTable - The DynamoDB table for tasks.
 * @param bucket - The S3 bucket.
 * @returns The Lambda function for merging files.
 */
const buildMergeFilesLambda = (
  stack: Stack,
  contentTable: Table,
  tasksTable: Table,
  bucket: Bucket
) => {
  /**
   * The ARN of the ffmpeg layer.
   */
  const ffmpegLayerArn = `arn:aws:lambda:us-east-1:${stack.account}:layer:ffmpeg:1`;
  const ffmpegLayer = LayerVersion.fromLayerVersionArn(
    stack,
    'ffmpegLayer',
    ffmpegLayerArn
  );

  /**
   * The Lambda function for merging files.
   */
  const mergeFilesLambda = new NodejsFunction(
    stack,
    `${stack.stackName}TextToSpeechMergeFilesLambda`,
    {
      functionName: `${stack.stackName}TextToSpeechMergeFiles`,
      entry: './src/functions/tts/merge_files.ts',
      handler: 'main',
      layers: [ffmpegLayer],
      runtime: Runtime.NODEJS_20_X,
      timeout: Duration.seconds(15),
      memorySize: 512,
      environment: {
        BUCKET_NAME: bucket.bucketName,
        TABLE_NAME: contentTable.tableName,
      },
    }
  );

  /**
   * The policy statement for sending task success.
   */
  const sendTaskSuccessPolicy = new PolicyStatement({
    effect: Effect.ALLOW,
    actions: ['states:SendTaskSuccess', 'states:SendTaskFailure'],
    resources: ['*'],
  });

  /**
   * Grants permissions to the Lambda function.
   */
  mergeFilesLambda.role?.addToPrincipalPolicy(sendTaskSuccessPolicy);
  contentTable.grantReadWriteData(mergeFilesLambda);
  tasksTable.grantReadWriteData(mergeFilesLambda);
  bucket.grantReadWrite(mergeFilesLambda);

  return mergeFilesLambda;
};

export { buildMergeFilesLambda };
