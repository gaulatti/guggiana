from __future__ import annotations

import csv
import json
import secrets
import struct
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .catalog import file_digest


def write_review_bundle(
    manifest: dict[str, Any],
    fixtures_catalog: dict[str, Any],
    artifacts_dir: Path,
    output_dir: Path,
    private_key_path: Path,
) -> dict[str, Any]:
    """Create a public blinded packet and a separately held private engine key."""
    output_resolved = output_dir.resolve()
    key_resolved = private_key_path.resolve()
    if key_resolved == output_resolved or output_resolved in key_resolved.parents:
        raise ValueError("the private engine key must be outside the reviewer bundle")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("reviewer bundle destination must be empty")

    fixtures = {fixture["id"]: fixture for fixture in fixtures_catalog["fixtures"]}
    records = [
        record for record in manifest["records"] if record["status"] in {"completed", "warning"}
    ]
    if not records:
        raise ValueError("reviewer bundle requires at least one completed audio record")

    output_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = output_dir / "audio"
    audio_dir.mkdir()
    private_key_path.parent.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc).isoformat()
    identifiers: set[str] = set()
    clips: list[dict[str, Any]] = []
    key_records: list[dict[str, Any]] = []
    for record in records:
        while True:
            identifier = f"clip-{secrets.token_hex(8)}"
            if identifier not in identifiers:
                identifiers.add(identifier)
                break
        source = artifacts_dir / record["audio"]["artifact"]
        if not source.is_file() or file_digest(source) != record["audio"]["sha256"]:
            raise ValueError("reviewer bundle source audio is missing or failed checksum verification")
        filename = f"{identifier}.wav"
        destination = audio_dir / filename
        _prepare_blinded_audio(source, destination)
        review_audio_sha256 = file_digest(destination)
        if review_audio_sha256 == record["audio"]["sha256"]:
            raise ValueError("reviewer audio must not retain a source-artifact checksum")
        fixture = fixtures[record["fixture_id"]]
        clips.append(
            {
                "audio_id": identifier,
                "filename": f"audio/{filename}",
                "sha256": review_audio_sha256,
                "locale": record["locale"],
                "fixture_id": record["fixture_id"],
                "category": record["category"],
                "prompt": fixture["text"],
            }
        )
        key_records.append(
            {
                "audio_id": identifier,
                "engine": record["engine"],
                "fixture_id": record["fixture_id"],
                "model": record["model"],
                "voice": record["voice"],
                "source_audio_sha256": record["audio"]["sha256"],
                "review_audio_sha256": review_audio_sha256,
            }
        )

    secrets.SystemRandom().shuffle(clips)
    public_manifest = {
        "schema_version": 1,
        "created_at": created_at,
        "blinded": True,
        "engine_identity_present": False,
        "source_identifiers_present": False,
        "media_preparation": {
            "method": "pcm-s16le-fixed-gain-v1",
            "gain_numerator": 32703,
            "gain_denominator": 32768,
            "scope": "applied identically to every candidate before review",
        },
        "clip_count": len(clips),
        "required_locales": fixtures_catalog["locales"],
        "score_dimensions": [
            "intelligibility",
            "naturalness",
            "cadence",
            "pronunciation",
            "accent_fit",
        ],
        "clips": clips,
    }
    manifest_path = output_dir / "reviewer-manifest.json"
    manifest_path.write_text(
        json.dumps(public_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    instructions_path = output_dir / "INSTRUCTIONS.md"
    instructions_path.write_text(_review_instructions(), encoding="utf-8")
    scores_path = output_dir / "scores.csv"
    _write_scores(clips, scores_path)

    checksum_paths = [manifest_path, instructions_path, scores_path, *sorted(audio_dir.iterdir())]
    checksums_path = output_dir / "SHA256SUMS"
    checksums_path.write_text(
        "".join(
            f"{file_digest(path)}  {path.relative_to(output_dir).as_posix()}\n"
            for path in checksum_paths
        ),
        encoding="utf-8",
    )
    private_key = {
        "schema_version": 1,
        "source_run_id": manifest["run_id"],
        "created_at": created_at,
        "private_engine_key": True,
        "records": sorted(key_records, key=lambda item: item["audio_id"]),
    }
    private_key_path.write_text(
        json.dumps(private_key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "status": "completed",
        "clip_count": len(clips),
        "randomized_ids": True,
        "engine_identity_present": False,
        "source_identifiers_present": False,
        "source_checksums_reused": False,
        "public_packet_checksums_recorded_in_result": False,
        "media_preparation": "pcm-s16le-fixed-gain-v1",
        "private_key_written_separately": True,
        "private_key_path_recorded": False,
        "audio_committed": False,
    }


def _prepare_blinded_audio(source: Path, destination: Path) -> None:
    """Apply an engine-neutral, deterministic gain before reviewer delivery.

    Rewriting every candidate with the same fixed-point PCM transform preserves
    rate, channels, duration, and audibility while preventing the public packet
    checksum from joining a clip to the engine-identified source manifest.
    """
    try:
        with wave.open(str(source), "rb") as input_audio:
            channels = input_audio.getnchannels()
            sample_width = input_audio.getsampwidth()
            sample_rate = input_audio.getframerate()
            frame_count = input_audio.getnframes()
            compression = input_audio.getcomptype()
            frames = input_audio.readframes(frame_count)
    except (OSError, EOFError, wave.Error) as error:
        raise ValueError(f"reviewer audio is not a readable PCM WAV: {error}") from error
    if compression != "NONE" or sample_width != 2 or not frames:
        raise ValueError("reviewer audio must be non-empty 16-bit PCM WAV")

    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    transformed = [
        (sample * 32703) // 32768
        if sample >= 0
        else -((-sample * 32703) // 32768)
        for sample in samples
    ]
    with wave.open(str(destination), "wb") as output_audio:
        output_audio.setnchannels(channels)
        output_audio.setsampwidth(sample_width)
        output_audio.setframerate(sample_rate)
        output_audio.writeframes(struct.pack(f"<{len(transformed)}h", *transformed))


def _write_scores(clips: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "audio_id",
        "locale",
        "fixture_id",
        "intelligibility_1_5",
        "naturalness_1_5",
        "cadence_1_5",
        "pronunciation_1_5",
        "accent_fit_1_5",
        "truncation_or_repetition",
        "reviewer_notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for clip in clips:
            writer.writerow(
                {
                    "audio_id": clip["audio_id"],
                    "locale": clip["locale"],
                    "fixture_id": clip["fixture_id"],
                    "intelligibility_1_5": "",
                    "naturalness_1_5": "",
                    "cadence_1_5": "",
                    "pronunciation_1_5": "",
                    "accent_fit_1_5": "",
                    "truncation_or_repetition": "",
                    "reviewer_notes": "",
                }
            )


def _review_instructions() -> str:
    return """# Blinded TTS review instructions

Review clips in the randomized order in `scores.csv`. Do not inspect repository
results or the separately held engine key until every score is locked.

Use whole-number scores from 1 (unacceptable) to 5 (excellent):

- **Intelligibility:** every intended word is understandable.
- **Naturalness:** the clip sounds like fluent, human speech rather than an artifact.
- **Cadence:** pacing, pauses, and emphasis fit the prompt.
- **Pronunciation:** names, numbers, dates, currency, acronyms, and quotations are spoken correctly.
- **Accent fit:** the voice fits the stated locale. `es-US` requires a qualified U.S.-Spanish reviewer; do not treat `es-MX` or generic Spanish as exact locale evidence.

Mark `truncation_or_repetition` yes/no and explain any suspected missing tail,
repeated phrase, hallucination, corruption, or scoring uncertainty in
`reviewer_notes`. Scores are human evidence, not legal approval or an engine
selection. Record reviewer qualification and conflict-of-interest attestations
outside this public packet before unblinding.
"""
