import { Readable } from 'stream';

const s3SendMock = jest.fn();
const sfnSendMock = jest.fn();
const getMock = jest.fn();
const updateRenderedMock = jest.fn();
const updateStatusMock = jest.fn();
const execSyncMock = jest.fn();

jest.mock('child_process', () => ({
  execSync: (...args: any[]) => execSyncMock(...args),
}));

jest.mock('fs', () => {
  const actual = jest.requireActual('fs');
  const { Readable } = jest.requireActual('stream');
  return {
    ...actual,
    createReadStream: jest.fn(() => Readable.from(['merged-audio'])),
  };
});

jest.mock('../../../../src/utils/dal/content', () => ({
  ContentStatus: { FAILED: 'FAILED' },
  getContentTableInstance: jest.fn(() => ({
    get: getMock,
    updateRendered: updateRenderedMock,
    updateStatus: updateStatusMock,
  })),
}));

jest.mock('@aws-sdk/client-s3', () => {
  class GetObjectCommand {
    input: any;
    constructor(input: any) {
      this.input = input;
    }
  }

  class PutObjectCommand {
    input: any;
    constructor(input: any) {
      this.input = input;
    }
  }

  class S3Client {
    send = s3SendMock;
  }

  return {
    GetObjectCommand,
    PutObjectCommand,
    S3Client,
  };
});

jest.mock('@aws-sdk/client-sfn', () => {
  class SendTaskSuccessCommand {
    input: any;
    constructor(input: any) {
      this.input = input;
    }
  }

  class SendTaskFailureCommand {
    input: any;
    constructor(input: any) {
      this.input = input;
    }
  }

  class SFNClient {
    send = sfnSendMock;
  }

  return {
    SFNClient,
    SendTaskSuccessCommand,
    SendTaskFailureCommand,
  };
});

