import { LocalWorkerClientError, LocalWorkerRequest, WorkerFetch, createLocalWorkerClient } from '../../../../src/domain/speech';

const ID = '123e4567-e89b-12d3-a456-426614174000';
const request: LocalWorkerRequest = {
  provider: 'piper',
  locale: 'en-US',
  voiceRole: 'narrator',
  segments: [{ kind: 'text', text: 'Secret article text.' }],
};

const reply = (status: number, body: unknown = {}, bytes = new ArrayBuffer(0)) => ({
  status,
  json: async () => body,
  arrayBuffer: async () => bytes,
});

const make = (fetch: WorkerFetch, over: Record<string, unknown> = {}) =>
  createLocalWorkerClient({ baseUrl: 'http://127.0.0.1:8080', token: 'tok-1', fetch, timeoutMs: 1000, maxArtifactBytes: 8, ...over });

const code = (promise: Promise<unknown>) => promise.then(() => 'ok', (e) => (e instanceof LocalWorkerClientError ? e.code : 'other'));

describe('local worker client', () => {
  it('submits the exact request with bearer auth and parses the status', async () => {
    const fetch = jest.fn(async () => reply(202, { id: ID, state: 'queued', attempts: 0, createdAt: 'x' }));
    const status = await make(fetch).submit(request);
    expect(status).toEqual({ id: ID, state: 'queued', attempts: 0 });
    const [url, init] = fetch.mock.calls[0] as unknown as [string, { method: string; headers: Record<string, string>; body: string; signal: AbortSignal }];
    expect(url).toBe('http://127.0.0.1:8080/v1/jobs');
    expect(init.method).toBe('POST');
    expect(init.headers).toEqual({ Authorization: 'Bearer tok-1', 'Content-Type': 'application/json' });
    expect(JSON.parse(init.body)).toEqual(request);
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it('reads status, failure details and cancels', async () => {
    const failed = { id: ID, state: 'failed', attempts: 2, failure: { code: 'engine_error', retryClass: 'permanent' } };
    const fetch = jest.fn(async () => reply(200, failed));
    const client = make(fetch);
    expect(await client.status(ID)).toEqual(failed);
    expect(await client.cancel(ID)).toEqual(failed);
    expect(fetch.mock.calls.map((c) => (c as unknown as [string, { method: string }])[1].method)).toEqual(['GET', 'DELETE']);
    expect((fetch.mock.calls[0] as unknown as [string, { headers: object }])[1].headers).toEqual({ Authorization: 'Bearer tok-1' });
    const odd = make(async () => reply(200, { id: ID, state: 'running', attempts: 1, failure: { code: 1 } }));
    expect(await odd.status(ID)).toEqual({ id: ID, state: 'running', attempts: 1 });
  });

  it('returns artifact bytes within the bound and rejects larger ones', async () => {
    const bytes = new Uint8Array([1, 2, 3]).buffer;
    expect(Array.from(await make(async () => reply(200, {}, bytes)).artifact(ID))).toEqual([1, 2, 3]);
    expect(await code(make(async () => reply(200, {}, new ArrayBuffer(9))).artifact(ID))).toBe('artifact_too_large');
    const broken = { status: 200, json: async () => ({}), arrayBuffer: async () => Promise.reject(new Error('x')) };
    expect(await code(make(async () => broken).artifact(ID))).toBe('unavailable');
  });

  it('maps HTTP outcomes to controlled codes', async () => {
    const outcomes: [number, string][] = [[401, 'unauthorized'], [404, 'not_found'], [429, 'queue_overloaded'], [400, 'rejected'], [413, 'rejected'], [503, 'unavailable']];
    for (const [status, expected] of outcomes) {
      expect(await code(make(async () => reply(status)).submit(request))).toBe(expected);
    }
  });

  it('never leaks request text, tokens or URLs in errors', async () => {
    const failing = make(async () => Promise.reject(new Error('boom tok-1 Secret article text http://127.0.0.1:8080')));
    const error = await failing.submit(request).catch((e) => e as Error);
    expect(error).toBeInstanceOf(LocalWorkerClientError);
    expect((error as LocalWorkerClientError).code).toBe('unavailable');
    expect(`${(error as Error).message}${(error as Error).stack?.split('\n')[0]}`).not.toMatch(/tok-1|Secret|127\.0\.0\.1/);
  });

  it('rejects malformed worker responses', async () => {
    const bodies: unknown[] = [
      null,
      'str',
      {},
      { id: 'not-an-id', state: 'queued', attempts: 0 },
      { id: 5, state: 'queued', attempts: 0 },
      { id: ID, state: 'weird', attempts: 0 },
      { id: ID, state: 7, attempts: 0 },
      { id: ID, state: 'queued', attempts: '0' },
    ];
    for (const body of bodies) {
      expect(await code(make(async () => reply(200, body)).status(ID))).toBe('invalid_response');
    }
    const notJson = { status: 200, json: async () => Promise.reject(new Error('x')), arrayBuffer: async () => new ArrayBuffer(0) };
    expect(await code(make(async () => notJson).status(ID))).toBe('invalid_response');
  });

  it('refuses bad configuration and job ids before any call', async () => {
    const fetch = jest.fn(async () => reply(200));
    const bad = [{ baseUrl: 'nonsense' }, { baseUrl: 'ftp://x' }, { token: '' }, { timeoutMs: 0 }, { maxArtifactBytes: 0 }];
    for (const over of bad) {
      expect(() => make(fetch, over)).toThrow(expect.objectContaining({ code: 'invalid_configuration' }));
    }
    const client = make(fetch);
    for (const call of [client.status, client.cancel, client.artifact]) {
      expect(await code(call('../x'))).toBe('invalid_configuration');
    }
    expect(fetch).not.toHaveBeenCalled();
  });
});
