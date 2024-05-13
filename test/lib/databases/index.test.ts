import { App, Stack } from 'aws-cdk-lib';
import { buildDatabases } from '../../../lib/databases';

test('Databases Aggregator succeeds', () => {
  const app = new App();
  const stack = new Stack(app, 'MyTestStack');
  const { contentTable, tasksTable } = buildDatabases(stack);
  expect(contentTable).not.toBeNull();
  expect(tasksTable).not.toBeNull();
});