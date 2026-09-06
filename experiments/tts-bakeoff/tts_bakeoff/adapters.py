from __future__ import annotations

import math
import os
import hashlib
import struct
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .catalog import file_digest


class EngineUnavailable(RuntimeError):
    """An optional engine cannot run in the current explicit environment."""


@dataclass
class SynthesisMeasurement:
    cold_load_seconds: float | None
    synthesis_seconds: float
    model: str
    voice: str
    backend: str


class Adapter:
    name = "base"

    def synthesize(
        self, fixture: dict[str, Any], destination: Path
    ) -> SynthesisMeasurement:
        raise NotImplementedError


class FakeAdapter(Adapter):
    """Deterministic offline adapter used only to exercise the harness."""

    name = "fake"

    def synthesize(self, fixture: dict[str, Any], destination: Path) -> SynthesisMeasurement:
        start = time.perf_counter_ns()
        sample_rate = 16_000
        duration = 2.0 if fixture["category"] != "long-form" else 46.0
        frames = int(sample_rate * duration)
        locale_offset = sum(ord(character) for character in fixture["locale"]) % 70
        frequency = 220 + locale_offset
        destination.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(destination), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(sample_rate)
            block = bytearray()
            for index in range(frames):
                window = index // (sample_rate // 2)
                amplitude = 1800 + (window * 7) % 300
                value = int(amplitude * math.sin(2 * math.pi * frequency * index / sample_rate))
                block.extend(struct.pack("<h", value))
                if len(block) >= sample_rate * 2:
                    audio.writeframesraw(block)
                    block.clear()
            if block:
                audio.writeframesraw(block)
        elapsed = (time.perf_counter_ns() - start) / 1_000_000_000
        return SynthesisMeasurement(0.0, elapsed, "deterministic-tone-v1", "synthetic", "stdlib")


