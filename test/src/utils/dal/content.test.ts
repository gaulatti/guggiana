export {};

const sendMock = jest.fn();
const unmarshallMock = jest.fn<any, [any]>((item) => ({ parsed: item }));

jest.mock('@aws-sdk/client-dynamodb', () => {
  class DynamoDBClient {
    constructor(_config: any) {}
  }

  class QueryCommand {
    input: any;
    constructor(input: any) {
      this.input = input;
    }
  }

  return { DynamoDBClient, QueryCommand };
});

jest.mock('@aws-sdk/lib-dynamodb', () => {
  class GetCommand {
    input: any;
    constructor(input: any) {
      this.input = input;
    }
  }

  class PutCommand {
    input: any;
    constructor(input: any) {
      this.input = input;
    }
  }

  class ScanCommand {
    input: any;
    constructor(input: any) {
      this.input = input;
    }
  }

  class UpdateCommand {
    input: any;
    constructor(input: any) {
      this.input = input;
    }
  }

  class DeleteCommand {
    input: any;
    constructor(input: any) {
      this.input = input;
    }
  }

  const DynamoDBDocumentClient = {
    from: jest.fn(() => ({ send: sendMock })),
  };

  return {
    DeleteCommand,
    DynamoDBDocumentClient,
    GetCommand,
    PutCommand,
    ScanCommand,
    UpdateCommand,
  };
});

jest.mock('@aws-sdk/util-dynamodb', () => ({
  unmarshall: (item: any) => unmarshallMock(item),
}));

