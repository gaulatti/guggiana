export {};

const sendMock = jest.fn();
const updateTitleMock = jest.fn();
const claimRenditionMock = jest.fn();
const updateRenditionStatusMock = jest.fn();
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
    claimRendition: claimRenditionMock,
    updateRenditionStatus: updateRenditionStatusMock,
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

const ARTICLE_HTML = `
  <h2 class="headline">Breaking</h2>
  <p class="byline--lite">By Team</p>
  <p class="paragraph--lite">P1.</p>
  <p class="paragraph--lite">P2.</p>
  <p class="paragraph--lite">Footer.</p>
`;

/** A DynamoDB stream image for a content record. */
const image = (attributes: Record<string, any>) => ({
  uuid: { S: 'uuid-main' },
  url: { S: '/story/main' },
  ...attributes,
});

const locales = (...codes: string[]) => ({
  requestedLocales: { L: codes.map((code) => ({ S: code })) },
});

const outputs = (...codes: string[]) => ({
  outputs: {
    M: Object.fromEntries(
      codes.map((code) => [code, { M: { url: { S: `s3://${code}` } } }])
    ),
  },
});

const claim = (code: string, status: string, claimedAt: string) => ({
  [`rendition#${code}`]: {
    M: { status: { S: status }, claimedAt: { S: claimedAt } },
  },
});

const record = (eventName: string, NewImage: Record<string, any>) => ({
  eventName,
  dynamodb: { NewImage },
});

const startedLocales = () =>
  sendMock.mock.calls.map((call) => JSON.parse(call[0].input.input).language.code);

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
    claimRenditionMock.mockResolvedValue(true);
    updateRenditionStatusMock.mockResolvedValue({});
    axiosGetMock.mockResolvedValue({ data: ARTICLE_HTML });
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

  it('starts exactly one workflow for a single requested locale', async () => {
    const { main } = await import('../../../../../src/functions/workflows/content-to-speech/trigger');

    await main({ Records: [record('INSERT', image(locales('es')))] });

    expect(updateTitleMock).toHaveBeenCalledWith('uuid-main', 'Breaking');
    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(startedLocales()).toEqual(['es']);
    expect(claimRenditionMock).toHaveBeenCalledTimes(1);
  });

  it('generates nothing for an inserted article nobody has asked for', async () => {
    const { main } = await import('../../../../../src/functions/workflows/content-to-speech/trigger');

    await main({ Records: [record('INSERT', image({}))] });

    expect(axiosGetMock).not.toHaveBeenCalled();
    expect(updateTitleMock).not.toHaveBeenCalled();
    expect(claimRenditionMock).not.toHaveBeenCalled();
    expect(sendMock).not.toHaveBeenCalled();
  });

  it('materializes exactly the supported set for an explicit all-locales request', async () => {
    const { main } = await import('../../../../../src/functions/workflows/content-to-speech/trigger');

    await main({ Records: [record('INSERT', image(locales('en', 'es')))] });

    expect(sendMock).toHaveBeenCalledTimes(2);
    expect(startedLocales().sort()).toEqual(['en', 'es']);
  });

  it('reuses a cached artifact and only generates the newly requested locale', async () => {
    const { main } = await import('../../../../../src/functions/workflows/content-to-speech/trigger');

    await main({
      Records: [
        record('MODIFY', image({ ...locales('en', 'es'), ...outputs('en') })),
      ],
    });

    expect(startedLocales()).toEqual(['es']);
    expect(claimRenditionMock).toHaveBeenCalledTimes(1);
    expect(claimRenditionMock.mock.calls[0][1]).toBe('es');
  });

  it('does nothing when every requested locale is already cached', async () => {
    const { main } = await import('../../../../../src/functions/workflows/content-to-speech/trigger');

    await main({
      Records: [
        record('MODIFY', image({ ...locales('en', 'es'), ...outputs('en', 'es') })),
      ],
    });

    expect(axiosGetMock).not.toHaveBeenCalled();
    expect(sendMock).not.toHaveBeenCalled();
  });

  it('does not re-enter a locale a live execution already claimed', async () => {
    const { main } = await import('../../../../../src/functions/workflows/content-to-speech/trigger');

    await main({
      Records: [
        record(
          'MODIFY',
          image({
            ...locales('en'),
            ...claim('en', 'running', new Date().toISOString()),
          })
        ),
      ],
    });

    expect(axiosGetMock).not.toHaveBeenCalled();
    expect(sendMock).not.toHaveBeenCalled();
  });

  it('re-claims a locale whose claim has expired', async () => {
    const { main } = await import('../../../../../src/functions/workflows/content-to-speech/trigger');

    await main({
      Records: [
        record(
          'MODIFY',
          image({
            ...locales('en'),
            ...claim('en', 'running', new Date(Date.now() - 60 * 60 * 1000).toISOString()),
          })
        ),
      ],
    });

    expect(startedLocales()).toEqual(['en']);
  });

  it('starts nothing when a concurrent caller already owns the claim', async () => {
    claimRenditionMock.mockResolvedValue(false);
    const { main } = await import('../../../../../src/functions/workflows/content-to-speech/trigger');

    await main({ Records: [record('INSERT', image(locales('en', 'es')))] });

    expect(claimRenditionMock).toHaveBeenCalledTimes(2);
    expect(sendMock).not.toHaveBeenCalled();
  });

  it('isolates a per-locale failure and still starts the other locale', async () => {
    sendMock
      .mockRejectedValueOnce(new Error('throttled'))
      .mockResolvedValue({ executionArn: 'exec-arn' });

    const { main } = await import('../../../../../src/functions/workflows/content-to-speech/trigger');

    await main({ Records: [record('INSERT', image(locales('en', 'es')))] });

    // Both locales were attempted; only `en` failed, and only its claim was
    // released so it can be retried without blocking `es`.
    expect(startedLocales()).toEqual(['en', 'es']);
    expect(updateRenditionStatusMock).toHaveBeenCalledTimes(1);
    expect(updateRenditionStatusMock).toHaveBeenCalledWith('uuid-main', 'en', 'failed');
  });

  it('ignores an unsupported requested locale rather than expanding the request', async () => {
    const { main } = await import('../../../../../src/functions/workflows/content-to-speech/trigger');

    await main({ Records: [record('INSERT', image(locales('fr')))] });

    expect(axiosGetMock).not.toHaveBeenCalled();
    expect(sendMock).not.toHaveBeenCalled();
  });

  it('ignores a requested-locale attribute that is not a list of strings', async () => {
    const { main } = await import('../../../../../src/functions/workflows/content-to-speech/trigger');

    await main({
      Records: [
        record('INSERT', image({ requestedLocales: { L: [{ N: '7' }] } })),
        record('INSERT', image({ requestedLocales: { S: 'en' } })),
      ],
    });

    expect(sendMock).not.toHaveBeenCalled();
  });

  it('skips events that are neither an insert nor a modification', async () => {
    const { main } = await import('../../../../../src/functions/workflows/content-to-speech/trigger');

    await main({ Records: [record('REMOVE', image(locales('en')))] });

    expect(axiosGetMock).not.toHaveBeenCalled();
    expect(sendMock).not.toHaveBeenCalled();
  });

  it('catches and logs parsing errors without throwing', async () => {
    axiosGetMock.mockRejectedValue(new Error('network down'));

    const { main } = await import('../../../../../src/functions/workflows/content-to-speech/trigger');

    await expect(
      main({ Records: [record('INSERT', image(locales('en')))] })
    ).resolves.toBeUndefined();

    expect(updateTitleMock).not.toHaveBeenCalled();
  });
});
