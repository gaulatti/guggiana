const getMock = jest.fn();

export {};
const queryByUrlMock = jest.fn();
const createMock = jest.fn();
const addRequestedLocalesMock = jest.fn();
const delayMock = jest.fn();
const extractPathWithTrailingSlashMock = jest.fn();
const presignMock = jest.fn();
const createRequestMock = jest.fn();
const formatUrlMock = jest.fn();

jest.mock('crypto', () => ({
  randomUUID: jest.fn(() => 'generated-uuid'),
}));

jest.mock('../../../../../src/utils/consts/languages', () => ({
  pollyLanguages: [
    { code: 'en', items: [{ name: 'Matthew' }] },
    { code: 'es', items: [{ name: 'Lupe' }] },
  ],
}));

jest.mock('../../../../../src/utils/dal/content', () => ({
  getContentTableInstance: jest.fn(() => ({
    get: getMock,
    queryByUrl: queryByUrlMock,
    create: createMock,
    addRequestedLocales: addRequestedLocalesMock,
  })),
}));

jest.mock('../../../../../src/utils', () => ({
  delay: (...args: any[]) => delayMock(...args),
  extractPathWithTrailingSlash: (...args: any[]) =>
    extractPathWithTrailingSlashMock(...args),
}));

jest.mock('@aws-sdk/client-s3', () => {
  class GetObjectCommand {
    input: any;
    constructor(input: any) {
      this.input = input;
    }
  }

  class S3Client {
    config: any;
    constructor() {
      this.config = { region: 'us-east-1' };
    }
  }

  return {
    GetObjectCommand,
    S3Client,
  };
});

jest.mock('@aws-sdk/s3-request-presigner', () => ({
  S3RequestPresigner: class {
    presign = (...args: any[]) => presignMock(...args);
  },
}));

jest.mock('@aws-sdk/util-create-request', () => ({
  createRequest: (...args: any[]) => createRequestMock(...args),
}));

jest.mock('@aws-sdk/util-format-url', () => ({
  formatUrl: (...args: any[]) => formatUrlMock(...args),
}));

const output = (uuid: string, code: string) => ({
  url: `https://s3.us-east-1.amazonaws.com/audio-bucket/full/${uuid}-${code}.mp3`,
});

const item = (
  uuid: string,
  codes: string[],
  extra: Record<string, any> = {}
) => ({
  uuid,
  outputs: Object.fromEntries(codes.map((code) => [code, output(uuid, code)])),
  ...extra,
});