class PiperAdapter(Adapter):
    name = "piper"

    def __init__(
        self,
        engine_config: dict[str, Any],
        model_dir: Path,
        espeak_data_dir: Path | None = None,
    ):
        self.config = engine_config
        self.model_dir = model_dir
        self.espeak_data_dir = espeak_data_dir
        self.loaded: dict[str, Any] = {}
        try:
            from piper import PiperVoice
        except ImportError as error:
            raise EngineUnavailable(
                "piper-tts is not installed; sync the pinned piper extra"
            ) from error
        self.voice_class = PiperVoice

    def _load(self, locale: str) -> tuple[Any, float | None, dict[str, Any]]:
        mapping = self.config["locale_mapping"][locale]
        model = self.model_dir / mapping["path"]
        model_config = Path(f"{model}.json")
        if not model.is_file() or not model_config.is_file():
            raise EngineUnavailable(
                f"verified Piper model is absent for {locale}; run the explicit fetch command"
            )
        if file_digest(model, "md5") != mapping["model_md5"]:
            raise EngineUnavailable(f"Piper model checksum mismatch for {locale}")
        if file_digest(model) != mapping["model_sha256"]:
            raise EngineUnavailable(f"Piper model SHA-256 mismatch for {locale}")
        if file_digest(model_config, "md5") != mapping["config_md5"]:
            raise EngineUnavailable(f"Piper config checksum mismatch for {locale}")
        model_card = model.parent / "MODEL_CARD"
        if not model_card.is_file() or file_digest(model_card, "md5") != mapping["model_card_md5"]:
            raise EngineUnavailable(f"Piper model-card provenance mismatch for {locale}")
        if locale in self.loaded:
            return self.loaded[locale], None, mapping
        start = time.perf_counter_ns()
        load_options: dict[str, Any] = {"config_path": str(model_config)}
        if self.espeak_data_dir:
            if not (self.espeak_data_dir / "phontab").is_file():
                raise EngineUnavailable("explicit Piper eSpeak data directory is invalid")
            load_options["espeak_data_dir"] = str(self.espeak_data_dir)
        voice = self.voice_class.load(str(model), **load_options)
        elapsed = (time.perf_counter_ns() - start) / 1_000_000_000
        self.loaded[locale] = voice
        return voice, elapsed, mapping

    def synthesize(self, fixture: dict[str, Any], destination: Path) -> SynthesisMeasurement:
        voice, cold_load, mapping = self._load(fixture["locale"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        start = time.perf_counter_ns()
        with wave.open(str(destination), "wb") as audio:
            voice.synthesize_wav(fixture["text"], audio)
        elapsed = (time.perf_counter_ns() - start) / 1_000_000_000
        return SynthesisMeasurement(
            cold_load,
            elapsed,
            mapping["voice"],
            mapping["voice"],
            "onnxruntime-cpu",
        )


class ChatterboxAdapter(Adapter):
    name = "chatterbox"

    def __init__(
        self,
        engine_config: dict[str, Any],
        model_dir: Path,
        voice_reference: Path | None,
        voice_reference_id: str | None,
        device: str,
        seed: int,
    ):
        if not voice_reference or not voice_reference.is_file():
            raise EngineUnavailable(
                "Chatterbox requires a consented local voice reference via --voice-reference"
            )
        if not voice_reference_id:
            raise EngineUnavailable(
                "Chatterbox requires an opaque consent/provenance ID via --voice-reference-id"
            )
        self.config = engine_config
        self.model_dir = model_dir
        self.voice_reference = voice_reference
        self.voice_reference_id = voice_reference_id
        self.device = device
        self.seed = seed
        self.loaded: dict[str, Any] = {}
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            import torch
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        except ImportError as error:
            raise EngineUnavailable(
                "chatterbox-tts is not installed; sync the pinned chatterbox extra"
            ) from error
        self.torch = torch
        self.model_class = ChatterboxMultilingualTTS

    def _sync_device(self) -> None:
        if self.device == "mps" and self.torch.backends.mps.is_available():
            self.torch.mps.synchronize()

    def _load(self, locale: str) -> tuple[Any, float | None, dict[str, Any]]:
        mapping = self.config["locale_mapping"][locale]
        model_name = mapping["model"]
        details = self.config["models"][model_name]
        checkpoint_dir = self.model_dir / model_name
        t3_file = checkpoint_dir / details["file"]
        if not t3_file.is_file() or file_digest(t3_file) != details["sha256"]:
            raise EngineUnavailable(f"verified Chatterbox checkpoint is absent for {locale}")
        for required_file in details["required_files"]:
            filename = required_file["local_file"]
            candidate = checkpoint_dir / filename
            if not candidate.is_file() or file_digest(candidate) != required_file["sha256"]:
                raise EngineUnavailable(f"Chatterbox file is absent or invalid: {filename}")
        if model_name in self.loaded:
            return self.loaded[model_name], None, mapping
        self._sync_device()
        start = time.perf_counter_ns()
        model = self.model_class.from_local(
            checkpoint_dir, device=self.device, t3_model=details["file"]
        )
        self._sync_device()
        elapsed = (time.perf_counter_ns() - start) / 1_000_000_000
        self.loaded[model_name] = model
        return model, elapsed, mapping

    def synthesize(self, fixture: dict[str, Any], destination: Path) -> SynthesisMeasurement:
        model, cold_load, mapping = self._load(fixture["locale"])
        fixture_seed = self.seed + int(hashlib.sha256(fixture["id"].encode()).hexdigest()[:8], 16)
        self.torch.manual_seed(fixture_seed)
        self._sync_device()
        start = time.perf_counter_ns()
        waveform = model.generate(
            fixture["text"],
            language_id=mapping["language_id"],
            audio_prompt_path=str(self.voice_reference),
        )
        self._sync_device()
        destination.parent.mkdir(parents=True, exist_ok=True)
        samples = waveform.detach().cpu().squeeze().clamp(-1, 1)
        pcm = (samples * 32767).to(self.torch.int16).numpy().tobytes()
        with wave.open(str(destination), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(int(model.sr))
            audio.writeframes(pcm)
        elapsed = (time.perf_counter_ns() - start) / 1_000_000_000
        return SynthesisMeasurement(
            cold_load,
            elapsed,
            mapping["model"],
            self.voice_reference_id,
            self.device,
        )


class PollyAdapter(Adapter):
    name = "polly"

    def __init__(self, engine_config: dict[str, Any], allow_network: bool, region: str | None):
        if not allow_network:
            raise EngineUnavailable("Polly is disabled unless --allow-network is explicitly supplied")
        try:
            import boto3
        except ImportError as error:
            raise EngineUnavailable("boto3 is not installed; sync the pinned polly extra") from error
        self.config = engine_config
        self.client = boto3.client("polly", region_name=region)

    def synthesize(self, fixture: dict[str, Any], destination: Path) -> SynthesisMeasurement:
        mapping = self.config["locale_mapping"][fixture["locale"]]
        destination.parent.mkdir(parents=True, exist_ok=True)
        start = time.perf_counter_ns()
        response = self.client.synthesize_speech(
            Engine=mapping["engine"],
            OutputFormat="pcm",
            SampleRate="16000",
            Text=fixture["text"],
            TextType="text",
            VoiceId=mapping["voice"],
        )
        pcm = response["AudioStream"].read()
        with wave.open(str(destination), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16_000)
            audio.writeframes(pcm)
        elapsed = (time.perf_counter_ns() - start) / 1_000_000_000
        return SynthesisMeasurement(None, elapsed, "aws-polly-neural", mapping["voice"], "aws-api")


def build_adapter(
    name: str,
    config: dict[str, Any],
    model_dir: Path,
    allow_network: bool = False,
    region: str | None = None,
    voice_reference: Path | None = None,
    voice_reference_id: str | None = None,
    device: str = "cpu",
    seed: int = 20260906,
    piper_espeak_data_dir: Path | None = None,
) -> Adapter:
    if name == "fake":
        return FakeAdapter()
    engine = config["engines"][name]
    if name == "piper":
        return PiperAdapter(engine, model_dir / "piper", piper_espeak_data_dir)
    if name == "chatterbox":
        return ChatterboxAdapter(
            engine,
            model_dir / "chatterbox",
            voice_reference,
            voice_reference_id,
            device,
            seed,
        )
    if name == "polly":
        return PollyAdapter(engine, allow_network, region)
    raise ValueError(f"unknown engine: {name}")
