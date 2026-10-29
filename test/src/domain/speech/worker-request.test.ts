import {
  LOCAL_WORKER_LIMITS,
  LocalWorkerRequestError,
  SpeechDocument,
  SpeechSegment,
  composeArticleSpeechDocument,
  toLocalWorkerRequests,
} from '../../../../src/domain/speech';

const doc = (segments: SpeechSegment[]): SpeechDocument => ({ locale: 'de-DE', voice: 'narrator', segments });
const text = (value: string): SpeechSegment => ({ kind: 'text', text: value });
const pause = (durationMs: number): SpeechSegment => ({ kind: 'pause', durationMs });

describe('toLocalWorkerRequests', () => {
  it('maps a document to exactly the worker request shape with an explicit provider', () => {
    const segments = [text('Hallo.'), pause(450), text('Welt.')];
    expect(toLocalWorkerRequests('piper', doc(segments))).toEqual([
      { provider: 'piper', locale: 'de-DE', voiceRole: 'narrator', segments },
    ]);
  });

  it('has no default provider and rejects anything but an enabled adapter', () => {
    for (const provider of ['', 'polly', 'PIPER']) {
      expect(() => toLocalWorkerRequests(provider, doc([text('x')]))).toThrow(
        expect.objectContaining({ name: 'LocalWorkerRequestError', code: 'provider_unavailable' })
      );
    }
    expect(toLocalWorkerRequests('chatterbox', doc([text('x')]))[0].provider).toBe('chatterbox');
  });

  it.each([
    ['no spoken text', doc([pause(10)])],
    ['an oversized text segment', doc([text('a'.repeat(LOCAL_WORKER_LIMITS.maxSegmentChars + 1))])],
    ['an out-of-range pause', doc([text('x'), pause(LOCAL_WORKER_LIMITS.maxPauseMs + 1)])],
    ['an unsupported locale', { locale: 'ja-JP', voice: 'narrator', segments: [text('x')] } as unknown as SpeechDocument],
  ])('fails closed on %s without repairing it', (_name, document) => {
    expect(() => toLocalWorkerRequests('piper', document)).toThrow(
      expect.objectContaining({ code: 'invalid_document' })
    );
  });

  it('splits long articles at text boundaries, keeping order, pauses and every character', () => {
    const paragraphs = Array.from({ length: 100 }, (_, i) => `Paragraph ${i}.`);
    const document = composeArticleSpeechDocument({
      locale: 'en-US',
      title: 'Title',
      byline: 'By Someone',
      body: paragraphs.join('\n'),
    });
    const requests = toLocalWorkerRequests('piper', document);

    expect(requests.length).toBeGreaterThan(1);
    expect(requests.flatMap((r) => r.segments)).toEqual(document.segments);
    for (const request of requests) {
      expect(request.segments.length).toBeLessThanOrEqual(LOCAL_WORKER_LIMITS.maxSegments);
      expect(request.segments.some((s) => s.kind === 'text')).toBe(true);
      expect(request.segments[request.segments.length - 1].kind).toBe('text');
    }
    // A pause between chunks travels with the text it precedes.
    expect(requests[1].segments[0].kind).toBe('pause');
  });

  it('splits on the character bound and keeps trailing pauses with the last text', () => {
    const big = 'a'.repeat(LOCAL_WORKER_LIMITS.maxSegmentChars);
    const segments = [text(big), text(big), text(big), text(big), text(big), text(big), text(big), text('tail'), pause(900)];
    const requests = toLocalWorkerRequests('piper', doc(segments));

    expect(requests).toHaveLength(2);
    expect(requests[0].segments).toHaveLength(6);
    expect(requests[1].segments).toEqual([text(big), text('tail'), pause(900)]);
  });

  it('rejects a single text unit whose leading pauses exceed the segment bound', () => {
    const pauses = Array.from({ length: LOCAL_WORKER_LIMITS.maxSegments }, () => pause(1));
    expect(() => toLocalWorkerRequests('piper', doc([...pauses, text('x')]))).toThrow(
      expect.objectContaining({ code: 'chunk_too_large' })
    );
    expect(new LocalWorkerRequestError('chunk_too_large', 'm')).toBeInstanceOf(Error);
  });
});
