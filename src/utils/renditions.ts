import { LanguageObject, pollyLanguages } from './consts/languages';

/**
 * Per-content, per-locale rendition bookkeeping.
 *
 * A rendition is one language's translation-and-synthesis workflow for one
 * article. Renditions are materialized lazily: nothing is generated until a
 * caller explicitly asks for that locale, and an already-generated artifact is
 * reused instead of regenerated.
 *
 * This module is pure. Persistence lives in the content DAL and the workflow
 * launch lives in the trigger handler.
 */

/** The deliberate "every supported locale" request token. */
const ALL_LOCALES = 'all';

/** DynamoDB attribute prefix for a per-locale claim. Flat, so the claim is a single atomic conditional write. */
const RENDITION_ATTRIBUTE_PREFIX = 'rendition#';

/**
 * A claim older than this is treated as abandoned and may be re-claimed. It
 * bounds the blast radius of a Lambda that dies between claiming a locale and
 * starting its execution.
 */
const RENDITION_CLAIM_EXPIRY_MS = 15 * 60 * 1000;

type RenditionStatus = 'queued' | 'running' | 'succeeded' | 'failed';

/** Bounded metric dimension: how much work one request asked for. */
type RequestedLocaleClass = 'single' | 'subset' | 'all';

interface RenditionClaim {
  status: RenditionStatus;
  claimedAt: string;
}

interface RequestedLocales {
  codes: string[];
  localeClass: RequestedLocaleClass;
}

interface LocaleRequestInput {
  language?: string | null;
  languages?: string[] | null;
}

/** The supported locale identifiers, unchanged from the existing contract. */
const supportedLocaleCodes = (): string[] =>
  pollyLanguages.map((language: LanguageObject) => language.code);

const isSupportedLocale = (code: string): boolean =>
  supportedLocaleCodes().includes(code);

/** The full language objects the state machine input expects, in canonical order. */
const languageObjectsFor = (codes: string[]): LanguageObject[] =>
  pollyLanguages.filter((language: LanguageObject) =>
    codes.includes(language.code)
  );

const renditionAttribute = (code: string): string =>
  `${RENDITION_ATTRIBUTE_PREFIX}${code}`;

const classify = (codes: string[]): RequestedLocaleClass => {
  if (codes.length === supportedLocaleCodes().length) return ALL_LOCALES;
  if (codes.length === 1) return 'single';
  return 'subset';
};

/**
 * Normalizes a caller's requested locales into the canonical supported order.
 * Unsupported or duplicate codes are rejected rather than silently dropped, so
 * a typo fails loudly instead of quietly generating the wrong set.
 */
const normalizeLocales = (requested: string[]): string[] => {
  if (requested.length === 0) {
    throw new Error('No languages requested');
  }
  for (const code of requested) {
    if (!isSupportedLocale(code)) {
      throw new Error(`Unsupported language: ${code}`);
    }
  }
  return supportedLocaleCodes().filter((code) => requested.includes(code));
};

/**
 * Resolves the locales a request asked for.
 *
 * - `languages: ['en-US', 'es-US']` materializes exactly those two.
 * - `language: 'en-US'` materializes exactly that one. A single-locale request
 *   is never expanded to every locale.
 * - `language: 'all'` is the deliberate all-locales path.
 * - Omitting both preserves the pre-existing `get` contract, which waited for
 *   every supported locale.
 *
 * `languages` takes precedence when both are supplied.
 */
const resolveRequestedLocales = (
  input: LocaleRequestInput | null | undefined
): RequestedLocales => {
  const languages = input?.languages;
  if (languages && languages.length > 0) {
    const codes = normalizeLocales(languages);
    return { codes, localeClass: classify(codes) };
  }

  const language = input?.language;
  if (language && language !== ALL_LOCALES) {
    const codes = normalizeLocales([language]);
    return { codes, localeClass: classify(codes) };
  }

  return { codes: supportedLocaleCodes(), localeClass: ALL_LOCALES };
};

/** Locales whose artifact already exists on the content item. */
const cachedLocales = (item: any, codes: string[]): string[] => {
  const outputs = item?.outputs || {};
  return codes.filter((code) => Boolean(outputs[code]));
};

/** Locales that still need to be generated. */
const missingLocales = (item: any, codes: string[]): string[] => {
  const cached = cachedLocales(item, codes);
  return codes.filter((code) => !cached.includes(code));
};

/** True when every requested locale has a stored artifact. */
const renditionsPresent = (item: any, codes: string[]): boolean =>
  Boolean(item) && missingLocales(item, codes).length === 0;

/**
 * Whether a locale may be claimed now: never claimed, previously failed, or
 * claimed so long ago that the claiming execution is presumed dead.
 */
const isClaimable = (
  claim: RenditionClaim | undefined | null,
  now: number
): boolean => {
  if (!claim) return true;
  if (claim.status === 'failed') return true;
  if (claim.status === 'succeeded') return false;
  const claimedAt = Date.parse(claim.claimedAt);
  if (Number.isNaN(claimedAt)) return true;
  return now - claimedAt > RENDITION_CLAIM_EXPIRY_MS;
};

/** The claim stored for a locale on a content item, if any. */
const claimFor = (
  item: any,
  code: string
): RenditionClaim | undefined => item?.[renditionAttribute(code)];

/**
 * Locales that still need work: not cached, and not already claimed by a live
 * execution. Used to decide whether a stream event is worth acting on at all.
 */
const claimableLocales = (item: any, codes: string[], now: number): string[] =>
  missingLocales(item, codes).filter((code) =>
    isClaimable(claimFor(item, code), now)
  );

export {
  ALL_LOCALES,
  RENDITION_ATTRIBUTE_PREFIX,
  RENDITION_CLAIM_EXPIRY_MS,
  cachedLocales,
  claimFor,
  claimableLocales,
  classify,
  isClaimable,
  isSupportedLocale,
  languageObjectsFor,
  missingLocales,
  normalizeLocales,
  renditionAttribute,
  renditionsPresent,
  resolveRequestedLocales,
  supportedLocaleCodes,
};
export type {
  LocaleRequestInput,
  RenditionClaim,
  RenditionStatus,
  RequestedLocaleClass,
  RequestedLocales,
};
