import { pollyLanguages } from '../../../src/utils/consts/languages';
import {
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
} from '../../../src/utils/renditions';

const ALL = pollyLanguages.map((language) => language.code);
const [FIRST, SECOND] = ALL;

const withOutputs = (...codes: string[]) => ({
  outputs: Object.fromEntries(codes.map((code) => [code, { url: `s3://${code}` }])),
});

describe('supported locales', () => {
  it('preserves the existing language identifiers and their order', () => {
    expect(supportedLocaleCodes()).toEqual(ALL);
    expect(isSupportedLocale(FIRST)).toBe(true);
    expect(isSupportedLocale('xx-XX')).toBe(false);
  });

  it('maps codes back to the language objects the state machine expects', () => {
    expect(languageObjectsFor([SECOND, FIRST])).toEqual([
      pollyLanguages[0],
      pollyLanguages[1],
    ]);
    expect(languageObjectsFor([])).toEqual([]);
  });

  it('namespaces the per-locale claim attribute', () => {
    expect(renditionAttribute(FIRST)).toBe(`${RENDITION_ATTRIBUTE_PREFIX}${FIRST}`);
  });
});

describe('normalizeLocales', () => {
  it('returns the requested codes in canonical order', () => {
    expect(normalizeLocales([SECOND, FIRST])).toEqual([FIRST, SECOND]);
  });

  it('collapses duplicates', () => {
    expect(normalizeLocales([FIRST, FIRST])).toEqual([FIRST]);
  });

  it('rejects an empty request', () => {
    expect(() => normalizeLocales([])).toThrow('No languages requested');
  });

  it('rejects an unsupported code instead of dropping it', () => {
    expect(() => normalizeLocales([FIRST, 'xx-XX'])).toThrow(
      'Unsupported language: xx-XX'
    );
  });
});

describe('classify', () => {
  it('separates single, subset, and all requests', () => {
    expect(classify([FIRST])).toBe('single');
    expect(classify([FIRST, SECOND])).toBe('subset');
    expect(classify(ALL)).toBe(ALL_LOCALES);
  });
});

describe('resolveRequestedLocales', () => {
  it('never expands a single-locale request to every locale', () => {
    expect(resolveRequestedLocales({ language: FIRST })).toEqual({
      codes: [FIRST],
      localeClass: 'single',
    });
  });

  it('honours an explicit list and prefers it over a single language', () => {
    expect(resolveRequestedLocales({ languages: [SECOND, FIRST] })).toEqual({
      codes: [FIRST, SECOND],
      localeClass: 'subset',
    });
    expect(
      resolveRequestedLocales({ language: FIRST, languages: [SECOND] })
    ).toEqual({ codes: [SECOND], localeClass: 'single' });
  });

  it('keeps the deliberate all-locales path available', () => {
    expect(resolveRequestedLocales({ language: ALL_LOCALES })).toEqual({
      codes: ALL,
      localeClass: 'all',
    });
    expect(resolveRequestedLocales({ languages: ALL })).toEqual({
      codes: ALL,
      localeClass: 'all',
    });
  });

  it('falls back to every locale only when nothing was specified', () => {
    for (const input of [undefined, null, {}, { language: null }, { languages: [] }]) {
      expect(resolveRequestedLocales(input as any)).toEqual({
        codes: ALL,
        localeClass: 'all',
      });
    }
  });

  it('propagates an unsupported code', () => {
    expect(() => resolveRequestedLocales({ language: 'xx-XX' })).toThrow(
      'Unsupported language: xx-XX'
    );
  });
});

describe('cache inspection', () => {
  it('separates cached locales from the ones still to generate', () => {
    const item = withOutputs(FIRST);
    expect(cachedLocales(item, [FIRST, SECOND])).toEqual([FIRST]);
    expect(missingLocales(item, [FIRST, SECOND])).toEqual([SECOND]);
  });

  it('treats an item with no outputs as entirely uncached', () => {
    expect(cachedLocales({}, [FIRST])).toEqual([]);
    expect(missingLocales({}, [FIRST])).toEqual([FIRST]);
  });

  it('reports presence only when every requested locale is stored', () => {
    expect(renditionsPresent(withOutputs(FIRST), [FIRST])).toBe(true);
    expect(renditionsPresent(withOutputs(FIRST), [FIRST, SECOND])).toBe(false);
    expect(renditionsPresent(null, [FIRST])).toBe(false);
  });
});

describe('claims', () => {
  const now = Date.parse('2026-09-06T12:00:00.000Z');
  const fresh = new Date(now - 1000).toISOString();
  const expired = new Date(now - RENDITION_CLAIM_EXPIRY_MS - 1000).toISOString();

  it('reads the claim stored for a locale', () => {
    const item = { [renditionAttribute(FIRST)]: { status: 'queued', claimedAt: fresh } };
    expect(claimFor(item, FIRST)).toEqual({ status: 'queued', claimedAt: fresh });
    expect(claimFor(item, SECOND)).toBeUndefined();
    expect(claimFor(undefined, FIRST)).toBeUndefined();
  });

  it('allows a first claim and a retry after failure', () => {
    expect(isClaimable(undefined, now)).toBe(true);
    expect(isClaimable(null, now)).toBe(true);
    expect(isClaimable({ status: 'failed', claimedAt: fresh }, now)).toBe(true);
  });

  it('refuses to duplicate a live or completed rendition', () => {
    expect(isClaimable({ status: 'queued', claimedAt: fresh }, now)).toBe(false);
    expect(isClaimable({ status: 'running', claimedAt: fresh }, now)).toBe(false);
    expect(isClaimable({ status: 'succeeded', claimedAt: expired }, now)).toBe(false);
  });

  it('reclaims an abandoned or unreadable claim', () => {
    expect(isClaimable({ status: 'running', claimedAt: expired }, now)).toBe(true);
    expect(isClaimable({ status: 'running', claimedAt: 'not-a-date' }, now)).toBe(true);
  });

  it('lists only the locales that still need work', () => {
    const item = {
      ...withOutputs(FIRST),
      [renditionAttribute(SECOND)]: { status: 'running', claimedAt: fresh },
      [renditionAttribute(ALL[2])]: { status: 'failed', claimedAt: fresh },
    };
    expect(claimableLocales(item, [FIRST, SECOND, ALL[2], ALL[3]], now)).toEqual([
      ALL[2],
      ALL[3],
    ]);
  });
});
