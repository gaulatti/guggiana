import { getTasksTableInstance } from '../../utils/dal/tasks';
import {
  instrumentHandler,
  observeDependency,
  recordWorkflowOutcome,
} from '../../utils/metrics';

const db = getTasksTableInstance(process.env.TABLE_NAME!);

/**
 * Handles the main logic for the Polly wait function.
 * @param event - The event object containing the necessary data.
 * @param _context - The context object.
 * @param _callback - The callback function.
 */
const handler = async (event: any, _context: any, _callback: any) => {
  const { textType, title, token, audioOutput } = event;

  const source =
    textType === 'title'
      ? title
      : textType === 'paragraph'
      ? audioOutput
      : null;

  if (source) {
    const {
      SynthesisTask: { TaskId, OutputUri },
    } = source;

    const currentDate = new Date();
    currentDate.setSeconds(currentDate.getSeconds() + 500);
    const unixTimestamp = Math.floor(currentDate.getTime() / 1000);

    if (TaskId && OutputUri) {
      await observeDependency('polly_wait', 'dynamodb', 'create', () =>
        db.create(TaskId, OutputUri, token, unixTimestamp)
      );
      recordWorkflowOutcome('polly_wait', 'success');
    } else {
      recordWorkflowOutcome('polly_wait', 'skipped');
    }
  } else {
    recordWorkflowOutcome('polly_wait', 'skipped');
  }
};

const main = instrumentHandler('polly_wait', handler);

export { main };
