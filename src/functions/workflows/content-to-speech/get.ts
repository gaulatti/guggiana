import { GetObjectCommand, GetObjectCommandInput, GetObjectCommandOutput, S3Client } from '@aws-sdk/client-s3';
import { S3RequestPresigner } from '@aws-sdk/s3-request-presigner';
import { createRequest } from '@aws-sdk/util-create-request';
import { formatUrl } from '@aws-sdk/util-format-url';
import { randomUUID } from 'crypto';
import { checkLanguagesPresent, delay, extractPathWithTrailingSlash } from '../../../utils';
import { getContentTableInstance } from '../../../utils/dal/content';
import {
  instrumentHandler,
  observeDependency,
  recordRetry,
  recordWorkflowOutcome,
} from '../../../utils/metrics';

const db = getContentTableInstance(process.env.TABLE_NAME!);
const client = new S3Client();
const presigner = new S3RequestPresigner(client.config);

/**
 * Parses an S3 URL and extracts the bucket name and key.
 * @param url - The S3 URL to parse.
 * @returns An object containing the bucket name and key.
 * @throws Error if the URL is invalid.
 */
function parseS3Url(url: string) {
  const match = url.match(/https:\/\/s3\..+\.amazonaws\.com\/([^\/]+)\/(.+)/);
  if (!match || match.length !== 3) {
    throw new Error('Invalid S3 URL');
  }
  return {
    Bucket: match[1],
    Key: decodeURIComponent(match[2]),
  };
}

/**
 * Main function that processes the event and returns the existing item.
 *
 * @param event - The event object containing input parameters.
 * @param _context - The context object.
 * @param callback - The callback function to be called with the result.
 */
const handler = async (event: any, _context: any, callback: any) => {
  const { contentId, href, language } = event.args.input;
  if (!contentId && !href) throw new Error('Missing contentId or url');
  let existingItem: any;
  let url: string | null | undefined;
  let uuid: string | undefined;

  if (contentId) {
    existingItem = await observeDependency('get', 'dynamodb', 'get', () =>
      db.get(contentId)
    );
  }

  if (href) {
    url = extractPathWithTrailingSlash(href);
  }

  /**
   * If existingItem can't be found by UUID, try to find it by URL
   */
  if (!existingItem) {
    existingItem = await observeDependency('get', 'dynamodb', 'query', () =>
      db.queryByUrl(url)
    );
  }

  /**
   * If there's no existing item, create a new one
   */
  if (!existingItem) {
    /**
     * If there's no URL, return 404. We need the URL to crawl the page
     */
    if (!url) throw new Error('404');
    const createResponse = await observeDependency(
      'get',
      'dynamodb',
      'create',
      () => db.create(randomUUID(), url)
    );
    uuid = createResponse.uuid;
    console.log(`Created record for ${url}`);
    existingItem = await observeDependency('get', 'dynamodb', 'get', () =>
      db.get(uuid)
    );
  } else {
    uuid = existingItem.uuid;
  }

  /**
   * If we're only looking for one language, if
   * that language exists we can return the item.
   *
   * Otherwise, we wait until all languages are generated.
   */
  while (!checkLanguagesPresent(existingItem, language)) {
    recordRetry('get', 'content_poll', 'waiting');
    await delay(1000);
    existingItem = await observeDependency('get', 'dynamodb', 'get', () =>
      db.get(uuid)
    );
  }
  if (existingItem) {
    const keys = Object.keys(existingItem['outputs']);
    const output: { code: string; url: string }[] = [];
    await Promise.all(
      keys.map(async (key) => {
        const { Bucket, Key } = parseS3Url(existingItem!['outputs'][key]['url']);

        const command = new GetObjectCommand({
          Bucket,
          Key,
        });

        const request = await createRequest<any, GetObjectCommandInput, GetObjectCommandOutput>(new S3Client({}), command);

        const signedRequest = await observeDependency(
          'get',
          's3',
          'presign',
          () => presigner.presign(request, { expiresIn: 3600 })
        );
        const signedUrl = formatUrl(signedRequest);

        output.push({ code: key, url: signedUrl });
      })
    );
    existingItem['outputs'] = output;
  }

  recordWorkflowOutcome('get', 'success');
  callback(null, existingItem);
};

const main = instrumentHandler('get', handler);

export { main };
