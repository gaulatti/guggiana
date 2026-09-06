from __future__ import annotations

import csv
import importlib.metadata
import json
import statistics
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters import EngineUnavailable, build_adapter
from .audio import inspect_wav
from .catalog import canonical_json_sha256, host_metadata
from .network import deny_network
from .resources import measure_peak_memory


def run_bakeoff(
    fixtures_catalog: dict[str, Any],
    config: dict[str, Any],
    engines: list[str],
    artifacts_dir: Path,
    model_dir: Path,
    *,
    allow_network: bool = False,
    region: str | None = None,
    voice_reference: Path | None = None,
    voice_reference_id: str | None = None,
    device: str = "cpu",
    seed: int = 20260906,
    piper_espeak_data_dir: Path | None = None,
    fixture_ids: set[str] | None = None,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    fixture_sha = canonical_json_sha256(fixtures_catalog)
    config_sha = canonical_json_sha256(config)
    blind_context = canonical_json_sha256(
        {"config": config_sha, "voice_reference_id": voice_reference_id, "seed": seed}
    )
    run_id = canonical_json_sha256(
        {
            "generated_at": generated_at,
            "fixtures": fixture_sha,
            "config": config_sha,
            "engines": engines,
            "device": device,
            "seed": seed,
            "voice_reference_id": voice_reference_id,
            "network_enabled": allow_network,
            "region": region,
            "piper_espeak_data_override": bool(piper_espeak_data_dir),
        }
    )[:16]
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": generated_at,
        "fixtures_sha256": fixture_sha,
        "engine_config_sha256": config_sha,
        "host": host_metadata(),
        "measurement": {
            "clock": "time.perf_counter_ns",
            "cold_load": "first load for each local model in this process; OS filesystem caches were not purged",
            "peak_memory": "10 ms RSS sampling with psutil when installed; process max-RSS fallback otherwise",
            "rtf": "synthesis_seconds divided by WAV duration_seconds",
            "semantic_integrity": "unverified unless ASR or blinded human scores are supplied",
            "mps_determinism": "seeded, but exact reproducibility is not guaranteed by the MPS backend",
        },
        "execution": {
            "device": device,
            "seed": seed,
            "network_enabled": allow_network,
            "aws_region": region if allow_network and "polly" in engines else None,
            "voice_reference_id": voice_reference_id,
            "voice_reference_path_recorded": False,
            "process_cold": False,
            "piper_espeak_data_override": bool(piper_espeak_data_dir),
            "installed_distributions": _installed_distributions(),
        },
        "requested_engines": engines,
        "engine_provenance": {
            name: config["engines"][name] for name in engines if name in config["engines"]
        },
        "records": [],
    }
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    selected_fixtures = [
        fixture
        for fixture in fixtures_catalog["fixtures"]
        if fixture_ids is None or fixture["id"] in fixture_ids
    ]
    if fixture_ids and {fixture["id"] for fixture in selected_fixtures} != fixture_ids:
        raise ValueError("one or more selected fixture IDs do not exist")

    for engine_name in engines:
        try:
            boundary = nullcontext() if engine_name == "polly" else deny_network()
            with boundary:
                adapter = build_adapter(
                    engine_name,
                    config,
                    model_dir,
                    allow_network=allow_network,
                    region=region,
                    voice_reference=voice_reference,
                    voice_reference_id=voice_reference_id,
                    device=device,
                    seed=seed,
                    piper_espeak_data_dir=piper_espeak_data_dir,
                )
        except (EngineUnavailable, ImportError):
            for fixture in selected_fixtures:
                manifest["records"].append(
                    unavailable_record(
                        engine_name,
                        fixture,
                        blind_context,
                        "required dependency or explicitly supplied artifact is unavailable",
                    )
                )
            continue

        for fixture in selected_fixtures:
            blind_id = make_blind_id(engine_name, fixture["id"], blind_context)
            output = artifacts_dir / f"{blind_id}.wav"
            try:
                boundary = nullcontext() if engine_name == "polly" else deny_network()
                with boundary, measure_peak_memory() as memory:
                    measurement = adapter.synthesize(fixture, output)
                audio = inspect_wav(output, fixture.get("target_duration_seconds"))
                manifest["records"].append(
                    {
                        "engine": engine_name,
                        "fixture_id": fixture["id"],
                        "locale": fixture["locale"],
                        "category": fixture["category"],
                        "blind_id": blind_id,
                        "status": "succeeded",
                        "failure": None,
                        "model": measurement.model,
                        "voice": measurement.voice,
                        "backend": measurement.backend,
                        "seed": seed,
                        "cold_load_seconds": _round(measurement.cold_load_seconds),
                        "synthesis_seconds": _round(measurement.synthesis_seconds),
                        "peak_rss_mib": memory.peak_mib,
                        "incremental_peak_rss_mib": memory.incremental_peak_mib,
                        "rtf": _round(measurement.synthesis_seconds / audio["duration_seconds"]),
                        "audio": {**audio, "artifact": f"{blind_id}.wav"},
                        "asr": {"status": "not-run", "wer": None, "transcript_sha256": None},
                    }
                )
            except EngineUnavailable:
                output.unlink(missing_ok=True)
                manifest["records"].append(
                    unavailable_record(
                        engine_name,
                        fixture,
                        blind_context,
                        "required verified local artifact is unavailable",
                    )
                )
            except Exception as error:
                # The artifact is owned by this run and a partial WAV must never look successful.
                output.unlink(missing_ok=True)
                manifest["records"].append(
                    failed_record(engine_name, fixture, blind_context, error)
                )

    manifest["summary"] = summarize(manifest)
    manifest["decision"] = {
        "status": "no-selection",
        "reason": "Objective results alone cannot pass the required blinded human, locale-accent, semantic-integrity, and license gates.",
        "es-US": config["decision_gates"]["es-US"],
        "next_step": "Score successful blinded clips with qualified reviewers, add ASR or transcript review, and obtain license approval before choosing a replacement.",
    }
    return manifest