describe('src/utils/dal/content DBClient', () => {
  beforeEach(() => {
    jest.resetModules();
    jest.clearAllMocks();
  });

  it('lists items', async () => {
    sendMock.mockResolvedValue({ Items: [{ uuid: '1' }] });
    const { DBClient } = await import('../../../../src/utils/dal/content');
    const db = new DBClient('table');

    await expect(db.list()).resolves.toEqual([{ uuid: '1' }]);
  });

  it('returns null for empty get uuid', async () => {
    const { DBClient } = await import('../../../../src/utils/dal/content');
    const db = new DBClient('table');

    await expect(db.get(null)).resolves.toBeNull();
    expect(sendMock).not.toHaveBeenCalled();
  });

  it('gets an item by uuid', async () => {
    sendMock.mockResolvedValue({ Item: { uuid: 'a' } });
    const { DBClient } = await import('../../../../src/utils/dal/content');
    const db = new DBClient('table');

    await expect(db.get('a')).resolves.toEqual({ uuid: 'a' });
  });

  it('creates content and returns summary', async () => {
    sendMock.mockResolvedValue({});
    const { DBClient, ContentStatus } = await import('../../../../src/utils/dal/content');
    const db = new DBClient('table');

    await expect(db.create('uuid', '/story')).resolves.toEqual({
      uuid: 'uuid',
      url: '/story',
    });

    const command = sendMock.mock.calls[0][0];
    expect(command.input.Item.article_status).toBe(ContentStatus.PENDING);
  });

  it('updates status/title/rendered fields through update command', async () => {
    sendMock.mockResolvedValue({ Attributes: { uuid: 'id' } });
    const { DBClient, ContentStatus } = await import('../../../../src/utils/dal/content');
    const db = new DBClient('table');

    await db.updateStatus('id', ContentStatus.DELIVERED);
    await db.updateTitle('id', 'A title');
    await db.updateRendered('id', {
      en: { status: 'ok', jobId: 'job', url: 's3://bucket/file' },
    });

    expect(sendMock).toHaveBeenCalledTimes(3);
    expect(sendMock.mock.calls[0][0].input.UpdateExpression).toContain('article_status');
    expect(sendMock.mock.calls[1][0].input.UpdateExpression).toContain('title');
    expect(sendMock.mock.calls[2][0].input.UpdateExpression).toContain('outputs');
  });

  it('creates merge jobs and deletes records', async () => {
    sendMock.mockResolvedValue({});
    const { DBClient, ContentStatus } = await import('../../../../src/utils/dal/content');
    const db = new DBClient('table');

    await expect(
      db.createMergeJob('merge-1', 'article-1', 's3://merged.mp3', 'en')
    ).resolves.toBe('s3://merged.mp3');
    await db.delete('merge-1');

    expect(sendMock).toHaveBeenCalledTimes(2);
    const putInput = sendMock.mock.calls[0][0].input;
    expect(putInput.Item.type).toBe('merge');
    expect(putInput.Item.article_status).toBe(ContentStatus.RENDERED);
    expect(sendMock.mock.calls[1][0].input.Key).toEqual({ uuid: 'merge-1' });
  });

  it('returns null when queryByUrl receives empty input', async () => {
    const { DBClient } = await import('../../../../src/utils/dal/content');
    const db = new DBClient('table');

    await expect(db.queryByUrl(undefined)).resolves.toBeNull();
    expect(sendMock).not.toHaveBeenCalled();
  });

  it('queries by url and unmarshalls first item when present', async () => {
    sendMock.mockResolvedValue({
      Items: [{ S: 'raw-value' }],
    });
    unmarshallMock.mockReturnValue({ uuid: 'parsed' });

    const { DBClient } = await import('../../../../src/utils/dal/content');
    const db = new DBClient('table');

    await expect(db.queryByUrl('/story')).resolves.toEqual({ uuid: 'parsed' });
    expect(unmarshallMock).toHaveBeenCalledWith({ S: 'raw-value' });
  });

  it('returns null when queryByUrl has no matching items', async () => {
    sendMock.mockResolvedValue({ Items: [] });
    const { DBClient } = await import('../../../../src/utils/dal/content');
    const db = new DBClient('table');

    await expect(db.queryByUrl('/missing')).resolves.toBeNull();
  });

  it('stores the requested locales on a new content record', async () => {
    sendMock.mockResolvedValue({});
    const { DBClient } = await import('../../../../src/utils/dal/content');
    const db = new DBClient('table');

    await db.create('uuid', '/story', ['en-US']);

    expect(sendMock.mock.calls[0][0].input.Item.requestedLocales).toEqual(['en-US']);
  });

  it('defaults a new content record to no requested locales', async () => {
    sendMock.mockResolvedValue({});
    const { DBClient } = await import('../../../../src/utils/dal/content');
    const db = new DBClient('table');

    await db.create('uuid', '/story');

    expect(sendMock.mock.calls[0][0].input.Item.requestedLocales).toEqual([]);
  });

  it('appends requested locales without withdrawing existing ones', async () => {
    sendMock.mockResolvedValue({ Attributes: { uuid: 'id' } });
    const { DBClient } = await import('../../../../src/utils/dal/content');
    const db = new DBClient('table');

    await db.addRequestedLocales('id', ['es-US']);

    const command = sendMock.mock.calls[0][0];
    expect(command.input.UpdateExpression).toContain('list_append');
    expect(command.input.ExpressionAttributeValues[':locales']).toEqual(['es-US']);
    expect(command.input.ExpressionAttributeValues[':empty']).toEqual([]);
  });

  it('claims a locale with a single conditional write', async () => {
    sendMock.mockResolvedValue({ Attributes: { uuid: 'id' } });
    const { DBClient } = await import('../../../../src/utils/dal/content');
    const db = new DBClient('table');

    await expect(
      db.claimRendition('id', 'en-US', '2026-09-06T12:00:00.000Z', '2026-09-06T11:45:00.000Z')
    ).resolves.toBe(true);

    const command = sendMock.mock.calls[0][0];
    expect(command.input.ExpressionAttributeNames['#rendition']).toBe('rendition#en-US');
    expect(command.input.ConditionExpression).toBe(
      'attribute_not_exists(#rendition) OR #rendition.#status = :failed OR #rendition.#claimedAt < :expiredBefore'
    );
    expect(command.input.ExpressionAttributeValues[':claim']).toEqual({
      status: 'queued',
      claimedAt: '2026-09-06T12:00:00.000Z',
    });
    expect(command.input.ExpressionAttributeValues[':expiredBefore']).toBe(
      '2026-09-06T11:45:00.000Z'
    );
  });

  it('reports a lost race instead of duplicating the rendition', async () => {
    const conditionalFailure: any = new Error('claim already held');
    conditionalFailure.name = 'ConditionalCheckFailedException';
    sendMock.mockRejectedValue(conditionalFailure);

    const { DBClient } = await import('../../../../src/utils/dal/content');
    const db = new DBClient('table');

    await expect(
      db.claimRendition('id', 'en-US', 'now', 'expiry')
    ).resolves.toBe(false);
  });

  it('propagates a claim failure that is not a lost race', async () => {
    sendMock.mockRejectedValue(new Error('throttled'));

    const { DBClient } = await import('../../../../src/utils/dal/content');
    const db = new DBClient('table');

    await expect(db.claimRendition('id', 'en-US', 'now', 'expiry')).rejects.toThrow(
      'throttled'
    );
  });

  it('moves one locale to a new status without touching the others', async () => {
    sendMock.mockResolvedValue({ Attributes: { uuid: 'id' } });
    const { DBClient } = await import('../../../../src/utils/dal/content');
    const db = new DBClient('table');

    await db.updateRenditionStatus('id', 'pt-BR', 'failed');

    const command = sendMock.mock.calls[0][0];
    expect(command.input.ExpressionAttributeNames['#rendition']).toBe('rendition#pt-BR');
    expect(command.input.ExpressionAttributeValues[':claim'].status).toBe('failed');
    expect(command.input.ConditionExpression).toBeUndefined();
  });

  it('returns singleton instance from getContentTableInstance', async () => {
    const { getContentTableInstance } = await import('../../../../src/utils/dal/content');

    const first = getContentTableInstance('table-a');
    const second = getContentTableInstance('table-b');

    expect(first).toBe(second);
  });
});
