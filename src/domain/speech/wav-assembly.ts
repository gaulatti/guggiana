/**
 * Assembles the ordered WAV artifacts of one article into a single mono PCM16
 * WAV, so the single MP3 encode (`gaulatti/guggiana#21`) happens once, after
 * assembly, as `docs/speech-synthesis-contract.md` requires.
 *
 * Dark: no Lambda calls this module. It is strict and pure: every input must be
 * a canonical mono, 16-bit PCM RIFF/WAVE file from the local worker, all at one
 * sample rate. Anything else is an error; nothing is resampled, padded or
 * repaired, and errors carry a controlled code only (never audio or text).
 */

export type WavAssemblyErrorCode = 'no_parts' | 'invalid_wav' | 'unsupported_format' | 'sample_rate_mismatch' | 'output_too_large';

export class WavAssemblyError extends Error {
  constructor(readonly code: WavAssemblyErrorCode) {
    super(code);
    this.name = 'WavAssemblyError';
  }
}

export interface WavAssemblyOptions {
  /** Largest assembled WAV accepted, header included. */
  readonly maxBytes: number;
}

export interface AssembledWav {
  readonly wav: Buffer;
  readonly sampleRate: number;
  readonly durationMs: number;
}

const HEADER_BYTES = 44;
const BYTES_PER_SAMPLE = 2;

interface ParsedWav {
  readonly sampleRate: number;
  readonly pcm: Buffer;
}

/** Parses the canonical 44-byte-header WAV the worker writes. */
function parseWav(bytes: Buffer): ParsedWav {
  if (bytes.length < HEADER_BYTES) {
    throw new WavAssemblyError('invalid_wav');
  }
  const canonical =
    bytes.toString('ascii', 0, 4) === 'RIFF' &&
    bytes.toString('ascii', 8, 12) === 'WAVE' &&
    bytes.toString('ascii', 12, 16) === 'fmt ' &&
    bytes.readUInt32LE(16) === 16 &&
    bytes.toString('ascii', 36, 40) === 'data' &&
    bytes.readUInt32LE(4) === bytes.length - 8 &&
    bytes.readUInt32LE(40) === bytes.length - HEADER_BYTES;
  if (!canonical || bytes.readUInt32LE(40) % BYTES_PER_SAMPLE !== 0) {
    throw new WavAssemblyError('invalid_wav');
  }
  const pcmFormat = bytes.readUInt16LE(20) === 1;
  const mono = bytes.readUInt16LE(22) === 1;
  const sixteenBit = bytes.readUInt16LE(34) === 16;
  const sampleRate = bytes.readUInt32LE(24);
  if (!pcmFormat || !mono || !sixteenBit || sampleRate === 0) {
    throw new WavAssemblyError('unsupported_format');
  }
  return { sampleRate, pcm: bytes.subarray(HEADER_BYTES) };
}

function header(sampleRate: number, dataBytes: number): Buffer {
  const out = Buffer.alloc(HEADER_BYTES);
  out.write('RIFF', 0, 'ascii');
  out.writeUInt32LE(HEADER_BYTES - 8 + dataBytes, 4);
  out.write('WAVEfmt ', 8, 'ascii');
  out.writeUInt32LE(16, 16);
  out.writeUInt16LE(1, 20);
  out.writeUInt16LE(1, 22);
  out.writeUInt32LE(sampleRate, 24);
  out.writeUInt32LE(sampleRate * BYTES_PER_SAMPLE, 28);
  out.writeUInt16LE(BYTES_PER_SAMPLE, 32);
  out.writeUInt16LE(16, 34);
  out.write('data', 36, 'ascii');
  out.writeUInt32LE(dataBytes, 40);
  return out;
}

/** Concatenates the parts, in the given order, into one WAV. */
export function assembleWavParts(parts: readonly Buffer[], options: WavAssemblyOptions): AssembledWav {
  if (parts.length === 0) {
    throw new WavAssemblyError('no_parts');
  }
  const parsed = parts.map(parseWav);
  const sampleRate = parsed[0].sampleRate;
  if (parsed.some((part) => part.sampleRate !== sampleRate)) {
    throw new WavAssemblyError('sample_rate_mismatch');
  }
  const dataBytes = parsed.reduce((total, part) => total + part.pcm.length, 0);
  if (HEADER_BYTES + dataBytes > options.maxBytes) {
    throw new WavAssemblyError('output_too_large');
  }
  return {
    wav: Buffer.concat([header(sampleRate, dataBytes), ...parsed.map((part) => part.pcm)]),
    sampleRate,
    durationMs: Math.round((dataBytes / BYTES_PER_SAMPLE / sampleRate) * 1000),
  };
}
