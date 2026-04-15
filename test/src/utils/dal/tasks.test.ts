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

  class ScanCommand {
    input: any;
    constructor(input: any) {
      this.input = input;
    }
  }

  return { DynamoDBClient, QueryCommand, ScanCommand };
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

  class UpdateCommand {
    input: any;
    constructor(input: any) {
      this.input = input;
    }
  }

  const DynamoDBDocumentClient = {
    from: jest.fn(() => ({ send: sendMock })),
  };

  return {
    DynamoDBDocumentClient,
    GetCommand,
    PutCommand,
    UpdateCommand,
  };
});

jest.mock('@aws-sdk/util-dynamodb', () => ({
  unmarshall: (item: any) => unmarshallMock(item),
}));

describe('src/utils/dal/tasks DBClient', () => {
  beforeEach(() => {
    jest.resetModules();
    jest.clearAllMocks();
  });

  it('lists and unmarshalls task items', async () => {
    sendMock.mockResolvedValue({ Items: [{ id: '1' }, { id: '2' }] });
    unmarshallMock.mockImplementation((item) => ({ uuid: item.id }));

    const { getTasksTableInstance } = await import('../../../../src/utils/dal/tasks');
    const db = getTasksTableInstance('tasks-table');

    await expect(db.list()).resolves.toEqual([{ uuid: '1' }, { uuid: '2' }]);
  });

  it('returns empty list when scan has no items', async () => {
    sendMock.mockResolvedValue({});

    const { getTasksTableInstance } = await import('../../../../src/utils/dal/tasks');
    const db = getTasksTableInstance('tasks-table');

    await expect(db.list()).resolves.toEqual([]);
  });

  it('returns null for empty get uuid and returns item for valid uuid', async () => {
    const { getTasksTableInstance } = await import('../../../../src/utils/dal/tasks');
    const db = getTasksTableInstance('tasks-table');

    await expect(db.get(undefined)).resolves.toBeNull();

    sendMock.mockResolvedValueOnce({ Item: { uuid: 'ok' } });
    await expect(db.get('ok')).resolves.toEqual({ uuid: 'ok' });
  });

  it('creates tasks and updates status', async () => {
    sendMock.mockResolvedValue({ Attributes: { uuid: 'u1' } });

    const { TaskStatus, getTasksTableInstance } = await import('../../../../src/utils/dal/tasks');
    const db = getTasksTableInstance('tasks-table');

    await expect(db.create('u1', 's3://file', 'token', 10)).resolves.toEqual({
      uuid: 'u1',
      url: 's3://file',
    });
    await db.updateStatus('u1', TaskStatus.DELIVERED);

    expect(sendMock).toHaveBeenCalledTimes(2);
    expect(sendMock.mock.calls[0][0].input.Item.task_status).toBe(TaskStatus.PENDING);
    expect(sendMock.mock.calls[1][0].input.UpdateExpression).toContain('task_status');
  });

  it('returns null when queryByUrl input is missing', async () => {
    const { getTasksTableInstance } = await import('../../../../src/utils/dal/tasks');
    const db = getTasksTableInstance('tasks-table');

    await expect(db.queryByUrl(null)).resolves.toBeNull();
    expect(sendMock).not.toHaveBeenCalled();
  });

  it('queries by url and returns unmarshalled first item', async () => {
    sendMock.mockResolvedValue({ Items: [{ S: 'task-raw' }] });
    unmarshallMock.mockReturnValue({ uuid: 'task-1' });

    const { getTasksTableInstance } = await import('../../../../src/utils/dal/tasks');
    const db = getTasksTableInstance('tasks-table');

    await expect(db.queryByUrl('/story')).resolves.toEqual({ uuid: 'task-1' });
    expect(unmarshallMock).toHaveBeenCalledWith({ S: 'task-raw' });
  });

  it('returns null when queryByUrl has no matching items', async () => {
    sendMock.mockResolvedValue({ Items: [] });
    const { getTasksTableInstance } = await import('../../../../src/utils/dal/tasks');
    const db = getTasksTableInstance('tasks-table');

    await expect(db.queryByUrl('/missing')).resolves.toBeNull();
  });

  it('returns same singleton task instance', async () => {
    const { getTasksTableInstance } = await import('../../../../src/utils/dal/tasks');

    const first = getTasksTableInstance('tasks-a');
    const second = getTasksTableInstance('tasks-b');

    expect(first).toBe(second);
  });
});
