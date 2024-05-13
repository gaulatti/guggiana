import { App } from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { GuggianaStack } from '../lib/guggiana-stack';

test('Databases created', () => {
  const app = new App();
  const stack = new GuggianaStack(app, 'MyTestStack');
  const template = Template.fromStack(stack);

  template.hasResourceProperties('AWS::DynamoDB::Table', {
    TableName: `${stack.stackName}Content`,
    BillingMode: 'PAY_PER_REQUEST',
  });

  template.hasResourceProperties('AWS::DynamoDB::Table', {
    TableName: `${stack.stackName}Tasks`,
    BillingMode: 'PAY_PER_REQUEST',
  });
});
