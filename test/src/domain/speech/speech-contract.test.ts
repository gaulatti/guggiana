import {
  AUDIO_ENCODING,
  LOCALE_DEFINITIONS,
  PARAGRAPH_PAUSE_MS,
  ProviderCapabilities,
  SPEECH_LOCALES,
  SYNTHESIS_FAILURE_CODES,
  SYNTHESIS_JOB_STATES,
  SpeechDocument,
  TITLE_PAUSE_MS,
  VOICE_ROLES,
  composeArticleSpeechDocument,
  createFakeSpeechProvider,
  estimateDurationMs,
  FAKE_PROVIDER_CAPABILITIES,
  getLocaleDefinition,
  isSpeechLocale,
  isTerminal,
  runToCompletion,
  validateSpeechDocument,
} from '../../../../src/domain/speech';

const caps = (overrides: Partial<ProviderCapabilities> = {}): ProviderCapabilities => ({
  ...FAKE_PROVIDER_CAPABILITIES,
  ...overrides,
});

const textDoc = (segments: SpeechDocument['segments']): SpeechDocument => ({
  locale: 'en-US',
  voice: 'narrator',
  segments,
});

describe('speech contract constants', () => {
  it('pins the five product locales and the job/failure vocabularies', () => {
    expect([...SPEECH_LOCALES]).toEqual(['en-US', 'es-US', 'fr-FR', 'de-DE', 'pt-BR']);
    expect([...VOICE_ROLES]).toEqual(['narrator']);
    expect([...SYNTHESIS_JOB_STATES]).toEqual(['queued', 'running', 'succeeded', 'failed']);
    expect(SYNTHESIS_FAILURE_CODES).toContain('unsupported_locale');
    expect(AUDIO_ENCODING).toBe('pcm_s16le');
  });
});

describe('locales', () => {
  it('exposes a neutral definition for every locale in canonical order', () => {
    expect(LOCALE_DEFINITIONS.map((d) => d.locale)).toEqual([...SPEECH_LOCALES]);
    expect(LOCALE_DEFINITIONS.every((d) => /^[a-z]{2}$/.test(d.language) && /^[A-Z]{2}$/.test(d.region))).toBe(true);
    expect(getLocaleDefinition('pt-BR')).toEqual({ locale: 'pt-BR', language: 'pt', region: 'BR' });
  });

  it('narrows unknown strings', () => {
    expect(isSpeechLocale('en-US')).toBe(true);
    expect(isSpeechLocale('ja-JP')).toBe(false);
  });
});

describe('composeArticleSpeechDocument', () => {
  it('represents the full title + byline + multi-paragraph shape without SSML', () => {
    const doc = composeArticleSpeechDocument({
      locale: 'es-US',
      title: '  Breaking news  ',
      byline: 'By A. Reporter',
      body: 'First paragraph.\n\n  Second paragraph.  \n',
    });
    expect(doc.locale).toBe('es-US');
    expect(doc.voice).toBe('narrator');
    expect(doc.segments).toEqual([
      { kind: 'text', text: 'Breaking news' },
      { kind: 'pause', durationMs: PARAGRAPH_PAUSE_MS },
      { kind: 'text', text: 'By A. Reporter' },
      { kind: 'pause', durationMs: TITLE_PAUSE_MS },
      { kind: 'text', text: 'First paragraph.' },
      { kind: 'pause', durationMs: PARAGRAPH_PAUSE_MS },
      { kind: 'text', text: 'Second paragraph.' },
    ]);
    expect(JSON.stringify(doc)).not.toMatch(/<speak>|<p>/);
  });

  it('honours an explicit voice role', () => {
    const doc = composeArticleSpeechDocument({ locale: 'en-US', voice: 'narrator', title: 'T', byline: '', body: '' });
    expect(doc.voice).toBe('narrator');
  });

  it('drops an empty title but keeps the byline', () => {
    const doc = composeArticleSpeechDocument({ locale: 'en-US', title: '   ', byline: 'Byline', body: '' });
    expect(doc.segments).toEqual([{ kind: 'text', text: 'Byline' }]);
  });

  it('emits body paragraphs alone when title and byline are empty', () => {
    const doc = composeArticleSpeechDocument({ locale: 'en-US', title: '', byline: '', body: 'Only body.' });
    expect(doc.segments).toEqual([{ kind: 'text', text: 'Only body.' }]);
  });

  it('produces nothing spoken for an entirely empty article', () => {
    const doc = composeArticleSpeechDocument({ locale: 'en-US', title: '', byline: '', body: '   \n  ' });
    expect(doc.segments).toEqual([]);
  });
});

