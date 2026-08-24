import { SFNClient, SendTaskSuccessCommand } from '@aws-sdk/client-sfn';
import { TaskStatus, getTasksTableInstance } from '../../utils/dal/tasks';
import {
  instrumentHandler,
  observeDependency,
  recordWorkflowBacklog,
  recordWorkflowBatch,
  recordWorkflowOutcome,
} from '../../utils/metrics';

const client = new SFNClient({});
const db = getTasksTableInstance(process.env.TABLE_NAME!);

/**
 * Handles the main logic for the Polly listener.
 *
 * @param event - The event object containing the records.
 * @param _context - The context object.
 * @param callback - The callback function.
 */
const handler = async (event: any, _context: any, callback: any) => {
  const { Records } = event;

  if (!Records && !Records.length) {
    recordWorkflowBatch('polly_listener', 0);
    recordWorkflowOutcome('polly_listener', 'skipped');
    return callback(null, 'No records found');
  }
  recordWorkflowBatch('polly_listener', Records.length);

  const items = Records.filter(
    ({ eventName }: any) => eventName === 'ObjectCreated:Put'
  ).map((item: any) => {
    const {
      s3: {
        bucket: { name },
        object: { key },
      },
    } = item;

    return `https://s3.us-east-1.amazonaws.com/${name}/${key}`;
  });

  const dbItems = await observeDependency(
    'polly_listener',
    'dynamodb',
    'list',
    () => db.list()
  );
  recordWorkflowBacklog('polly_listener', dbItems.length);

  for (const item in items) {
    const dbItem = dbItems.find(({ url }) => url == items[item]);

    if (dbItem) {
      await observeDependency('polly_listener', 'dynamodb', 'update', () =>
        db.updateStatus(dbItem.uuid, TaskStatus.DELIVERED)
      );

      const input = {
        taskToken: dbItem.token,
        output: JSON.stringify({ url: dbItem.url }),
      };
      const command = new SendTaskSuccessCommand(input);
      await observeDependency('polly_listener', 'step_functions', 'send_task', () =>
        client.send(command)
      );
      recordWorkflowOutcome('polly_listener', 'success');
    } else {
      recordWorkflowOutcome('polly_listener', 'skipped');
    }

    // if (!dbItem) {
    // console.error('[Listener] Item not found, creating');
    // }

    // console.log({dbItem});
  }

  // const { detail, resources, 'detail-type': detailType } = event;
  // console.log(JSON.stringify(event), detail, resources, detailType);

  //   import { SFNClient, SendTaskSuccessCommand } from "@aws-sdk/client-sfn"; // ES Modules import
  // // const { SFNClient, SendTaskSuccessCommand } = require("@aws-sdk/client-sfn"); // CommonJS import
  // const client = new SFNClient(config);
  // const input = { // SendTaskSuccessInput
  //   taskToken: "STRING_VALUE", // required
  //   output: "STRING_VALUE", // required
  // };
  // const command = new SendTaskSuccessCommand(input);
  // const response = await client.send(command);
  // // {};

  // import { SFNClient, SendTaskFailureCommand } from "@aws-sdk/client-sfn"; // ES Modules import
  // // const { SFNClient, SendTaskFailureCommand } = require("@aws-sdk/client-sfn"); // CommonJS import
  // const client = new SFNClient(config);
  // const input = { // SendTaskFailureInput
  //   taskToken: "STRING_VALUE", // required
  //   error: "STRING_VALUE",
  //   cause: "STRING_VALUE",
  // };
  // const command = new SendTaskFailureCommand(input);
  // const response = await client.send(command);
  // // {};
};

const main = instrumentHandler('polly_listener', handler);

export { main };
