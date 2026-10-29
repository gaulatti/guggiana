import { LocalWorkerRequest } from './worker-request';

/**
 * Plain request/response client for the local synthesis worker's HTTP API
 * (`worker/README.md`). Groundwork for `gaulatti/guggiana#21`; nothing calls it.
 *
 * It is stateless: it holds only the base URL, bearer token and an injected
 * `fetch`. It stores nothing, never logs, and its errors carry a controlled
 * code only, never request text, response bodies, URLs or the token.
 */

export type LocalWorkerJobState = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';

export interface LocalWorkerJobStatus {
  readonly id: string;
  readonly state: LocalWorkerJobState;
  readonly attempts: number;
  readonly failure?: { readonly code: string; readonly retryClass: string };
}

export type LocalWorkerClientErrorCode =
  | 'invalid_configuration'
  | 'unauthorized'
  | 'queue_overloaded'
  | 'rejected'
  | 'not_found'
  | 'unavailable'
  | 'invalid_response'
  | 'artifact_too_large';

export class LocalWorkerClientError extends Error {
  constructor(readonly code: LocalWorkerClientErrorCode) {
    super(code);
    this.name = 'LocalWorkerClientError';
  }
}

export type WorkerFetch = (url: string, init: { method: string; headers: Record<string, string>; body?: string; signal: AbortSignal }) => Promise<{
  status: number;
  json(): Promise<unknown>;
  arrayBuffer(): Promise<ArrayBuffer>;
}>;

export interface LocalWorkerClientOptions {
  readonly baseUrl: string;
  readonly token: string;
  readonly fetch: WorkerFetch;
  /** Per-call deadline; the client never retries. */
  readonly timeoutMs: number;
  /** Largest artifact accepted (the worker caps its own at 512 MiB). */
  readonly maxArtifactBytes: number;
}

const JOB_ID = /^[0-9a-f-]{36}$/;
const STATES: readonly string[] = ['queued', 'running', 'succeeded', 'failed', 'cancelled'];

export interface LocalWorkerClient {
  submit(request: LocalWorkerRequest): Promise<LocalWorkerJobStatus>;
  status(jobId: string): Promise<LocalWorkerJobStatus>;
  cancel(jobId: string): Promise<LocalWorkerJobStatus>;
  artifact(jobId: string): Promise<Uint8Array>;
}

export function createLocalWorkerClient(options: LocalWorkerClientOptions): LocalWorkerClient {
  let base: URL;
  try {
    base = new URL(options.baseUrl);
  } catch {
    throw new LocalWorkerClientError('invalid_configuration');
  }
  if (
    (base.protocol !== 'http:' && base.protocol !== 'https:') ||
    options.token === '' ||
    !(options.timeoutMs > 0) ||
    !(options.maxArtifactBytes > 0)
  ) {
    throw new LocalWorkerClientError('invalid_configuration');
  }

  const call = async (method: string, path: string, body?: unknown) => {
    const headers: Record<string, string> = { Authorization: `Bearer ${options.token}` };
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
    }
    let response;
    try {
      response = await options.fetch(new URL(path, base).toString(), {
        method,
        headers,
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        signal: AbortSignal.timeout(options.timeoutMs),
      });
    } catch {
      throw new LocalWorkerClientError('unavailable');
    }
    if (response.status === 401) throw new LocalWorkerClientError('unauthorized');
    if (response.status === 404) throw new LocalWorkerClientError('not_found');
    if (response.status === 429) throw new LocalWorkerClientError('queue_overloaded');
    if (response.status >= 500) throw new LocalWorkerClientError('unavailable');
    if (response.status >= 400) throw new LocalWorkerClientError('rejected');
    return response;
  };

  const toStatus = async (response: { json(): Promise<unknown> }): Promise<LocalWorkerJobStatus> => {
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      throw new LocalWorkerClientError('invalid_response');
    }
    const value = payload as Record<string, unknown> | null;
    if (
      typeof value !== 'object' ||
      value === null ||
      typeof value.id !== 'string' ||
      !JOB_ID.test(value.id) ||
      typeof value.state !== 'string' ||
      !STATES.includes(value.state) ||
      typeof value.attempts !== 'number'
    ) {
      throw new LocalWorkerClientError('invalid_response');
    }
    const failure = value.failure as Record<string, unknown> | undefined;
    return {
      id: value.id,
      state: value.state as LocalWorkerJobState,
      attempts: value.attempts,
      ...(failure && typeof failure.code === 'string' && typeof failure.retryClass === 'string'
        ? { failure: { code: failure.code, retryClass: failure.retryClass } }
        : {}),
    };
  };

  const requireId = (jobId: string): void => {
    if (!JOB_ID.test(jobId)) throw new LocalWorkerClientError('invalid_configuration');
  };

  return {
    submit: async (request) => toStatus(await call('POST', '/v1/jobs', request)),
    status: async (jobId) => {
      requireId(jobId);
      return toStatus(await call('GET', `/v1/jobs/${jobId}`));
    },
    cancel: async (jobId) => {
      requireId(jobId);
      return toStatus(await call('DELETE', `/v1/jobs/${jobId}`));
    },
    artifact: async (jobId) => {
      requireId(jobId);
      const response = await call('GET', `/v1/jobs/${jobId}/artifact`);
      let bytes: ArrayBuffer;
      try {
        bytes = await response.arrayBuffer();
      } catch {
        throw new LocalWorkerClientError('unavailable');
      }
      if (bytes.byteLength > options.maxArtifactBytes) throw new LocalWorkerClientError('artifact_too_large');
      return new Uint8Array(bytes);
    },
  };
}
