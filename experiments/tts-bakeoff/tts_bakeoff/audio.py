from __future__ import annotations

import hashlib
import math
import struct
import wave
from pathlib import Path
from typing import Any


class AudioValidationError(ValueError):
    """A synthesis output is not a usable PCM WAV artifact."""


def inspect_wav(path: Path, target: dict[str, int] | None = None) -> dict[str, Any]:
    try:
        with wave.open(str(path), "rb") as audio:
            channels = audio.getnchannels()
            sample_width = audio.getsampwidth()
            sample_rate = audio.getframerate()
            frames = audio.getnframes()
            compression = audio.getcomptype()
            pcm = audio.readframes(frames)
    except (OSError, EOFError, wave.Error) as error:
        raise AudioValidationError(f"not a readable PCM WAV: {error}") from error

    if compression != "NONE" or channels < 1 or sample_width != 2 or sample_rate <= 0 or frames <= 0:
        raise AudioValidationError("expected non-empty 16-bit uncompressed PCM WAV")
    expected_pcm_bytes = frames * channels * sample_width
    if len(pcm) != expected_pcm_bytes:
        raise AudioValidationError(
            f"truncated PCM payload: expected {expected_pcm_bytes} bytes, decoded {len(pcm)}"
        )
    duration = frames / sample_rate
    if duration <= 0.05:
        raise AudioValidationError("audio is too short to be meaningful")

    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
    if rms < 30:
        raise AudioValidationError("audio is silent or below the minimum signal threshold")
    clipping_fraction = sum(abs(sample) >= 32760 for sample in samples) / len(samples)

    repeat = repeated_window_heuristic(pcm, sample_rate, channels)
    target_observation = "not-applicable"
    target_outside = None
    if target:
        target_outside = not (target["min"] <= duration <= target["max"])
        target_observation = "outside-target" if target_outside else "within-target"

    return {
        "duration_seconds": round(duration, 6),
        "format": "wav",
        "encoding": "pcm_s16le",
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "sample_width_bytes": sample_width,
        "frames": frames,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "signal": {
            "rms": round(rms, 3),
            "clipping_fraction": round(clipping_fraction, 8),
            "silent": False,
        },
        "truncation": {
            "status": "unverified",
            "method": "duration target only; semantic transcript or human review required",
            "duration_target_observation": target_observation,
            "outside_target": target_outside,
        },
        "repetition": {
            "status": "unverified",
            "method": "exact non-silent 500 ms PCM window heuristic; semantic transcript or human review required",
            **repeat,
        },
    }


def repeated_window_heuristic(pcm: bytes, sample_rate: int, channels: int) -> dict[str, Any]:
    frame_bytes = channels * 2
    window_bytes = max(1, sample_rate // 2) * frame_bytes
    seen: dict[str, int] = {}
    repeated = 0
    inspected = 0
    for offset in range(0, len(pcm) - window_bytes + 1, window_bytes):
        chunk = pcm[offset : offset + window_bytes]
        samples = struct.unpack(f"<{len(chunk) // 2}h", chunk)
        rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
        if rms < 30:
            continue
        inspected += 1
        digest = hashlib.sha256(chunk).hexdigest()
        if digest in seen:
            repeated += 1
        seen[digest] = seen.get(digest, 0) + 1
    return {"inspected_non_silent_windows": inspected, "exact_repeated_windows": repeated}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
