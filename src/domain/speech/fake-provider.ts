import { createHash } from 'crypto';

import {
  AUDIO_ENCODING,
  ProviderCapabilities,
  SPEECH_LOCALES,
  SpeechDocument,
  SpeechLocale,
  SynthesisArtifactMetadata,
  SynthesisFailureCode,
  SynthesisJob,
  VOICE_ROLES,
} from './contract';
import { SpeechProvider } from './provider';
import { validateSpeechDocument } from './validate';

/** Rough spoken duration: characters times a fixed per-character cost. */
const MS_PER_CHARACTER = 60;

/** Base capabilities of the deterministic fake engine. */
export const FAKE_PROVIDER_CAPABILITIES: ProviderCapabilities = {
  provider: 'fake',
  model: 'fake-tts',
  modelRevision: '2026-09-06',
  locales: SPEECH_LOCALES,
  voiceRoles: VOICE_ROLES,
  maxSegmentChars: 2900,
  minPauseMs: 0,
  maxPauseMs: 5000,
  audio: { encoding: AUDIO_ENCODING, sampleRateHz: 24_000, channels: 1 },
};

export interface FakeProviderOptions {
  /** Force every job to fail on its running step with this code. */
  readonly failWith?: SynthesisFailureCode;
  /** Restrict supported locales (defaults to all product locales). */
  readonly locales?: readonly SpeechLocale[];
}

/** Deterministic estimated duration for a document, in milliseconds. */
export function estimateDurationMs(document: SpeechDocument): number {
  return document.segments.reduce(
    (total, segment) =>
      total + (segment.kind === 'text' ? segment.text.length * MS_PER_CHARACTER : segment.durationMs),
    0
  );
}

function buildMetadata(
  document: SpeechDocument,
  capabilities: ProviderCapabilities
): SynthesisArtifactMetadata {
  const canonical = JSON.stringify({
    locale: document.locale,
    voice: document.voice,
    segments: document.segments,
  });
  const checksumSha256 = createHash('sha256')
    .update(`${capabilities.model}@${capabilities.modelRevision}:${canonical}`)
    .digest('hex');
  return {
    provider: capabilities.provider,
    model: capabilities.model,
    modelRevision: capabilities.modelRevision,
    voice: document.voice,
    locale: document.locale,
    durationMs: estimateDurationMs(document),
    sampleRateHz: capabilities.audio.sampleRateHz,
    encoding: AUDIO_ENCODING,
    checksumSha256,
  };
}

/**
 * A deterministic in-memory {@link SpeechProvider} for contract tests and local
 * evaluation. Job IDs, checksums, and durations are stable for equal inputs.
 */
export function createFakeSpeechProvider(options: FakeProviderOptions = {}): SpeechProvider {
  const capabilities = (): ProviderCapabilities => ({
    ...FAKE_PROVIDER_CAPABILITIES,
    locales: options.locales ?? FAKE_PROVIDER_CAPABILITIES.locales,
  });

  let counter = 0;

  const createJob = (document: SpeechDocument): SynthesisJob => {
    counter += 1;
    return { id: `fake-${counter}`, state: 'queued', document };
  };

  const advance = (job: SynthesisJob): SynthesisJob => {
    if (job.state === 'queued') {
      return { ...job, state: 'running' };
    }
    if (job.state === 'running') {
      if (options.failWith) {
        return {
          ...job,
          state: 'failed',
          failureCode: options.failWith,
          failureReason: `forced failure: ${options.failWith}`,
        };
      }
      const validation = validateSpeechDocument(job.document, capabilities());
      if (!validation.ok) {
        return { ...job, state: 'failed', failureCode: validation.code, failureReason: validation.reason };
      }
      return { ...job, state: 'succeeded', metadata: buildMetadata(job.document, capabilities()) };
    }
    return job;
  };

  return { capabilities, createJob, advance };
}
