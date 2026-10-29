import {
  SPEECH_PROVIDER_SETTINGS as S,
  SpeechProviderConfigError,
  inDualRunSample,
  parseSpeechProviderConfig,
  planSpeechProvider,
} from '../../../../src/domain/speech';

describe('parseSpeechProviderConfig', () => {
  it('defaults to Polly with rollback off and no dual-run when nothing is set', () => {
    const expected = { provider: 'polly', rollbackToPolly: false, dualRunPercent: 0 };
    expect(parseSpeechProviderConfig({})).toEqual(expected);
    expect(parseSpeechProviderConfig({ [S.provider]: '', [S.rollbackToPolly]: '', [S.dualRunPercent]: '' })).toEqual(expected);
  });

  it('accepts explicit values', () => {
    expect(
      parseSpeechProviderConfig({
        [S.provider]: 'piper',
        [S.rollbackToPolly]: 'true',
        [S.dualRunProvider]: 'chatterbox',
        [S.dualRunPercent]: '100',
      })
    ).toEqual({ provider: 'piper', rollbackToPolly: true, dualRunProvider: 'chatterbox', dualRunPercent: 100 });
    expect(parseSpeechProviderConfig({ [S.provider]: 'polly', [S.rollbackToPolly]: 'false' }).provider).toBe('polly');
  });

  it('rejects every invalid value instead of falling back', () => {
    const bad: Record<string, string>[] = [
      { [S.provider]: 'POLLY' },
      { [S.provider]: 'gemini' },
      { [S.rollbackToPolly]: 'yes' },
      { [S.dualRunProvider]: 'polly' },
      { [S.dualRunPercent]: '101' },
      { [S.dualRunPercent]: '-1' },
      { [S.dualRunPercent]: '1.5' },
      { [S.dualRunPercent]: '1000' },
      { [S.dualRunPercent]: '10' },
    ];
    for (const settings of bad) {
      expect(() => parseSpeechProviderConfig(settings)).toThrow(SpeechProviderConfigError);
    }
  });
});

describe('planSpeechProvider', () => {
  const base = { provider: 'polly', rollbackToPolly: false, dualRunPercent: 0 } as const;

  it('serves Polly by default and never runs a shadow', () => {
    for (const key of ['a', 'b', 'c']) {
      expect(planSpeechProvider(parseSpeechProviderConfig({}), key)).toEqual({ primary: 'polly' });
    }
  });

  it('serves the configured local provider only when explicitly selected', () => {
    expect(planSpeechProvider({ ...base, provider: 'piper' }, 'k')).toEqual({ primary: 'piper' });
  });

  it('rollback forces Polly and disables dual-run', () => {
    const config = { ...base, provider: 'piper', rollbackToPolly: true, dualRunProvider: 'chatterbox', dualRunPercent: 100 } as const;
    expect(planSpeechProvider(config, 'k')).toEqual({ primary: 'polly' });
  });

  it('dual-runs a deterministic sample behind Polly, never serving the shadow', () => {
    const config = { ...base, dualRunProvider: 'piper', dualRunPercent: 100 } as const;
    expect(planSpeechProvider(config, 'k')).toEqual({ primary: 'polly', shadow: 'piper' });
    expect(planSpeechProvider({ ...config, dualRunPercent: 0 }, 'k')).toEqual({ primary: 'polly' });
    const half = { ...config, dualRunPercent: 50 };
    const keys = Array.from({ length: 400 }, (_, i) => `op-${i}`);
    const hits = keys.filter((k) => planSpeechProvider(half, k).shadow === 'piper').length;
    expect(hits).toBeGreaterThan(140);
    expect(hits).toBeLessThan(260);
    expect(keys.map((k) => inDualRunSample(k, 50))).toEqual(keys.map((k) => inDualRunSample(k, 50)));
  });

  it('does not dual-run when a local provider is already primary', () => {
    const config = { ...base, provider: 'piper', dualRunProvider: 'chatterbox', dualRunPercent: 100 } as const;
    expect(planSpeechProvider(config, 'k')).toEqual({ primary: 'piper' });
  });
});