def make_blind_id(engine: str, fixture_id: str, config_sha: str) -> str:
    return canonical_json_sha256({"engine": engine, "fixture": fixture_id, "config": config_sha})[:12]


def unavailable_record(
    engine: str, fixture: dict[str, Any], config_sha: str, reason: str
) -> dict[str, Any]:
    return {
        "engine": engine,
        "fixture_id": fixture["id"],
        "locale": fixture["locale"],
        "category": fixture["category"],
        "blind_id": make_blind_id(engine, fixture["id"], config_sha),
        "status": "unavailable",
        "failure": {"type": "EngineUnavailable", "message": reason},
        "model": None,
        "voice": None,
        "backend": None,
        "cold_load_seconds": None,
        "synthesis_seconds": None,
        "peak_rss_mib": None,
        "incremental_peak_rss_mib": None,
        "rtf": None,
        "audio": None,
        "asr": {"status": "not-run", "wer": None, "transcript_sha256": None},
    }


def failed_record(
    engine: str, fixture: dict[str, Any], config_sha: str, error: Exception
) -> dict[str, Any]:
    record = unavailable_record(
        engine, fixture, config_sha, "synthesis or audio validation failed"
    )
    record["status"] = "failed"
    record["failure"] = {
        "type": type(error).__name__,
        "reason": "synthesis-or-audio-validation-failed",
        "exception_type": type(error).__name__,
    }
    return record


