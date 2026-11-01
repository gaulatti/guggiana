import { WavAssemblyError, assembleWavParts } from '../../../../src/domain/speech';

function wav(samples: number[], sampleRate = 16000, over: { format?: number; channels?: number; bits?: number } = {}): Buffer {
  const data = Buffer.alloc(samples.length * 2);
  samples.forEach((sample, index) => data.writeInt16LE(sample, index * 2));
  const out = Buffer.alloc(44);
  out.write('RIFF', 0, 'ascii');
  out.writeUInt32LE(36 + data.length, 4);
  out.write('WAVEfmt ', 8, 'ascii');
  out.writeUInt32LE(16, 16);
  out.writeUInt16LE(over.format ?? 1, 20);
  out.writeUInt16LE(over.channels ?? 1, 22);
  out.writeUInt32LE(sampleRate, 24);
  out.writeUInt32LE(sampleRate * 2, 28);
  out.writeUInt16LE(2, 32);
  out.writeUInt16LE(over.bits ?? 16, 34);
  out.write('data', 36, 'ascii');
  out.writeUInt32LE(data.length, 40);
  return Buffer.concat([out, data]);
}

const code = (fn: () => unknown) => {
  try {
    fn();
    return 'ok';
  } catch (error) {
    return error instanceof WavAssemblyError ? error.code : 'other';
  }
};
const limit = { maxBytes: 1_000_000 };

describe('assembleWavParts', () => {
  it('concatenates PCM in order under one canonical header', () => {
    const result = assembleWavParts([wav([1, 2]), wav([3]), wav([4, 5])], limit);
    expect(result.sampleRate).toBe(16000);
    expect(result.wav.length).toBe(44 + 10);
    expect(result.wav.readUInt32LE(4)).toBe(result.wav.length - 8);
    expect(result.wav.readUInt32LE(40)).toBe(10);
    expect([0, 1, 2, 3, 4].map((i) => result.wav.readInt16LE(44 + i * 2))).toEqual([1, 2, 3, 4, 5]);
    expect(assembleWavParts([result.wav], limit).wav.equals(result.wav)).toBe(true);
  });

  it('reports the duration of the assembled audio', () => {
    expect(assembleWavParts([wav(new Array(8000).fill(0)), wav(new Array(8000).fill(0))], limit).durationMs).toBe(1000);
  });

  it('accepts an empty-audio part', () => {
    expect(assembleWavParts([wav([]), wav([7])], limit).wav.length).toBe(46);
  });

  it('rejects no parts', () => {
    expect(code(() => assembleWavParts([], limit))).toBe('no_parts');
  });

  it('rejects truncated and malformed files without repairing them', () => {
    const good = wav([1, 2]);
    const corrupt = (offset: number, text: string) => {
      const copy = Buffer.from(good);
      copy.write(text, offset, 'ascii');
      return copy;
    };
    const badRiffSize = Buffer.from(good);
    badRiffSize.writeUInt32LE(1, 4);
    const badDataSize = Buffer.from(good);
    badDataSize.writeUInt32LE(2, 40);
    const oddData = Buffer.concat([wav([1]), Buffer.from([0])]);
    oddData.writeUInt32LE(oddData.length - 8, 4);
    oddData.writeUInt32LE(3, 40);
    const extraChunk = Buffer.from(good);
    extraChunk.writeUInt32LE(18, 16);
    for (const bad of [Buffer.alloc(10), good.subarray(0, 45), corrupt(0, 'RIFX'), corrupt(8, 'WAVX'), corrupt(12, 'fmtx'), corrupt(36, 'dat!'), badRiffSize, badDataSize, oddData, extraChunk]) {
      expect(code(() => assembleWavParts([bad], limit))).toBe('invalid_wav');
    }
  });

  it('rejects anything but mono 16-bit PCM', () => {
    expect(code(() => assembleWavParts([wav([1], 16000, { format: 3 })], limit))).toBe('unsupported_format');
    expect(code(() => assembleWavParts([wav([1], 16000, { channels: 2 })], limit))).toBe('unsupported_format');
    expect(code(() => assembleWavParts([wav([1], 16000, { bits: 8 })], limit))).toBe('unsupported_format');
    expect(code(() => assembleWavParts([wav([1], 0)], limit))).toBe('unsupported_format');
  });

  it('rejects mixed sample rates instead of resampling', () => {
    expect(code(() => assembleWavParts([wav([1], 16000), wav([1], 22050)], limit))).toBe('sample_rate_mismatch');
  });

  it('enforces the output bound, header included, at the exact boundary', () => {
    expect(code(() => assembleWavParts([wav([1, 2])], { maxBytes: 48 }))).toBe('ok');
    expect(code(() => assembleWavParts([wav([1, 2])], { maxBytes: 47 }))).toBe('output_too_large');
  });

  it('carries only a controlled code in errors', () => {
    expect(new WavAssemblyError('invalid_wav').message).toBe('invalid_wav');
  });
});
