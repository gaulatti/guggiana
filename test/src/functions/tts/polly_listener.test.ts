const sendMock = jest.fn();
const updateStatusMock = jest.fn();
const listMock = jest.fn();

jest.mock('@aws-sdk/client-sfn', () => {
  class SendTaskSuccessCommand {
    input: any;
    constructor(input: any) {
      this.input = input;
    }
  }

  class SFNClient {
    send = sendMock;
  }

  return {
    SFNClient,
    SendTaskSuccessCommand,
  };
});

jest.mock('../../../../src/utils/dal/tasks', () => ({
  TaskStatus: { DELIVERED: 'DELIVERED' },
  getTasksTableInstance: jest.fn(() => ({
    list: listMock,
    updateStatus: updateStatusMock,
  })),
}));

describe('src/functions/tts/polly_listener main', () => {
  beforeEach(() => {
    jest.resetModules();
    jest.clearAllMocks();
  });

  it('returns early when Records is a falsy value with length support', async () => {
    const callback = jest.fn();
    const { main } = await import('../../../../src/functions/tts/polly_listener');

    await main({ Records: '' }, {}, callback);

    expect(callback).toHaveBeenCalledWith(null, 'No records found');
    expect(listMock).not.toHaveBeenCalled();
  });

  it('updates matching tasks and sends success to Step Functions', async () => {
    listMock.mockResolvedValue([
      {
        uuid: 'u-1',
        token: 'tok-1',
        url: 'https://s3.us-east-1.amazonaws.com/audio-bucket/path/file.mp3',
      },
    ]);
    const callback = jest.fn();
    const { main } = await import('../../../../src/functions/tts/polly_listener');

    await main(
      {
        Records: [
          {
            eventName: 'ObjectCreated:Put',
            s3: {
              bucket: { name: 'audio-bucket' },
              object: { key: 'path/file.mp3' },
            },
          },
          {
            eventName: 'ObjectRemoved:Delete',
            s3: {
              bucket: { name: 'audio-bucket' },
              object: { key: 'ignore.mp3' },
            },
          },
        ],
      },
      {},
      callback
    );

    expect(listMock).toHaveBeenCalledTimes(1);
    expect(updateStatusMock).toHaveBeenCalledWith('u-1', 'DELIVERED');
    expect(sendMock).toHaveBeenCalledTimes(1);
    const command = sendMock.mock.calls[0][0];
    expect(command.input).toEqual({
      taskToken: 'tok-1',
      output: JSON.stringify({
        url: 'https://s3.us-east-1.amazonaws.com/audio-bucket/path/file.mp3',
      }),
    });
    expect(callback).not.toHaveBeenCalled();
  });

  it('skips updates when no db record matches an item', async () => {
    listMock.mockResolvedValue([]);
    const { main } = await import('../../../../src/functions/tts/polly_listener');

    await main(
      {
        Records: [
          {
            eventName: 'ObjectCreated:Put',
            s3: {
              bucket: { name: 'audio-bucket' },
              object: { key: 'new/file.mp3' },
            },
          },
        ],
      },
      {},
      jest.fn()
    );

    expect(updateStatusMock).not.toHaveBeenCalled();
    expect(sendMock).not.toHaveBeenCalled();
  });
});
