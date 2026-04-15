const createMock = jest.fn();

jest.mock('../../../../src/utils/dal/tasks', () => ({
  getTasksTableInstance: jest.fn(() => ({ create: createMock })),
}));

describe('src/functions/tts/polly_wait main', () => {
  beforeEach(() => {
    jest.resetModules();
    jest.clearAllMocks();
  });

  it('creates a task for title output when TaskId and OutputUri are present', async () => {
    const before = Date.now();
    const { main } = await import('../../../../src/functions/tts/polly_wait');

    await main(
      {
        textType: 'title',
        token: 'task-token',
        title: { SynthesisTask: { TaskId: 'task-1', OutputUri: 's3://audio/title.mp3' } },
      },
      {},
      jest.fn()
    );

    expect(createMock).toHaveBeenCalledTimes(1);
    const [taskId, outputUri, token, ttl] = createMock.mock.calls[0];
    expect(taskId).toBe('task-1');
    expect(outputUri).toBe('s3://audio/title.mp3');
    expect(token).toBe('task-token');
    expect(ttl).toBeGreaterThanOrEqual(Math.floor(before / 1000) + 499);
    expect(ttl).toBeLessThanOrEqual(Math.floor(Date.now() / 1000) + 501);
  });

  it('creates a task from paragraph output when textType is paragraph', async () => {
    const { main } = await import('../../../../src/functions/tts/polly_wait');

    await main(
      {
        textType: 'paragraph',
        token: 'task-token',
        audioOutput: {
          SynthesisTask: { TaskId: 'task-2', OutputUri: 's3://audio/paragraph.mp3' },
        },
      },
      {},
      jest.fn()
    );

    expect(createMock).toHaveBeenCalledWith(
      'task-2',
      's3://audio/paragraph.mp3',
      'task-token',
      expect.any(Number)
    );
  });

  it('does not create a task when source is missing', async () => {
    const { main } = await import('../../../../src/functions/tts/polly_wait');

    await main({ textType: 'unknown' }, {}, jest.fn());

    expect(createMock).not.toHaveBeenCalled();
  });

  it('does not create a task when TaskId or OutputUri are missing', async () => {
    const { main } = await import('../../../../src/functions/tts/polly_wait');

    await main(
      {
        textType: 'title',
        token: 'task-token',
        title: { SynthesisTask: { TaskId: '', OutputUri: '' } },
      },
      {},
      jest.fn()
    );

    expect(createMock).not.toHaveBeenCalled();
  });
});