def summarize(manifest: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for engine in manifest["requested_engines"]:
        records = [record for record in manifest["records"] if record["engine"] == engine]
        successful = [record for record in records if record["status"] == "succeeded"]
        rtfs = [record["rtf"] for record in successful]
        synth = [record["synthesis_seconds"] for record in successful]
        cold_loads = [
            record["cold_load_seconds"]
            for record in successful
            if record["cold_load_seconds"] is not None
        ]
        peak_rss = [record["peak_rss_mib"] for record in successful]
        incremental_peak = [record["incremental_peak_rss_mib"] for record in successful]
        output[engine] = {
            "total": len(records),
            "succeeded": len(successful),
            "failed": sum(record["status"] == "failed" for record in records),
            "unavailable": sum(record["status"] == "unavailable" for record in records),
            "median_rtf": _median(rtfs),
            "median_synthesis_seconds": _median(synth),
            "median_cold_load_seconds": _median(cold_loads),
            "cold_load_observations": cold_loads,
            "median_peak_rss_mib": _median(peak_rss),
            "peak_rss_mib": max(
                peak_rss, default=None
            ),
            "median_incremental_peak_rss_mib": _median(incremental_peak),
            "max_incremental_peak_rss_mib": max(
                incremental_peak, default=None
            ),
            "output_bytes": sum(record["audio"]["size_bytes"] for record in successful),
            "semantic_integrity": "unverified" if successful else "not-applicable",
            "integrity_warnings": sum(
                bool(record["audio"]["truncation"]["outside_target"])
                or record["audio"]["repetition"]["exact_repeated_windows"] > 0
                for record in successful
            ),
        }
    return output


def write_manifest(manifest: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def combine_process_cold_manifests(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    if not manifests:
        raise ValueError("at least one manifest is required")
    first = manifests[0]
    for manifest in manifests[1:]:
        if manifest["fixtures_sha256"] != first["fixtures_sha256"]:
            raise ValueError("cannot combine manifests from different fixture catalogs")
        if manifest["engine_config_sha256"] != first["engine_config_sha256"]:
            raise ValueError("cannot combine manifests from different engine catalogs")
        if manifest["host"] != first["host"]:
            raise ValueError("cannot combine manifests from different hosts")

    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    engines: list[str] = []
    provenance: dict[str, Any] = {}
    for manifest in manifests:
        for engine in manifest["requested_engines"]:
            if engine not in engines:
                engines.append(engine)
        provenance.update(manifest.get("engine_provenance", {}))
        for record in manifest["records"]:
            key = (record["engine"], record["fixture_id"])
            if key in seen:
                raise ValueError(f"duplicate combined record: {key[0]}/{key[1]}")
            seen.add(key)
            records.append(record)

    generated_at = datetime.now(timezone.utc).isoformat()
    combined = {
        **first,
        "run_id": canonical_json_sha256(
            {"source_runs": [manifest["run_id"] for manifest in manifests], "generated_at": generated_at}
        )[:16],
        "generated_at": generated_at,
        "requested_engines": engines,
        "engine_provenance": provenance,
        "records": records,
    }
    combined["measurement"] = {
        **first["measurement"],
        "cold_load": "fresh CPython process and fresh engine/model load for every successful fixture; OS filesystem caches were not purged",
        "peak_memory": "per-process 10 ms RSS sampling with pinned psutil",
    }
    combined["execution"] = {
        **first["execution"],
        "process_cold": True,
        "source_processes": len(manifests),
    }
    combined["summary"] = summarize(combined)
    return combined


def write_blinded_sheet(manifest: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "blind_id",
        "locale",
        "category",
        "intelligibility_1_5",
        "naturalness_1_5",
        "cadence_1_5",
        "pronunciation_1_5",
        "accent_fit_1_5",
        "truncation_or_repetition",
        "reviewer_notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for record in manifest["records"]:
            if record["status"] != "succeeded":
                continue
            writer.writerow(
                {
                    "blind_id": record["blind_id"],
                    "locale": record["locale"],
                    "category": record["category"],
                    "intelligibility_1_5": "",
                    "naturalness_1_5": "",
                    "cadence_1_5": "",
                    "pronunciation_1_5": "",
                    "accent_fit_1_5": "",
                    "truncation_or_repetition": "",
                    "reviewer_notes": "",
                }
            )


def render_report(manifest: dict[str, Any]) -> str:
    lines = [
        "# Multilingual TTS bake-off report",
        "",
        f"Run `{manifest['run_id']}` on `{manifest['host'].get('chip') or manifest['host'].get('model') or manifest['host']['machine']}`.",
        "",
        "| Engine | Success | Failed | Unavailable | Median RTF | Median peak RSS MiB | Median cold load s | Integrity warnings |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for engine, summary in manifest["summary"].items():
        lines.append(
            f"| {engine} | {summary['succeeded']} | {summary['failed']} | {summary['unavailable']} | "
            f"{_display(summary['median_rtf'])} | {_display(summary['median_peak_rss_mib'])} | "
            f"{_display(summary['median_cold_load_seconds'])} | {summary['integrity_warnings']} |"
        )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"**{manifest['decision']['status']}** — {manifest['decision']['reason']}",
            "",
            f"es-US: {manifest['decision']['es-US']}",
            "",
            "## Evidence boundaries",
            "",
            f"- Process-cold: `{str(manifest['execution'].get('process_cold', False)).lower()}`; source processes: `{manifest['execution'].get('source_processes', 1)}`.",
            f"- Installed Piper/psutil: `{manifest['execution']['installed_distributions'].get('piper-tts')}` / `{manifest['execution']['installed_distributions'].get('psutil')}`.",
            f"- Network enabled: `{str(manifest['execution'].get('network_enabled', False)).lower()}`; Polly was not contacted.",
            f"- Piper short eSpeak data-path override: `{str(manifest['execution'].get('piper_espeak_data_override', False)).lower()}` (upstream macOS wheel path-length defect).",
            "- Chatterbox was not run without its pinned multi-gigabyte snapshot and a consented reference; Polly was not run without explicit AWS authorization.",
            "- ASR and human review were not run. Semantic truncation, repetition, pronunciation, and accent fit therefore remain unverified.",
            "",
            "Generated audio and model files are deliberately not committed. The manifest records objective evidence; the blinded sheet is the human-review input.",
            "",
        ]
    )
    return "\n".join(lines)


def _median(values: list[float]) -> float | None:
    return _round(statistics.median(values)) if values else None


def _round(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _display(value: object) -> str:
    return "—" if value is None else str(value)


def _installed_distributions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for distribution in ("piper-tts", "chatterbox-tts", "boto3", "psutil"):
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[distribution] = None
    return versions