describe('src/functions/workflows/content-to-speech/get main', () => {
  const originalEnv = process.env;

  beforeEach(() => {
    jest.resetModules();
    jest.clearAllMocks();
    process.env = {
      ...originalEnv,
      TABLE_NAME: 'content-table',
    };
    delayMock.mockResolvedValue(undefined);
    addRequestedLocalesMock.mockResolvedValue({});
    createRequestMock.mockResolvedValue({ host: 'signed-request' });
    presignMock.mockResolvedValue({
      protocol: 'https',
      hostname: 'example.com',
      path: '/signed.mp3',
    });
    formatUrlMock.mockReturnValue('https://signed.example.com/file.mp3');
  });

  afterAll(() => {
    process.env = originalEnv;
  });

  const load = () =>
    import('../../../../../src/functions/workflows/content-to-speech/get');

  it('throws when both contentId and href are missing', async () => {
    const callback = jest.fn();
    const { main } = await load();

    await expect(
      main({ args: { input: {} } }, {}, callback)
    ).rejects.toThrow('Missing contentId or url');
  });

  it('throws 404 when no item exists and href cannot be normalized', async () => {
    getMock.mockResolvedValue(null);
    queryByUrlMock.mockResolvedValue(null);
    extractPathWithTrailingSlashMock.mockReturnValue(null);

    const { main } = await load();

    await expect(
      main(
        {
          args: {
            input: {
              contentId: 'does-not-exist',
              href: 'https://example.com/not-cnn',
            },
          },
        },
        {},
        jest.fn()
      )
    ).rejects.toThrow('404');
  });

  it('rejects an unsupported language instead of silently generating another', async () => {
    const { main } = await load();

    await expect(
      main({ args: { input: { contentId: 'uuid-1', language: 'fr' } } }, {}, jest.fn())
    ).rejects.toThrow('Unsupported language: fr');
    expect(getMock).not.toHaveBeenCalled();
  });

  it('waits only for the single requested locale and never for the others', async () => {
    const callback = jest.fn();
    getMock
      .mockResolvedValueOnce(item('uuid-1', []))
      .mockResolvedValueOnce(item('uuid-1', ['en']));

    const { main } = await load();

    await main(
      { args: { input: { contentId: 'uuid-1', language: 'en' } } },
      {},
      callback
    );

    // `es` was never requested, so it is never generated and never waited on.
    expect(addRequestedLocalesMock).toHaveBeenCalledWith('uuid-1', ['en']);
    expect(delayMock).toHaveBeenCalledTimes(1);
    expect(delayMock).toHaveBeenCalledWith(1000);
    expect(createRequestMock).toHaveBeenCalledTimes(1);
    expect(presignMock).toHaveBeenCalledWith(
      { host: 'signed-request' },
      { expiresIn: 3600 }
    );
    expect(callback).toHaveBeenCalledWith(null, {
      uuid: 'uuid-1',
      outputs: [{ code: 'en', url: 'https://signed.example.com/file.mp3' }],
    });
  });

  it('serves a cached artifact without asking for any new work', async () => {
    const callback = jest.fn();
    getMock.mockResolvedValue(item('uuid-1', ['en']));

    const { main } = await load();

    await main(
      { args: { input: { contentId: 'uuid-1', language: 'en' } } },
      {},
      callback
    );

    expect(addRequestedLocalesMock).not.toHaveBeenCalled();
    expect(delayMock).not.toHaveBeenCalled();
    expect(callback).toHaveBeenCalled();
  });

  it('accepts an explicit locale subset', async () => {
    const callback = jest.fn();
    getMock.mockResolvedValue(item('uuid-1', ['es']));

    const { main } = await load();

    await main(
      { args: { input: { contentId: 'uuid-1', languages: ['es'] } } },
      {},
      callback
    );

    expect(addRequestedLocalesMock).not.toHaveBeenCalled();
    expect(callback).toHaveBeenCalled();
  });

  it('does not re-request a locale the record already asked for', async () => {
    const callback = jest.fn();
    getMock
      .mockResolvedValueOnce(item('uuid-1', [], { requestedLocales: ['en'] }))
      .mockResolvedValueOnce(item('uuid-1', ['en'], { requestedLocales: ['en'] }));

    const { main } = await load();

    await main(
      { args: { input: { contentId: 'uuid-1', language: 'en' } } },
      {},
      callback
    );

    expect(addRequestedLocalesMock).not.toHaveBeenCalled();
    expect(callback).toHaveBeenCalled();
  });

  it('waits for every supported locale on the explicit all-locales path', async () => {
    const callback = jest.fn();
    getMock
      .mockResolvedValueOnce(item('uuid-1', ['en']))
      .mockResolvedValueOnce(item('uuid-1', ['en', 'es']));
    formatUrlMock
      .mockReturnValueOnce('https://signed.example.com/en.mp3')
      .mockReturnValueOnce('https://signed.example.com/es.mp3');

    const { main } = await load();

    await main(
      { args: { input: { contentId: 'uuid-1', language: 'all' } } },
      {},
      callback
    );

    expect(addRequestedLocalesMock).toHaveBeenCalledWith('uuid-1', ['es']);
    expect(delayMock).toHaveBeenCalledTimes(1);
    expect(callback.mock.calls[0][1].outputs).toHaveLength(2);
  });

  it('keeps the previous contract when no language is supplied', async () => {
    const callback = jest.fn();
    getMock.mockResolvedValue(item('uuid-1', ['en', 'es']));
    formatUrlMock
      .mockReturnValueOnce('https://signed.example.com/en.mp3')
      .mockReturnValueOnce('https://signed.example.com/es.mp3');

    const { main } = await load();

    await main({ args: { input: { contentId: 'uuid-1' } } }, {}, callback);

    expect(addRequestedLocalesMock).not.toHaveBeenCalled();
    expect(callback.mock.calls[0][1].outputs).toHaveLength(2);
  });

  it('creates a new record carrying only the requested locales', async () => {
    extractPathWithTrailingSlashMock.mockReturnValue('/story/new');
    queryByUrlMock.mockResolvedValue(null);
    createMock.mockResolvedValue({ uuid: 'generated-uuid', url: '/story/new' });
    getMock
      .mockResolvedValueOnce(null)
      .mockResolvedValue(item('generated-uuid', ['es']));

    const callback = jest.fn();
    const { main } = await load();

    await main(
      { args: { input: { href: 'https://www.cnn.com/story/new', language: 'es' } } },
      {},
      callback
    );

    expect(createMock).toHaveBeenCalledWith('generated-uuid', '/story/new', ['es']);
    expect(addRequestedLocalesMock).not.toHaveBeenCalled();
    expect(callback).toHaveBeenCalledWith(null, {
      uuid: 'generated-uuid',
      outputs: [{ code: 'es', url: 'https://signed.example.com/file.mp3' }],
    });
  });

  it('throws for invalid S3 output URLs during signing', async () => {
    getMock.mockResolvedValue({
      uuid: 'uuid-invalid',
      outputs: {
        en: { url: 'https://invalid-host/file.mp3' },
        es: { url: 'https://invalid-host/file.mp3' },
      },
    });

    const callback = jest.fn();
    const { main } = await load();

    await expect(
      main({ args: { input: { contentId: 'uuid-invalid' } } }, {}, callback)
    ).rejects.toThrow('Invalid S3 URL');
    expect(callback).not.toHaveBeenCalled();
  });
});
