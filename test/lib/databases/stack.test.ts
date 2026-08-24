import { App } from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { GuggianaStack } from '../../../lib/guggiana-stack';

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

  const functions = template.findResources('AWS::Lambda::Function');
  const instrumentedFunctions = Object.values(functions).filter(
    (resource: any) =>
      resource.Properties.Environment?.Variables?.GUGGIANA_BUILD_VERSION
  );
  expect(instrumentedFunctions).toHaveLength(7);
  instrumentedFunctions.forEach((resource: any) => {
    expect(resource.Properties.Environment.Variables).toEqual(
      expect.objectContaining({ GUGGIANA_BUILD_VERSION: '0.1.0' })
    );
  });
});
