import { RemovalPolicy, Stack } from 'aws-cdk-lib';
import { NodejsFunction } from 'aws-cdk-lib/aws-lambda-nodejs';
import { Bucket, EventType } from 'aws-cdk-lib/aws-s3';
import { LambdaDestination } from 'aws-cdk-lib/aws-s3-notifications';

/**
 * Builds a bucket for text-to-speech functionality.
 *
 * @param stack - The AWS CloudFormation stack.
 * @param pollyListenerLambda - The Lambda function for Polly listener.
 * @returns The created bucket.
 */
const buildBucket = (stack: Stack, pollyListenerLambda: NodejsFunction) => {
  /**
   * Creates a bucket for text-to-speech functionality.
   */
  const bucket = new Bucket(stack, `${stack.stackName}TextToSpeechBucket`, {
    bucketName: `${stack.stackName.toLowerCase()}-text-to-speech`,
    removalPolicy: RemovalPolicy.DESTROY,
  });

  /**
   * Adds an event notification for the bucket.
   */
  const prefix = 'audio/';
  bucket.addEventNotification(EventType.OBJECT_CREATED, new LambdaDestination(pollyListenerLambda), { prefix });

  return bucket;
};

export { buildBucket };
