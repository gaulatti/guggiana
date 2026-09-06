import { SFNClient, StartExecutionCommand } from '@aws-sdk/client-sfn';
import { unmarshall } from '@aws-sdk/util-dynamodb';
import axios from 'axios';
import { load } from 'cheerio';
import { getContentTableInstance } from '../../../utils/dal/content';
import {
  instrumentHandler,
  observeDependency,
  recordRenditionRequest,
  recordRenditionResult,
  recordWorkflowBatch,
  recordWorkflowOutcome,
} from '../../../utils/metrics';
import {
  RENDITION_CLAIM_EXPIRY_MS,
  cachedLocales,
  claimableLocales,
  classify,
  languageObjectsFor,
  normalizeLocales,
} from '../../../utils/renditions';

const db = getContentTableInstance(process.env.TABLE_NAME!);
const client = new SFNClient();

/**
 * Fetches and parses an article from a given URL.
 * @param url - The URL of the article to fetch and parse.
 * @returns An object containing the title, byline, and text of the article.
 */
const fetchAndParseArticle = async (url: string) => {
  /**
   * Fetch the article content.
   */
  const response = await observeDependency('trigger', 'http', 'fetch', () =>
    axios.get(`https://lite.cnn.com${url}`)
  );
  const html = response.data;
  const $ = load(html);

  /**
   * Parse the article content.
   */
  const title = $('.headline').text().trim();
  const byline = $('.byline--lite').text().trim();
  const text = $('.paragraph--lite:not(:last-child)')
    .map((_index, element) => $(element).text().trim())
    .get()
    .join('\n');

  return { title, byline, text };
};

/**
 * Starts the execution of a Step Function workflow.
 *
 * @param uuid - The UUID of the workflow.
 * @param url - The URL of the content.
 * @param title - The title of the content.
 * @param text - The text of the content.
 * @param byline - The byline of the content.
 * @param language - The language of the content.
 * @returns A promise that resolves to the execution details.
 */
const startStepFunctionExecution = async (uuid: string, url: string, title: string, text: string, byline: string, language: any) => {
  const input = {
    stateMachineArn: process.env.STATE_MACHINE_ARN,
    name: `${uuid}-${language.code}`,
    input: JSON.stringify({ uuid, url, title, text, byline, language }),
  };
  const command = new StartExecutionCommand(input);
  const execution = await observeDependency(
    'trigger',
    'step_functions',
    'start_execution',
    () => client.send(command)
  );
  return execution;
};

/**
 * The locales a content record has asked for, normalized to the canonical
 * supported order. An unsupported or absent request materializes nothing:
 * there is no implicit expansion to every locale.
 */
const requestedLocalesFor = (item: any): string[] => {
  const requested = Array.isArray(item?.requestedLocales)
    ? item.requestedLocales.filter((code: unknown) => typeof code === 'string')
    : [];
  if (requested.length === 0) return [];
  try {
    return normalizeLocales(requested);
  } catch {
    return [];
  }
};

/**
 * Materializes exactly the locales that are requested, not cached, and not
 * already claimed by a live execution.
 *
 * Each locale is claimed with a single atomic conditional write, so concurrent
 * stream events converge on one execution per locale rather than duplicating
 * translation and synthesis. Each locale is also isolated: one failure marks
 * only that locale for retry and never aborts the others.
 *
 * @returns The locales for which an execution was started.
 */
const materializeRenditions = async (
  uuid: string,
  url: string,
  item: any,
  codes: string[],
  now: number
): Promise<string[]> => {
  const localeClass = classify(codes);
  const claimedAt = new Date(now).toISOString();
  const expiredBefore = new Date(now - RENDITION_CLAIM_EXPIRY_MS).toISOString();

  const { title, byline, text } = await fetchAndParseArticle(url);
  await observeDependency('trigger', 'dynamodb', 'update', () =>
    db.updateTitle(uuid, title)
  );

  const started: string[] = [];
  let reused = 0;
  let failed = 0;

  for (const language of languageObjectsFor(codes)) {
    const claimed = await observeDependency('trigger', 'dynamodb', 'update', () =>
      db.claimRendition(uuid, language.code, claimedAt, expiredBefore)
    );
    if (!claimed) {
      reused += 1;
      continue;
    }
    try {
      const execution = await startStepFunctionExecution(uuid, url, title, text, byline, language);
      started.push(language.code);
      console.log(`Step Function execution started`, {
        title,
        language,
        execution,
      });
    } catch (error) {
      /**
       * Release the claim so this locale can be retried without blocking the
       * locales that did start.
       */
      failed += 1;
      await observeDependency('trigger', 'dynamodb', 'update', () =>
        db.updateRenditionStatus(uuid, language.code, 'failed')
      );
      console.error(`Failed to start ${language.code} rendition`, error);
    }
  }

  recordRenditionResult('trigger', localeClass, 'miss', started.length);
  recordRenditionResult('trigger', localeClass, 'reused', reused);
  recordRenditionResult('trigger', localeClass, 'failed', failed);
  return started;
};

/**
 * Main function that processes the event records and triggers the
 * content-to-speech workflow for the locales a caller actually asked for.
 *
 * Renditions are materialized lazily. An inserted article generates nothing on
 * its own; it generates the locales recorded on the item, and a later request
 * that adds a locale arrives here as a modification.
 *
 * @param event - The event object containing the records to process.
 */
const handler = async (event: any) => {
  recordWorkflowBatch('trigger', event.Records.length);
  const now = Date.now();

  for (const record of event.Records) {
    if (record.eventName !== 'INSERT' && record.eventName !== 'MODIFY') {
      recordWorkflowOutcome('trigger', 'skipped');
      continue;
    }

    const item = unmarshall(record.dynamodb.NewImage);
    const uuid: string = item.uuid;
    const url: string = item.url;
    const codes = requestedLocalesFor(item);

    if (codes.length === 0) {
      recordWorkflowOutcome('trigger', 'skipped');
      continue;
    }

    const localeClass = classify(codes);
    recordRenditionRequest('trigger', localeClass, codes.length);
    recordRenditionResult(
      'trigger',
      localeClass,
      'hit',
      cachedLocales(item, codes).length
    );

    /**
     * Nothing to do when every requested locale is already stored or already
     * claimed by a live execution. Checking before fetching is what avoids the
     * article download and the translation and synthesis work.
     */
    const pending = claimableLocales(item, codes, now);
    if (pending.length === 0) {
      recordWorkflowOutcome('trigger', 'skipped');
      continue;
    }

    try {
      await materializeRenditions(uuid, url, item, pending, now);
      recordWorkflowOutcome('trigger', 'success');
    } catch (error) {
      recordWorkflowOutcome('trigger', 'failure');
      console.error('Error:', error);
    }
  }
};

const main = instrumentHandler('trigger', handler);

export {
  fetchAndParseArticle,
  main,
  materializeRenditions,
  requestedLocalesFor,
  startStepFunctionExecution,
};