describe('src/functions/tts/merge_files main', () => {
  const originalEnv = process.env;

  beforeEach(() => {
    jest.resetModules();
    jest.clearAllMocks();
    process.env = {
      ...originalEnv,
      TABLE_NAME: 'content-table',
      BUCKET_NAME: 'audio-bucket',
    };
    sfnSendMock.mockResolvedValue({ ok: true });
    execSyncMock.mockReturnValue(Buffer.from('ffmpeg complete'));
  });

  afterAll(() => {
    process.env = originalEnv;
  });

  it('merges audio files, uploads output, and reports task success', async () => {
    s3SendMock
      .mockResolvedValueOnce({ Body: Readable.from(['title-audio']) })
      .mockResolvedValueOnce({ Body: Readable.from(['paragraph-audio']) })
      .mockResolvedValueOnce({ ETag: 'etag-1' });
    getMock.mockResolvedValue({ outputs: { en: { url: 'old' } } });

    const callback = jest.fn();
    const { main } = await import('../../../../src/functions/tts/merge_files');
    const event = {
      uuid: 'uuid-1',
      token: 'token-1',
      language: 'en',
      title: 'https://s3.us-east-1.amazonaws.com/audio-bucket/title/title.mp3',
      text: [
        {
          url: 'https://s3.us-east-1.amazonaws.com/audio-bucket/paragraphs/p1.mp3',
        },
      ],
    };

    const result = await main(event, {}, callback);

    expect(result).toEqual(event);
    expect(execSyncMock).toHaveBeenCalledWith(
      expect.stringContaining('ffmpeg -f concat -safe 0'),
      { timeout: 10000 }
    );
    expect(getMock).toHaveBeenCalledWith('uuid-1');
    expect(updateRenderedMock).toHaveBeenCalledWith('uuid-1', {
      en: {
        url: 'https://s3.us-east-1.amazonaws.com/audio-bucket/full/uuid-1-en.mp3',
      },
    });

    const successCommand = sfnSendMock.mock.calls[0][0];
    expect(successCommand.input).toEqual({
      taskToken: 'token-1',
      output: JSON.stringify({
        uuid: 'uuid-1',
        outputs: {
          en: {
            url: 'https://s3.us-east-1.amazonaws.com/audio-bucket/full/uuid-1-en.mp3',
          },
        },
      }),
    });
    expect(callback).toHaveBeenCalledWith(null, event);
  });

  it('continues when ffmpeg returns stderr through exec error object', async () => {
    execSyncMock.mockImplementation(() => {
      throw { stderr: Buffer.from('ffmpeg warning') };
    });

    s3SendMock
      .mockResolvedValueOnce({ Body: Readable.from(['title-audio']) })
      .mockResolvedValueOnce({ ETag: 'etag-1' });
    getMock.mockResolvedValue({ outputs: {} });

    const { main } = await import('../../../../src/functions/tts/merge_files');
    await main(
      {
        uuid: 'uuid-2',
        token: 'token-2',
        language: 'es',
        title: 'https://s3.us-east-1.amazonaws.com/audio-bucket/title/title.mp3',
        text: [],
      },
      {},
      jest.fn()
    );

    expect(updateRenderedMock).toHaveBeenCalledWith('uuid-2', {
      es: {
        url: 'https://s3.us-east-1.amazonaws.com/audio-bucket/full/uuid-2-es.mp3',
      },
    });
    expect(updateStatusMock).not.toHaveBeenCalled();
  });

  it('continues when ffmpeg throws without stderr and still succeeds', async () => {
    execSyncMock.mockImplementation(() => {
      throw new Error('ffmpeg missing');
    });

    s3SendMock
      .mockResolvedValueOnce({ Body: Readable.from(['title-audio']) })
      .mockResolvedValueOnce({ ETag: 'etag-1' });
    getMock.mockResolvedValue({ outputs: {} });

    const { main } = await import('../../../../src/functions/tts/merge_files');
    await main(
      {
        uuid: 'uuid-3',
        token: 'token-3',
        language: 'fr',
        title: 'https://s3.us-east-1.amazonaws.com/audio-bucket/title/title.mp3',
        text: [],
      },
      {},
      jest.fn()
    );

    expect(updateRenderedMock).toHaveBeenCalledWith('uuid-3', {
      fr: {
        url: 'https://s3.us-east-1.amazonaws.com/audio-bucket/full/uuid-3-fr.mp3',
      },
    });
    expect(updateStatusMock).not.toHaveBeenCalled();
  });

  it('updates failed status and sends task failure when S3 body is missing', async () => {
    s3SendMock.mockResolvedValueOnce({});

    const { main } = await import('../../../../src/functions/tts/merge_files');
    await main(
      {
        uuid: 'uuid-fail',
        token: 'token-fail',
        language: 'pt',
        title: 'https://s3.us-east-1.amazonaws.com/audio-bucket/title/title.mp3',
        text: [],
      },
      {},
      jest.fn()
    );

    expect(updateStatusMock).toHaveBeenCalledWith('uuid-fail', 'FAILED');
    const failureCommand = sfnSendMock.mock.calls[0][0];
    expect(failureCommand.input).toEqual({
      taskToken: 'token-fail',
      output: JSON.stringify({ uuid: 'uuid-fail' }),
    });
    expect(updateRenderedMock).not.toHaveBeenCalled();
  });

  it('uses default empty text and initializes outputs when article is missing', async () => {
    s3SendMock
      .mockResolvedValueOnce({ Body: Readable.from(['title-audio']) })
      .mockResolvedValueOnce({ ETag: 'etag-1' });
    getMock.mockResolvedValue(null);

    const { main } = await import('../../../../src/functions/tts/merge_files');
    await main(
      {
        uuid: 'uuid-no-article',
        token: 'token-no-article',
        language: 'de',
        title: 'https://s3.us-east-1.amazonaws.com/audio-bucket/title/title.mp3',
      },
      {},
      jest.fn()
    );

    expect(updateRenderedMock).toHaveBeenCalledWith('uuid-no-article', {
      de: {
        url: 'https://s3.us-east-1.amazonaws.com/audio-bucket/full/uuid-no-article-de.mp3',
      },
    });
  });
});