describe('validateSpeechDocument', () => {
  it('accepts a well-formed document', () => {
    expect(validateSpeechDocument(textDoc([{ kind: 'text', text: 'Hello' }, { kind: 'pause', durationMs: 300 }]), caps())).toEqual({ ok: true });
  });

  it('rejects an unsupported locale', () => {
    expect(validateSpeechDocument(textDoc([{ kind: 'text', text: 'Hi' }]), caps({ locales: ['fr-FR'] }))).toMatchObject({ ok: false, code: 'unsupported_locale' });
  });

  it('rejects an unsupported voice role', () => {
    const doc = { ...textDoc([{ kind: 'text', text: 'Hi' }]), voice: 'narrator' as const };
    expect(validateSpeechDocument(doc, caps({ voiceRoles: [] }))).toMatchObject({ ok: false, code: 'unsupported_voice_role' });
  });

  it('rejects a document with no spoken text', () => {
    expect(validateSpeechDocument(textDoc([{ kind: 'pause', durationMs: 100 }]), caps())).toMatchObject({ ok: false, code: 'empty_document' });
  });

  it('rejects a blank text segment', () => {
    expect(validateSpeechDocument(textDoc([{ kind: 'text', text: '   ' }]), caps())).toMatchObject({ ok: false, code: 'empty_document' });
  });

  it('rejects an over-long text segment', () => {
    expect(validateSpeechDocument(textDoc([{ kind: 'text', text: 'x'.repeat(10) }]), caps({ maxSegmentChars: 5 }))).toMatchObject({ ok: false, code: 'segment_too_long' });
  });

  it('rejects non-integer, too-short, and too-long pauses', () => {
    expect(validateSpeechDocument(textDoc([{ kind: 'text', text: 'a' }, { kind: 'pause', durationMs: 1.5 }]), caps())).toMatchObject({ ok: false, code: 'invalid_pause' });
    expect(validateSpeechDocument(textDoc([{ kind: 'text', text: 'a' }, { kind: 'pause', durationMs: -1 }]), caps({ minPauseMs: 0 }))).toMatchObject({ ok: false, code: 'invalid_pause' });
    expect(validateSpeechDocument(textDoc([{ kind: 'text', text: 'a' }, { kind: 'pause', durationMs: 9999 }]), caps({ maxPauseMs: 1000 }))).toMatchObject({ ok: false, code: 'invalid_pause' });
  });
});

describe('estimateDurationMs', () => {
  it('sums text cost and pause durations', () => {
    expect(estimateDurationMs(textDoc([{ kind: 'text', text: 'abc' }, { kind: 'pause', durationMs: 500 }]))).toBe(3 * 60 + 500);
  });
});

describe('fake provider', () => {
  it('progresses queued -> running -> succeeded with pinned metadata', () => {
    const provider = createFakeSpeechProvider();
    const document = composeArticleSpeechDocument({ locale: 'en-US', title: 'Title', byline: 'Byline', body: 'Body paragraph.' });
    const job = provider.createJob(document);
    expect(job).toMatchObject({ id: 'fake-1', state: 'queued' });
    const running = provider.advance(job);
    expect(running.state).toBe('running');
    const done = provider.advance(running);
    expect(done.state).toBe('succeeded');
    expect(done.metadata).toMatchObject({
      provider: 'fake',
      model: 'fake-tts',
      modelRevision: '2026-09-06',
      voice: 'narrator',
      locale: 'en-US',
      sampleRateHz: 24_000,
      encoding: AUDIO_ENCODING,
    });
    expect(done.metadata?.checksumSha256).toMatch(/^[a-f0-9]{64}$/);
    expect(done.metadata?.durationMs).toBe(estimateDurationMs(document));
  });

  it('is deterministic: equal documents yield equal checksums', () => {
    const document = textDoc([{ kind: 'text', text: 'Stable' }]);
    const a = runToCompletion(createFakeSpeechProvider(), document);
    const b = runToCompletion(createFakeSpeechProvider(), document);
    expect(a.metadata?.checksumSha256).toBe(b.metadata?.checksumSha256);
  });

  it('fails a job when the document is invalid for the adapter', () => {
    const provider = createFakeSpeechProvider({ locales: ['fr-FR'] });
    const job = runToCompletion(provider, textDoc([{ kind: 'text', text: 'Hi' }]));
    expect(job).toMatchObject({ state: 'failed', failureCode: 'unsupported_locale' });
    expect(job.failureReason).toContain('not supported');
  });

  it('fails a job on a forced failure code', () => {
    const provider = createFakeSpeechProvider({ failWith: 'provider_unavailable' });
    const job = runToCompletion(provider, textDoc([{ kind: 'text', text: 'Hi' }]));
    expect(job).toMatchObject({ state: 'failed', failureCode: 'provider_unavailable' });
    expect(job.failureReason).toContain('forced failure');
  });

  it('treats terminal jobs as idempotent', () => {
    const provider = createFakeSpeechProvider();
    const done = runToCompletion(provider, textDoc([{ kind: 'text', text: 'Hi' }]));
    expect(isTerminal(done)).toBe(true);
    expect(provider.advance(done)).toEqual(done);
  });

  it('reports its capabilities', () => {
    expect(createFakeSpeechProvider().capabilities().locales).toEqual([...SPEECH_LOCALES]);
    expect(createFakeSpeechProvider({ locales: ['en-US'] }).capabilities().locales).toEqual(['en-US']);
  });

  it('validates every product locale end to end', () => {
    for (const locale of SPEECH_LOCALES) {
      const job = runToCompletion(createFakeSpeechProvider(), { locale, voice: 'narrator', segments: [{ kind: 'text', text: 'Test' }] });
      expect(job.state).toBe('succeeded');
    }
  });
});
