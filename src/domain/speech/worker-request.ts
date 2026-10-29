import {
  AUDIO_ENCODING,
  ProviderCapabilities,
  SPEECH_LOCALES,
  SpeechDocument,
  SpeechLocale,
  SpeechSegment,
  VoiceRole,
} from './contract';
import { validateSpeechDocument } from './validate';

/**
 * Mapping from the provider-neutral {@link SpeechDocument} to the request
 * accepted by the local synthesis worker (`worker/local_synthesis/contract.py`).
 *
 * Groundwork only: nothing calls this module and the deployed workflow is
 * unchanged. The provider is always explicit; there is no default and no
 * Polly fallback.
 */

/** Adapters the worker can enable (`worker/config/model-manifest.json`). */
export const LOCAL_WORKER_PROVIDERS = ['piper', 'chatterbox'] as const;
export type LocalWorkerProvider = (typeof LOCAL_WORKER_PROVIDERS)[number];

/** Fixed bounds of the worker contract; keep in sync with `contract.py`. */
export const LOCAL_WORKER_LIMITS = {
  maxSegments: 64,
  maxSegmentChars: 2_900,
  maxDocumentChars: 20_000,
  maxPauseMs: 5_000,
} as const;

/** The exact JSON body of `POST /v1/jobs`. */
export interface LocalWorkerRequest {
  readonly provider: LocalWorkerProvider;
  readonly locale: SpeechLocale;
  readonly voiceRole: VoiceRole;
  readonly segments: readonly SpeechSegment[];
}

export type LocalWorkerRequestErrorCode = 'provider_unavailable' | 'invalid_document' | 'chunk_too_large';

export class LocalWorkerRequestError extends Error {
  constructor(
    readonly code: LocalWorkerRequestErrorCode,
    message: string
  ) {
    super(message);
    this.name = 'LocalWorkerRequestError';
  }
}

const WORKER_CAPABILITIES: ProviderCapabilities = {
  provider: 'local-worker',
  model: 'local-worker-contract',
  modelRevision: '1',
  locales: SPEECH_LOCALES,
  voiceRoles: ['narrator'],
  maxSegmentChars: LOCAL_WORKER_LIMITS.maxSegmentChars,
  minPauseMs: 0,
  maxPauseMs: LOCAL_WORKER_LIMITS.maxPauseMs,
  audio: { encoding: AUDIO_ENCODING, sampleRateHz: 22_050, channels: 1 },
};

const spokenChars = (segments: readonly SpeechSegment[]): number =>
  segments.reduce((total, segment) => total + (segment.kind === 'text' ? segment.text.length : 0), 0);

/**
 * Converts one document into one or more ordered worker requests.
 *
 * A long article exceeds the worker's 64-segment / 20,000-character job bound,
 * so the document is split only at text boundaries (a pause stays with the
 * text it precedes; trailing pauses stay with the last text). The caller
 * synthesizes the requests in order and assembles the returned PCM before the
 * single MP3 encode. The document is validated first and never repaired; a
 * chunk that still exceeds a bound is an error rather than silently altered.
 */
export function toLocalWorkerRequests(provider: string, document: SpeechDocument): LocalWorkerRequest[] {
  if (!(LOCAL_WORKER_PROVIDERS as readonly string[]).includes(provider)) {
    throw new LocalWorkerRequestError('provider_unavailable', 'provider must name an enabled worker adapter');
  }
  const validation = validateSpeechDocument(document, WORKER_CAPABILITIES);
  if (!validation.ok) {
    throw new LocalWorkerRequestError('invalid_document', `${validation.code}: ${validation.reason}`);
  }

  // Validation guarantees at least one text segment, so at least one unit.
  const units: SpeechSegment[][] = [];
  let pending: SpeechSegment[] = [];
  for (const segment of document.segments) {
    pending.push(segment);
    if (segment.kind === 'text') {
      units.push(pending);
      pending = [];
    }
  }
  units[units.length - 1].push(...pending);

  const chunks: SpeechSegment[][] = [];
  for (const unit of units) {
    const current = chunks[chunks.length - 1];
    if (
      current !== undefined &&
      current.length + unit.length <= LOCAL_WORKER_LIMITS.maxSegments &&
      spokenChars(current) + spokenChars(unit) <= LOCAL_WORKER_LIMITS.maxDocumentChars
    ) {
      current.push(...unit);
    } else {
      chunks.push([...unit]);
    }
  }

  return chunks.map((segments) => {
    if (segments.length > LOCAL_WORKER_LIMITS.maxSegments) {
      throw new LocalWorkerRequestError('chunk_too_large', 'a text unit exceeds the worker segment bound');
    }
    return {
      provider: provider as LocalWorkerProvider,
      locale: document.locale,
      voiceRole: document.voice,
      segments,
    };
  });
}
