import { Stack } from 'aws-cdk-lib';
import {
  AttributeType,
  BillingMode,
  StreamViewType,
  Table,
} from 'aws-cdk-lib/aws-dynamodb';

/**
 * Builds a tasks table in the specified stack.
 *
 * @param stack - The stack in which the table will be created.
 * @returns The created tasks table.
 */
const buildTasksTable = (stack: Stack) => {
  const table: Table = new Table(stack, `${stack.stackName}TasksTable`, {
    tableName: `${stack.stackName}Tasks`,
    partitionKey: { name: 'uuid', type: AttributeType.STRING },
    stream: StreamViewType.NEW_IMAGE,
    billingMode: BillingMode.PAY_PER_REQUEST,
    timeToLiveAttribute: 'ttl',
  });

  table.addGlobalSecondaryIndex({
    indexName: 'UrlIndex',
    partitionKey: { name: 'url', type: AttributeType.STRING },
  });

  return table;
};

export { buildTasksTable };
