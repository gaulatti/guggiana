import { SPEECH_LOCALES, SpeechLocale } from './contract';

/**
 * Provider-neutral description of a supported locale. The `language` code feeds
 * translation and the `region` disambiguates variants; neither is tied to any
 * synthesis engine.
 */
export interface LocaleDefinition {
  readonly locale: SpeechLocale;
  /** ISO 639-1 language code. */
  readonly language: string;
  /** ISO 3166-1 alpha-2 region code. */
  readonly region: string;
}

const DEFINITIONS: Readonly<Record<SpeechLocale, LocaleDefinition>> = {
  'en-US': { locale: 'en-US', language: 'en', region: 'US' },
  'es-US': { locale: 'es-US', language: 'es', region: 'US' },
  'fr-FR': { locale: 'fr-FR', language: 'fr', region: 'FR' },
  'de-DE': { locale: 'de-DE', language: 'de', region: 'DE' },
  'pt-BR': { locale: 'pt-BR', language: 'pt', region: 'BR' },
};

/** All supported locale definitions, in the canonical product order. */
export const LOCALE_DEFINITIONS: readonly LocaleDefinition[] = SPEECH_LOCALES.map(
  (locale) => DEFINITIONS[locale]
);

export function isSpeechLocale(value: string): value is SpeechLocale {
  return (SPEECH_LOCALES as readonly string[]).includes(value);
}

export function getLocaleDefinition(locale: SpeechLocale): LocaleDefinition {
  return DEFINITIONS[locale];
}
