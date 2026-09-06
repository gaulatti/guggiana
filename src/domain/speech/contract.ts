/**
 * Provider-neutral speech-synthesis domain contract.
 *
 * This module intentionally contains no Polly voice IDs, no SSML, no Step
 * Functions task tokens, and no S3/callback assumptions. Provider adapters own
 * that translation. Nothing here changes the deployed workflow; it exists so
 * local engines can be evaluated and implemented against a stable shape and
 * wired only after quality and operational gates pass.
 */

/** The five product locales Guggiana supports. */
export const SPEECH_LOCALES = ['en-US', 'es-US', 'fr-FR', 'de-DE', 'pt-BR'] as const;
export type SpeechLocale = (typeof SPEECH_LOCALES)[number];

/**
 * Semantic voice roles. Callers ask for a role, never a provider voice name;
 * the adapter maps the role to a concrete voice for its engine.
 */
export const VOICE_ROLES = ['narrator'] as const;
export type VoiceRole = (typeof VOICE_ROLES)[number];

/**
 * A unit of a speech document. Text is plain — never SSML — and pauses are
 * explicit and measured in milliseconds rather than encoded into markup.
 */
export type SpeechSegment =
  | { readonly kind: 'text'; readonly text: string }
  | { readonly kind: 'pause'; readonly durationMs: number };

/** The full request handed to a provider adapter. */
export interface SpeechDocument {
  readonly locale: SpeechLocale;
  readonly voice: VoiceRole;
  readonly segments: readonly SpeechSegment[];
}

/**
 * Synthesis output is linear PCM (little-endian signed 16-bit) until a single
 * final encode after assembly. Adapters must normalize to this.
 */
export const AUDIO_ENCODING = 'pcm_s16le' as const;
export type AudioEncoding = typeof AUDIO_ENCODING;

export interface AudioFormat {
  readonly encoding: AudioEncoding;
  readonly sampleRateHz: number;
  readonly channels: 1;
}

/** What a provider adapter declares it can do. */
export interface ProviderCapabilities {
  readonly provider: string;
  readonly model: string;
  readonly modelRevision: string;
  readonly locales: readonly SpeechLocale[];
  readonly voiceRoles: readonly VoiceRole[];
  readonly maxSegmentChars: number;
  readonly minPauseMs: number;
  readonly maxPauseMs: number;
  readonly audio: AudioFormat;
}

/** Asynchronous synthesis job lifecycle. There is no invisible provider fallback. */
export const SYNTHESIS_JOB_STATES = ['queued', 'running', 'succeeded', 'failed'] as const;
export type SynthesisJobState = (typeof SYNTHESIS_JOB_STATES)[number];

/** Bounded failure vocabulary. Adapters map engine errors onto these codes. */
export const SYNTHESIS_FAILURE_CODES = [
  'empty_document',
  'unsupported_locale',
  'unsupported_voice_role',
  'segment_too_long',
  'invalid_pause',
  'provider_unavailable',
] as const;
export type SynthesisFailureCode = (typeof SYNTHESIS_FAILURE_CODES)[number];

/** Metadata pinned to a successful artifact. */
export interface SynthesisArtifactMetadata {
  readonly provider: string;
  readonly model: string;
  readonly modelRevision: string;
  readonly voice: VoiceRole;
  readonly locale: SpeechLocale;
  readonly durationMs: number;
  readonly sampleRateHz: number;
  readonly encoding: AudioEncoding;
  readonly checksumSha256: string;
}

export interface SynthesisJob {
  readonly id: string;
  readonly state: SynthesisJobState;
  readonly document: SpeechDocument;
  readonly metadata?: SynthesisArtifactMetadata;
  readonly failureCode?: SynthesisFailureCode;
  readonly failureReason?: string;
}
