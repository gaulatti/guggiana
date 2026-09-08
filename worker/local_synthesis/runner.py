from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import wave
from pathlib import Path
from typing import Any

from .contract import SynthesisRequest, parse_request
from .manifest import file_digest, load_manifest, verify_provider


def _write_wav(destination: Path, sample_rate: int, pcm: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(pcm)
    os.chmod(destination, 0o600)


def _piper(
    request: SynthesisRequest, root: Path, details: dict[str, Any], destination: Path
) -> None:
    from piper import PiperVoice

    locale = details["locales"][request.locale]
    model = root / "piper" / locale["modelPath"]
    config = root / "piper" / locale["configPath"]
    voice = PiperVoice.load(str(model), config_path=str(config))
    sample_rate: int | None = None
    pcm = bytearray()
    for segment in request.segments:
        if segment.kind == "pause":
            if sample_rate is None:
                sample_rate = int(locale["sampleRateHz"])
            pcm.extend(b"\0\0" * int(sample_rate * (segment.duration_ms or 0) / 1000))
            continue
        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            voice.synthesize_wav(segment.text or "", audio)
        output.seek(0)
        with wave.open(output, "rb") as audio:
            if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
                raise RuntimeError("piper emitted unsupported audio")
            if sample_rate is None:
                sample_rate = audio.getframerate()
            if audio.getframerate() != sample_rate:
                raise RuntimeError("piper emitted inconsistent sample rates")
            pcm.extend(audio.readframes(audio.getnframes()))
    _write_wav(destination, sample_rate or int(locale["sampleRateHz"]), bytes(pcm))


def _chatterbox(
    request: SynthesisRequest,
    root: Path,
    details: dict[str, Any],
    destination: Path,
    reference: Path,
    reference_sha256: str,
    device: str,
) -> None:
    if not reference.is_file() or file_digest(reference) != reference_sha256:
        raise RuntimeError("consented reference checksum mismatch")
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    checkpoint = root / "chatterbox" / details["checkpointDirectory"]
    model = ChatterboxMultilingualTTS.from_local(
        checkpoint,
        device=device,
        t3_model=str(details["checkpointFile"]),
    )
    sample_rate = int(model.sr)
    pcm = bytearray()
    language_id = details["locales"][request.locale]["languageId"]
    for index, segment in enumerate(request.segments):
        if segment.kind == "pause":
            pcm.extend(b"\0\0" * int(sample_rate * (segment.duration_ms or 0) / 1000))
            continue
        seed = 20260906 + int(
            hashlib.sha256(f"{request.locale}:{index}".encode()).hexdigest()[:8], 16
        )
        torch.manual_seed(seed)
        waveform = model.generate(
            segment.text or "",
            language_id=language_id,
            audio_prompt_path=str(reference),
        )
        samples = waveform.detach().cpu().squeeze().clamp(-1, 1)
        pcm.extend((samples * 32767).to(torch.int16).numpy().tobytes())
    _write_wav(destination, sample_rate, bytes(pcm))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("piper", "chatterbox"), required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--voice-reference", type=Path)
    parser.add_argument("--voice-reference-sha256")
    parser.add_argument("--device", choices=("cpu", "mps", "cuda"), default="cpu")
    arguments = parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
        request = parse_request(payload, {arguments.provider})
        manifest, digest = load_manifest(arguments.manifest)
        verified = verify_provider(
            arguments.provider, manifest, digest, arguments.model_root
        )
        if arguments.provider == "piper":
            _piper(request, arguments.model_root, verified.details, arguments.output)
        else:
            if not arguments.voice_reference or not arguments.voice_reference_sha256:
                raise RuntimeError("consented reference is required")
            _chatterbox(
                request,
                arguments.model_root,
                verified.details,
                arguments.output,
                arguments.voice_reference,
                arguments.voice_reference_sha256,
                arguments.device,
            )
    # The isolated child exposes only a controlled exit class; engine exceptions
    # and their potentially content-bearing messages never cross the boundary.
    except Exception:  # noqa: BLE001
        return 70
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
