from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import sys
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .contract import SynthesisRequest
from .manifest import VerifiedProvider, file_digest, load_manifest, verify_provider


class RetryableEngineError(RuntimeError):
    retry_class = "provider_transient"


class EngineTimeout(RetryableEngineError):
    retry_class = "timeout"


class PermanentEngineError(RuntimeError):
    retry_class = "permanent"


class AdapterCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class EngineResult:
    provider: str
    model: str
    model_revision: str
    runtime_revision: str
    runtime_license: str
    voice_provenance: str
    manifest_sha256: str


class EngineAdapter(Protocol):
    name: str

    def synthesize(
        self,
        request: SynthesisRequest,
        destination: Path,
        cancel: threading.Event,
        timeout_seconds: float,
        attempt: int,
    ) -> EngineResult: ...


class FakeAdapter:
    """Injected deterministic engine for ordinary tests; never a production default."""

    name = "fake"

    def __init__(
        self,
        *,
        delay_seconds: float = 0.0,
        retryable_failures: int = 0,
        permanent_failure: bool = False,
    ):
        self.delay_seconds = delay_seconds
        self.retryable_failures = retryable_failures
        self.permanent_failure = permanent_failure

    def synthesize(
        self,
        request: SynthesisRequest,
        destination: Path,
        cancel: threading.Event,
        timeout_seconds: float,
        attempt: int,
    ) -> EngineResult:
        started = time.monotonic()
        while time.monotonic() - started < self.delay_seconds:
            if cancel.wait(0.005):
                raise AdapterCancelled()
            if time.monotonic() - started >= timeout_seconds:
                raise EngineTimeout("fake synthesis timed out")
        if cancel.is_set():
            raise AdapterCancelled()
        if self.permanent_failure:
            raise PermanentEngineError("injected permanent failure")
        if attempt <= self.retryable_failures:
            raise RetryableEngineError("injected retryable failure")

        sample_rate = 16_000
        spoken = sum(
            len(segment.text or "")
            for segment in request.segments
            if segment.kind == "text"
        )
        duration_seconds = min(1.0, max(0.1, spoken * 0.005))
        frames = int(sample_rate * duration_seconds)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(destination), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(sample_rate)
            samples = bytearray()
            for index in range(frames):
                value = int(1_800 * math.sin(2 * math.pi * 220 * index / sample_rate))
                samples.extend(struct.pack("<h", value))
            audio.writeframes(samples)
        return EngineResult(
            "fake",
            "deterministic-tone",
            "1",
            "stdlib",
            "test-only",
            "synthetic",
            "0" * 64,
        )


