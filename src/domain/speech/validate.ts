import {
  ProviderCapabilities,
  SpeechDocument,
  SynthesisFailureCode,
} from './contract';

export type ValidationResult =
  | { readonly ok: true }
  | { readonly ok: false; readonly code: SynthesisFailureCode; readonly reason: string };

function fail(code: SynthesisFailureCode, reason: string): ValidationResult {
  return { ok: false, code, reason };
}

/**
 * Validates a {@link SpeechDocument} against a provider's declared
 * {@link ProviderCapabilities}. Fails closed with a bounded
 * {@link SynthesisFailureCode}; never repairs the document.
 */
export function validateSpeechDocument(
  document: SpeechDocument,
  capabilities: ProviderCapabilities
): ValidationResult {
  if (!capabilities.locales.includes(document.locale)) {
    return fail('unsupported_locale', `locale "${document.locale}" is not supported by ${capabilities.provider}`);
  }
  if (!capabilities.voiceRoles.includes(document.voice)) {
    return fail('unsupported_voice_role', `voice role "${document.voice}" is not supported by ${capabilities.provider}`);
  }

  let spokenSegments = 0;
  for (const segment of document.segments) {
    if (segment.kind === 'text') {
      if (segment.text.trim().length === 0) {
        return fail('empty_document', 'a text segment contains no spoken text');
      }
      if (segment.text.length > capabilities.maxSegmentChars) {
        return fail('segment_too_long', `a text segment exceeds ${capabilities.maxSegmentChars} characters`);
      }
      spokenSegments += 1;
    } else if (
      !Number.isInteger(segment.durationMs) ||
      segment.durationMs < capabilities.minPauseMs ||
      segment.durationMs > capabilities.maxPauseMs
    ) {
      return fail(
        'invalid_pause',
        `pause of ${segment.durationMs}ms is outside the supported ${capabilities.minPauseMs}-${capabilities.maxPauseMs}ms range`
      );
    }
  }

  if (spokenSegments === 0) {
    return fail('empty_document', 'document has no spoken text');
  }
  return { ok: true };
}
