import { DynamoDBClient, QueryCommand } from '@aws-sdk/client-dynamodb';
import {
  DeleteCommand,
  DynamoDBDocumentClient,
  GetCommand,
  PutCommand,
  ScanCommand,
  UpdateCommand,
} from '@aws-sdk/lib-dynamodb';
import { unmarshall } from '@aws-sdk/util-dynamodb';
import { renditionAttribute } from '../renditions';
import type { RenditionStatus } from '../renditions';

const dynamoClient = new DynamoDBClient({});
const docClient = DynamoDBDocumentClient.from(dynamoClient, {
  marshallOptions: {
    removeUndefinedValues: true,
  },
});
let dbInstance: DBClient | null = null;

enum ContentStatus {
  PENDING = 'PENDING',
  RENDERED = 'RENDERED',
  DELIVERED = 'DELIVERED',
  FAILED = 'FAILED',
}

/**
 * Represents a database client for interacting with a specific table.
 */
class DBClient {
  private tableName: string;

  constructor(tableName: string) {
    this.tableName = tableName;
  }

  /**
   * Retrieves a list of items from the database.
   * @returns {Promise<any[]>} A promise that resolves to an array of items.
   */
  public async list() {
    const command = new ScanCommand({
      TableName: this.tableName,
    });

    const response = await docClient.send(command);

    return response.Items;
  }

  /**
   * Retrieves an item from the database based on the provided UUID.
   *
   * @param uuid - The UUID of the item to retrieve.
   * @returns The retrieved item, or null if the UUID is falsy.
   */
  public async get(uuid: string | null | undefined) {
    if (!uuid) return null;

    const command = new GetCommand({
      TableName: this.tableName,
      Key: {
        uuid,
      },
    });

    const response = await docClient.send(command);
    return response.Item;
  }

