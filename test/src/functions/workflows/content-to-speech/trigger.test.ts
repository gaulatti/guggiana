const sendMock = jest.fn();
const updateTitleMock = jest.fn();
const axiosGetMock = jest.fn();

jest.mock('axios', () => ({
  __esModule: true,
  default: {
    get: (...args: any[]) => axiosGetMock(...args),
  },
}));

jest.mock('../../../../../src/utils/consts/languages', () => ({
  pollyLanguages: [
    { code: 'en', items: [{ name: 'Matthew' }] },
    { code: 'es', items: [{ name: 'Lupe' }] },
  ],
}));

jest.mock('../../../../../src/utils/dal/content', () => ({
  getContentTableInstance: jest.fn(() => ({
    updateTitle: updateTitleMock,
  })),
}));

jest.mock('@aws-sdk/client-sfn', () => {
  class StartExecutionCommand {
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
    StartExecutionCommand,
  };
});

describe('src/functions/workflows/content-to-speech/trigger', () => {
  const originalEnv = process.env;

  beforeEach(() => {
    jest.resetModules();
    jest.clearAllMocks();
    process.env = {
      ...originalEnv,
      TABLE_NAME: 'content-table',
      STATE_MACHINE_ARN: 'arn:aws:states:us-east-1:123:stateMachine:test',
    };
    sendMock.mockResolvedValue({ executionArn: 'exec-arn' });
  });

  afterAll(() => {
    process.env = originalEnv;
  });

  it('fetches and parses CNN lite article content', async () => {
    axiosGetMock.mockResolvedValue({
      data: `
      <h2 class="headline">A Headline</h2>
      <p class="byline--lite">By Author</p>
      <p class="paragraph--lite">First paragraph.</p>
      <p class="paragraph--lite">Second paragraph.</p>
      <p class="paragraph--lite">Read more links.</p>
      `,
    });

    const { fetchAndParseArticle } = await import('../../../../../src/functions/workflows/content-to-speech/trigger');
    const output = await fetchAndParseArticle('/2026/04/14/story');

    expect(axiosGetMock).toHaveBeenCalledWith('https://lite.cnn.com/2026/04/14/story');
    expect(output).toEqual({
      title: 'A Headline',
      byline: 'By Author',
      text: 'First paragraph.\nSecond paragraph.',
    });
  });

  it('starts step function execution for a single language', async () => {
    const { startStepFunctionExecution } = await import('../../../../../src/functions/workflows/content-to-speech/trigger');

    const language = { code: 'en', items: [{ name: 'Matthew' }] };
    const execution = await startStepFunctionExecution(
      'uuid-1',
      '/story',
      'Title',
      'Paragraphs',
      'Byline',
      language
    );

    expect(execution).toEqual({ executionArn: 'exec-arn' });
    expect(sendMock).toHaveBeenCalledTimes(1);
    const command = sendMock.mock.calls[0][0];
    expect(command.input).toEqual({
      stateMachineArn: 'arn:aws:states:us-east-1:123:stateMachine:test',
      name: 'uuid-1-en',
      input: JSON.stringify({
        uuid: 'uuid-1',
        url: '/story',
        title: 'Title',
        text: 'Paragraphs',
        byline: 'Byline',
        language,
      }),
    });
  });

  it('handles INSERT events end-to-end and starts execution for each language', async () => {
    axiosGetMock.mockResolvedValue({
      data: `
      <h2 class="headline">Breaking</h2>
      <p class="byline--lite">By Team</p>
      <p class="paragraph--lite">P1.</p>
      <p class="paragraph--lite">P2.</p>
      <p class="paragraph--lite">Footer.</p>
      `,
    });

    const { main } = await import('../../../../../src/functions/workflows/content-to-speech/trigger');

    await main({
      Records: [
        {
          eventName: 'INSERT',
          dynamodb: {
            NewImage: {
              uuid: { S: 'uuid-main' },
              url: { S: '/story/main' },
            },
          },
        },
        {
          eventName: 'MODIFY',
          dynamodb: {
            NewImage: {
              uuid: { S: 'uuid-ignore' },
              url: { S: '/story/ignore' },
            },
          },
        },
      ],
    });

    expect(updateTitleMock).toHaveBeenCalledWith('uuid-main', 'Breaking');
    expect(sendMock).toHaveBeenCalledTimes(2);
  });

  it('catches and logs parsing/execution errors without throwing', async () => {
    axiosGetMock.mockRejectedValue(new Error('network down'));

    const { main } = await import('../../../../../src/functions/workflows/content-to-speech/trigger');

    await expect(
      main({
        Records: [
          {
            eventName: 'INSERT',
            dynamodb: {
              NewImage: {
                uuid: { S: 'uuid-error' },
                url: { S: '/story/error' },
              },
            },
          },
        ],
      })
    ).resolves.toBeUndefined();

    expect(updateTitleMock).not.toHaveBeenCalled();
  });
});
