import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { buildPrePollyLambda } from './functions/pre_polly';
import { buildPollyListenerLambda } from './functions/polly_listener';
import { buildPollyWaitLambda } from './functions/polly_wait';
import { buildBucket } from './s3/bucket';
import { buildMergeFilesLambda } from './functions/merge_files';
import { buildPollyWorkflow } from './workflow';
import { buildTasksTable } from './databases/tasks';
import { buildContentTable } from './databases/content';
import { buildPreTranslateLambda } from './functions/pre_translate';
import { buildTriggerLambda } from './functions/trigger';
import { buildGetLambda } from './functions/get';

export class GuggianaStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const tasksTable = buildTasksTable(this);
    const contentTable = buildContentTable(this);

    const preTranslateLambda = buildPreTranslateLambda(this);
    const prePollyLambda = buildPrePollyLambda(this);
    const pollyListenerLambda = buildPollyListenerLambda(this, tasksTable);
    const pollyWaitLambda = buildPollyWaitLambda(this, tasksTable);
    const bucket = buildBucket(this, pollyListenerLambda);
    const mergeFilesLambda = buildMergeFilesLambda(this, contentTable, tasksTable, bucket);

    const workflow = buildPollyWorkflow(this, bucket, preTranslateLambda, prePollyLambda, mergeFilesLambda, pollyWaitLambda, pollyListenerLambda);

    const triggerLambda = buildTriggerLambda(this, contentTable, workflow);
    const getLambda = buildGetLambda(this, contentTable, bucket);
  }
}