  /**
   * Creates a new content record in the database.
   *
   * @param uuid - The UUID of the content.
   * @param url - The URL of the content.
   * @returns An object containing the UUID and URL of the created content.
   */
  public async create(uuid: string, url: string, requestedLocales: string[] = []) {
    const command = new PutCommand({
      TableName: this.tableName,
      Item: {
        uuid,
        url,
        article_status: ContentStatus.PENDING,
        requestedLocales,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
    });

    await docClient.send(command);

    return { uuid, url };
  }

  /**
   * Records the locales a caller has asked for. The set only grows: adding a
   * locale never withdraws one another caller is already waiting on. The
   * resulting stream event is what asks the trigger to materialize the new
   * locales.
   *
   * @param uuid - The UUID of the content item.
   * @param requestedLocales - The locales to add to the requested set.
   * @returns The updated content item.
   */
  public async addRequestedLocales(uuid: string, requestedLocales: string[]) {
    const command = new UpdateCommand({
      TableName: this.tableName,
      Key: { uuid },
      UpdateExpression:
        'SET requestedLocales = list_append(if_not_exists(requestedLocales, :empty), :locales), updatedAt = :updatedAt',
      ExpressionAttributeValues: {
        ':empty': [],
        ':locales': requestedLocales,
        ':updatedAt': new Date().toISOString(),
      },
      ReturnValues: 'ALL_NEW',
    });

    return await docClient.send(command);
  }

  /**
   * Atomically claims one locale of one content item so that exactly one caller
   * launches its workflow.
   *
   * The claim succeeds only when the locale has never been claimed, its last
   * attempt failed, or its claim is older than `expiredBefore` (a Lambda that
   * died between claiming and starting). Concurrent callers therefore converge
   * on a single execution instead of duplicating translation and synthesis.
   *
   * @returns `true` when this caller owns the claim and must start the work.
   */
  public async claimRendition(
    uuid: string,
    code: string,
    claimedAt: string,
    expiredBefore: string
  ): Promise<boolean> {
    const command = new UpdateCommand({
      TableName: this.tableName,
      Key: { uuid },
      UpdateExpression: 'SET #rendition = :claim, updatedAt = :updatedAt',
      ConditionExpression:
        'attribute_not_exists(#rendition) OR #rendition.#status = :failed OR #rendition.#claimedAt < :expiredBefore',
      ExpressionAttributeNames: {
        '#rendition': renditionAttribute(code),
        '#status': 'status',
        '#claimedAt': 'claimedAt',
      },
      ExpressionAttributeValues: {
        ':claim': { status: 'queued', claimedAt },
        ':failed': 'failed',
        ':expiredBefore': expiredBefore,
        ':updatedAt': claimedAt,
      },
      ReturnValues: 'ALL_NEW',
    });

    try {
      await docClient.send(command);
      return true;
    } catch (error: any) {
      if (error?.name === 'ConditionalCheckFailedException') {
        return false;
      }
      throw error;
    }
  }

  /**
   * Moves one locale's claim to a new lifecycle status. Failure is isolated to
   * the locale it happened in; other locales keep their own state.
   *
   * @param uuid - The UUID of the content item.
   * @param code - The locale identifier.
   * @param status - The new rendition status.
   * @returns The updated content item.
   */
  public async updateRenditionStatus(
    uuid: string,
    code: string,
    status: RenditionStatus
  ) {
    const now = new Date().toISOString();
    const command = new UpdateCommand({
      TableName: this.tableName,
      Key: { uuid },
      UpdateExpression: 'SET #rendition = :claim, updatedAt = :updatedAt',
      ExpressionAttributeNames: { '#rendition': renditionAttribute(code) },
      ExpressionAttributeValues: {
        ':claim': { status, claimedAt: now },
        ':updatedAt': now,
      },
      ReturnValues: 'ALL_NEW',
    });

    return await docClient.send(command);
  }

  /**
   * Updates the status of a content item.
   *
   * @param uuid - The UUID of the content item.
   * @param status - The new status to be set.
   * @returns A promise that resolves to the updated content item.
   */
  public async updateStatus(uuid: string, status: ContentStatus) {
    let UpdateExpression =
      'set article_status = :status, updatedAt = :updatedAt';
    let ExpressionAttributeValues: { [k: string]: any } = {
      ':status': status,
      ':updatedAt': new Date().toISOString(),
    };

    return await this.update(uuid, UpdateExpression, ExpressionAttributeValues);
  }

  /**
   * Creates a merge job in the database.
   *
   * @param uuid - The UUID of the merge job.
   * @param article_id - The ID of the article.
   * @param url - The URL of the merge job.
   * @param language - The language of the merge job.
   * @returns The URL of the merge job.
   */
  public async createMergeJob(
    uuid: string,
    article_id: String,
    url: string,
    language: string
  ) {
    const command = new PutCommand({
      TableName: this.tableName,
      Item: {
        uuid,
        article_id,
        url,
        type: 'merge',
        language,
        article_status: ContentStatus.RENDERED,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
    });

    await docClient.send(command);

    return url;
  }

  /**
   * Updates the title of a content item.
   * @param uuid - The UUID of the content item.
   * @param title - The new title for the content item.
   * @returns A promise that resolves to the updated content item.
   */
  public async updateTitle(uuid: string, title: string) {
    let UpdateExpression = 'set title = :title, updatedAt = :updatedAt';
    let ExpressionAttributeValues: { [k: string]: any } = {
      ':title': title,
      ':updatedAt': new Date().toISOString(),
    };

    return await this.update(uuid, UpdateExpression, ExpressionAttributeValues);
  }

  /**
   * Updates the rendered content with the specified UUID.
   * @param uuid - The UUID of the content to update.
   * @param outputs - The updated outputs for the content.
   * @returns A promise that resolves to the result of the update operation.
   */
  public async updateRendered(
    uuid: string,
    outputs: Record<string, { status: string; jobId: string; url: string }>
  ) {
    let UpdateExpression = 'set outputs = :outputs, updatedAt = :updatedAt';
    let ExpressionAttributeValues: { [k: string]: any } = {
      ':outputs': outputs,
      ':updatedAt': new Date().toISOString(),
    };

    return await this.update(uuid, UpdateExpression, ExpressionAttributeValues);
  }

  /**
   * Updates a record in the database.
   *
   * @param uuid - The unique identifier of the record.
   * @param UpdateExpression - The update expression for modifying the record.
   * @param ExpressionAttributeValues - Optional. The attribute values used in the update expression.
   * @returns A promise that resolves to the updated record.
   */
  private async update(
    uuid: string,
    UpdateExpression: string,
    ExpressionAttributeValues?: Record<string, any>
  ) {
    const command = new UpdateCommand({
      TableName: this.tableName,
      Key: {
        uuid,
      },
      UpdateExpression,
      ExpressionAttributeValues,
      ReturnValues: 'ALL_NEW',
    });

    return await docClient.send(command);
  }

  /**
   * Deletes an item from the database.
   * @param uuid - The UUID of the item to delete.
   * @returns A promise that resolves when the item is successfully deleted.
   */
  public async delete(uuid: string) {
    const command = new DeleteCommand({
      TableName: this.tableName,
      Key: {
        uuid,
      },
    });

    return docClient.send(command);
  }

  /**
   * Queries the content by URL.
   * @param url - The URL to query.
   * @returns The queried content or null if not found.
   */
  public async queryByUrl(url: string | null | undefined) {
    if (!url) return null;
    const command = new QueryCommand({
      TableName: this.tableName,
      IndexName: 'UrlIndex',
      KeyConditionExpression: '#urlAttribute = :urlVal',
      ExpressionAttributeNames: {
        '#urlAttribute': 'url',
      },
      ExpressionAttributeValues: {
        ':urlVal': { S: url },
      },
    });

    const response = await docClient.send(command);
    return response.Items?.[0] ? unmarshall(response.Items[0]) : null;
  }
}

/**
 * Returns an instance of the content table from the database.
 * If the instance does not exist, it creates a new one.
 *
 * @param tableName - The name of the content table.
 * @returns The instance of the content table.
 */
const getContentTableInstance = (tableName: string) => {
  if (!dbInstance) {
    dbInstance = new DBClient(tableName);
  }

  return dbInstance;
};

export { DBClient, ContentStatus, getContentTableInstance };
