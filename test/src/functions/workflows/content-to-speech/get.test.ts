const getMock = jest.fn();
const queryByUrlMock = jest.fn();
const createMock = jest.fn();
const checkLanguagesPresentMock = jest.fn();
const delayMock = jest.fn();
const extractPathWithTrailingSlashMock = jest.fn();
const presignMock = jest.fn();
const createRequestMock = jest.fn();
const formatUrlMock = jest.fn();

jest.mock('crypto', () => ({
  randomUUID: jest.fn(() => 'generated-uuid'),
}));

jest.mock('../../../../../src/utils/dal/content', () => ({
  getContentTableInstance: jest.fn(() => ({
    get: getMock,
    queryByUrl: queryByUrlMock,
    create: createMock,
  })),
}));

jest.mock('../../../../../src/utils', () => ({
  checkLanguagesPresent: (...args: any[]) => checkLanguagesPresentMock(...args),
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

  it('throws when both contentId and href are missing', async () => {
    const callback = jest.fn();
    const { main } = await import('../../../../../src/functions/workflows/content-to-speech/get');

    await expect(
      main({ args: { input: {} } }, {}, callback)
    ).rejects.toThrow('Missing contentId or url');
  });

  it('throws 404 when no item exists and href cannot be normalized', async () => {
    getMock.mockResolvedValue(null);
    queryByUrlMock.mockResolvedValue(null);
    extractPathWithTrailingSlashMock.mockReturnValue(null);

    const { main } = await import('../../../../../src/functions/workflows/content-to-speech/get');

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

  it('loads by contentId, waits until language is ready, and signs output urls', async () => {
    const callback = jest.fn();
    getMock
      .mockResolvedValueOnce({
        uuid: 'uuid-1',
        outputs: {
          en: {
            url: 'https://s3.us-east-1.amazonaws.com/audio-bucket/full/uuid-1-en.mp3',
          },
        },
      })
      .mockResolvedValueOnce({
        uuid: 'uuid-1',
        outputs: {
          en: {
            url: 'https://s3.us-east-1.amazonaws.com/audio-bucket/full/uuid-1-en.mp3',
          },
        },
      });
    checkLanguagesPresentMock
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);

    const { main } = await import('../../../../../src/functions/workflows/content-to-speech/get');

    await main(
      {
        args: {
          input: {
            contentId: 'uuid-1',
            language: 'en',
          },
        },
      },
      {},
      callback
    );

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

  it('creates a new record from href when no existing item is found', async () => {
    extractPathWithTrailingSlashMock.mockReturnValue('/story/new');
    queryByUrlMock.mockResolvedValue(null);
    createMock.mockResolvedValue({ uuid: 'generated-uuid', url: '/story/new' });
    getMock.mockResolvedValue({
      uuid: 'generated-uuid',
      outputs: {
        en: {
          url: 'https://s3.us-east-1.amazonaws.com/audio-bucket/full/generated-uuid-en.mp3',
        },
        es: {
          url: 'https://s3.us-east-1.amazonaws.com/audio-bucket/full/generated-uuid-es.mp3',
        },
      },
    });
    checkLanguagesPresentMock.mockReturnValue(true);
    formatUrlMock
      .mockReturnValueOnce('https://signed.example.com/en.mp3')
      .mockReturnValueOnce('https://signed.example.com/es.mp3');

    const callback = jest.fn();
    const { main } = await import('../../../../../src/functions/workflows/content-to-speech/get');

    await main(
      {
        args: {
          input: {
            href: 'https://www.cnn.com/story/new',
          },
        },
      },
      {},
      callback
    );

    expect(createMock).toHaveBeenCalledWith('generated-uuid', '/story/new');
    expect(callback).toHaveBeenCalledWith(null, {
      uuid: 'generated-uuid',
      outputs: [
        { code: 'en', url: 'https://signed.example.com/en.mp3' },
        { code: 'es', url: 'https://signed.example.com/es.mp3' },
      ],
    });
  });

  it('throws for invalid S3 output URLs during signing', async () => {
    getMock.mockResolvedValue({
      uuid: 'uuid-invalid',
      outputs: {
        en: {
          url: 'https://invalid-host/file.mp3',
        },
      },
    });
    checkLanguagesPresentMock.mockReturnValue(true);

    const callback = jest.fn();
    const { main } = await import('../../../../../src/functions/workflows/content-to-speech/get');

    await expect(
      main(
        {
          args: {
            input: {
              contentId: 'uuid-invalid',
            },
          },
        },
        {},
        callback
      )
    ).rejects.toThrow('Invalid S3 URL');
    expect(callback).not.toHaveBeenCalled();
  });
});
