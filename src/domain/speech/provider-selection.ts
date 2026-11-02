import { createHash } from 'crypto';
import { LOCAL_WORKER_PROVIDERS, LocalWorkerProvider } from './worker-request';

/**
 * Explicit synthesis-provider selection for the Guggiana cutover
 * (`gaulatti/guggiana#21`).
 *
 * Dark: no Lambda or workflow calls this module, so the deployed path stays
 * Polly-only. When it is wired, an empty configuration selects Polly, rollback
 * is a single switch that forces Polly and disables dual-run, and every invalid
 * value is an error: nothing silently falls back to another provider.
 */

/** Setting names the (future) wiring layer reads; nothing reads them yet. */
export const SPEECH_PROVIDER_SETTINGS = {
  provider: 'GUGGIANA_SPEECH_PROVIDER',
  rollbackToPolly: 'GUGGIANA_SPEECH_ROLLBACK_TO_POLLY',
  dualRunProvider: 'GUGGIANA_SPEECH_DUAL_RUN_PROVIDER',
  dualRunPercent: 'GUGGIANA_SPEECH_DUAL_RUN_PERCENT',
} as const;

export type SpeechProviderName = 'polly' | LocalWorkerProvider;

export interface SpeechProviderConfig {
  /** Provider whose audio is served. Defaults to Polly. */
  readonly provider: SpeechProviderName;
  /** When true, Polly is served and dual-run is off, whatever else is set. */
  readonly rollbackToPolly: boolean;
  /** Local provider whose output is produced and discarded for comparison. */
  readonly dualRunProvider?: LocalWorkerProvider;
  /** Integer 0..100 share of operations that are also dual-run. */
  readonly dualRunPercent: number;
}

export interface SpeechProviderPlan {
  readonly primary: SpeechProviderName;
  /** Candidate run for comparison only; its audio is never served. */
  readonly shadow?: LocalWorkerProvider;
}

export class SpeechProviderConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SpeechProviderConfigError';
  }
}

type Settings = Readonly<Record<string, string | undefined>>;

const blank = (value: string | undefined): boolean => value === undefined || value === '';
const isLocal = (value: string): value is LocalWorkerProvider => (LOCAL_WORKER_PROVIDERS as readonly string[]).includes(value);

/** Parses settings strictly. Unset means the Polly default; anything else must be valid. */
export function parseSpeechProviderConfig(settings: Settings): SpeechProviderConfig {
  const rawProvider = settings[SPEECH_PROVIDER_SETTINGS.provider];
  let provider: SpeechProviderName = 'polly';
  if (!blank(rawProvider)) {
    if (rawProvider !== 'polly' && !isLocal(rawProvider as string)) {
      throw new SpeechProviderConfigError('provider must be polly, piper or chatterbox');
    }
    provider = rawProvider as SpeechProviderName;
  }

  const rawRollback = settings[SPEECH_PROVIDER_SETTINGS.rollbackToPolly];
  if (!blank(rawRollback) && rawRollback !== 'true' && rawRollback !== 'false') {
    throw new SpeechProviderConfigError('rollback must be true or false');
  }

  const rawShadow = settings[SPEECH_PROVIDER_SETTINGS.dualRunProvider];
  if (!blank(rawShadow) && !isLocal(rawShadow as string)) {
    throw new SpeechProviderConfigError('dual-run provider must be piper or chatterbox');
  }

  const rawPercent = settings[SPEECH_PROVIDER_SETTINGS.dualRunPercent];
  let dualRunPercent = 0;
  if (!blank(rawPercent)) {
    if (!/^\d{1,3}$/.test(rawPercent as string) || Number(rawPercent) > 100) {
      throw new SpeechProviderConfigError('dual-run percent must be an integer from 0 to 100');
    }
    dualRunPercent = Number(rawPercent);
  }
  if (dualRunPercent > 0 && blank(rawShadow)) {
    throw new SpeechProviderConfigError('dual-run percent requires a dual-run provider');
  }

  return {
    provider,
    rollbackToPolly: rawRollback === 'true',
    ...(blank(rawShadow) ? {} : { dualRunProvider: rawShadow as LocalWorkerProvider }),
    dualRunPercent,
  };
}

/**
 * Deterministic share of operations, keyed by an opaque operation identifier
 * (never article text), so a retry or restart lands in the same bucket.
 */
export function inDualRunSample(operationKey: string, percent: number): boolean {
  const digest = createHash('sha256').update(operationKey).digest();
  return digest.readUInt32BE(0) % 100 < percent;
}

/** Chooses what to serve and what, if anything, to run for comparison. */
export function planSpeechProvider(config: SpeechProviderConfig, operationKey: string): SpeechProviderPlan {
  if (config.rollbackToPolly) {
    return { primary: 'polly' };
  }
  const shadow = config.dualRunProvider;
  if (
    shadow !== undefined &&
    config.provider === 'polly' &&
    config.dualRunPercent > 0 &&
    inDualRunSample(operationKey, config.dualRunPercent)
  ) {
    return { primary: 'polly', shadow };
  }
  return { primary: config.provider };
}