class CandidateAdapter:
    def __init__(
        self,
        verified: VerifiedProvider,
        manifest_path: Path,
        model_root: Path,
        options: dict[str, object],
    ):
        self.name = verified.name
        self.verified = verified
        self.manifest_path = manifest_path.resolve()
        self.model_root = model_root.resolve()
        self.options = options

    def _terminate(self, process: subprocess.Popen[bytes]) -> None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def synthesize(
        self,
        request: SynthesisRequest,
        destination: Path,
        cancel: threading.Event,
        timeout_seconds: float,
        attempt: int,
    ) -> EngineResult:
        command = [
            sys.executable,
            "-m",
            "local_synthesis.runner",
            "--provider",
            self.name,
            "--model-root",
            str(self.model_root),
            "--manifest",
            str(self.manifest_path),
            "--output",
            str(destination),
        ]
        environment = os.environ.copy()
        environment["HF_HUB_OFFLINE"] = "1"
        environment["TRANSFORMERS_OFFLINE"] = "1"
        if self.name == "chatterbox":
            reference_path = self.options.get("voiceReferencePath")
            reference_sha256 = self.options.get("voiceReferenceSha256")
            consent_id = self.options.get("voiceConsentId")
            if not all(
                isinstance(value, str) and value
                for value in (reference_path, reference_sha256, consent_id)
            ):
                raise PermanentEngineError(
                    "chatterbox requires a checksummed consented reference"
                )
            device = self.options.get("device", "cpu")
            if device not in {"cpu", "mps", "cuda"}:
                raise PermanentEngineError("chatterbox device is invalid")
            command.extend(
                [
                    "--voice-reference",
                    str(reference_path),
                    "--voice-reference-sha256",
                    str(reference_sha256),
                ]
            )
            command.extend(["--device", str(device)])
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
        )
        assert process.stdin is not None
        try:
            process.stdin.write(json.dumps(request.as_dict()).encode("utf-8"))
            process.stdin.close()
            deadline = time.monotonic() + timeout_seconds
            while process.poll() is None:
                if cancel.wait(0.02):
                    self._terminate(process)
                    raise AdapterCancelled()
                if time.monotonic() >= deadline:
                    self._terminate(process)
                    raise EngineTimeout(f"{self.name} synthesis timed out")
            if process.returncode == 75:
                raise RetryableEngineError(f"{self.name} transient failure")
            if process.returncode != 0:
                raise PermanentEngineError(f"{self.name} synthesis failed")
        finally:
            if process.poll() is None:
                self._terminate(process)
        locale = self.verified.details["locales"][request.locale]
        concrete_model = str(locale.get("voice", self.verified.model))
        voice_provenance = f"{self.verified.details['voiceProvenance']} License: {locale['datasetLicense']}"
        return EngineResult(
            self.name,
            concrete_model,
            self.verified.model_revision,
            self.verified.runtime_revision,
            self.verified.runtime_license,
            voice_provenance,
            self.verified.manifest_sha256,
        )


def build_candidate_adapters(
    manifest_path: Path,
    model_root: Path,
    enabled: list[str],
    options: dict[str, dict[str, object]],
) -> dict[str, EngineAdapter]:
    if not enabled:
        raise ValueError("at least one candidate adapter must be enabled explicitly")
    if len(enabled) != len(set(enabled)) or any(
        name not in {"piper", "chatterbox"} for name in enabled
    ):
        raise ValueError("enabled providers must be unique pinned candidates")
    manifest, digest = load_manifest(manifest_path)
    built: dict[str, EngineAdapter] = {}
    for name in enabled:
        provider_options = options.get(name, {})
        allowed_options = (
            {"memoryLimitMiB"}
            if name == "piper"
            else {
                "memoryLimitMiB",
                "device",
                "voiceReferencePath",
                "voiceReferenceSha256",
                "voiceConsentId",
            }
        )
        if set(provider_options) - allowed_options:
            raise ValueError(f"enabled provider {name} has unsupported options")
        memory_limit = provider_options.get("memoryLimitMiB")
        if (
            isinstance(memory_limit, bool)
            or not isinstance(memory_limit, int)
            or not 512 <= memory_limit <= 65_536
        ):
            raise ValueError(
                f"enabled provider {name} requires an explicit bounded memoryLimitMiB"
            )
        if name == "piper" and memory_limit < 768:
            raise ValueError(
                "Piper memoryLimitMiB is below the measured safety envelope"
            )
        if name == "chatterbox":
            reference = provider_options.get("voiceReferencePath")
            checksum = provider_options.get("voiceReferenceSha256")
            consent_id = provider_options.get("voiceConsentId")
            if not all(
                isinstance(value, str) and value
                for value in (reference, checksum, consent_id)
            ):
                raise ValueError(
                    "Chatterbox requires a checksummed consented reference"
                )
            reference_path = Path(str(reference))
            if not reference_path.is_file() or file_digest(reference_path) != checksum:
                raise ValueError(
                    "Chatterbox consented reference checksum does not match"
                )
        verified = verify_provider(name, manifest, digest, model_root)
        built[name] = CandidateAdapter(
            verified, manifest_path, model_root, provider_options
        )
    return built
