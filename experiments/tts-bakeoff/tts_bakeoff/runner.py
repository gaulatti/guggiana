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
from .asr import AsrFailed, AsrUnavailable, FasterWhisperAdapter
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
    asr_config: dict[str, Any] | None = None,
    asr_model_dir: Path | None = None,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    fixture_sha = canonical_json_sha256(fixtures_catalog)
    config_sha = canonical_json_sha256(config)
    asr_config_sha = canonical_json_sha256(asr_config) if asr_config is not None else None
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
            "asr_config": asr_config_sha,
        }
    )[:16]
    manifest: dict[str, Any] = {
        "schema_version": 2,
        "run_id": run_id,
        "generated_at": generated_at,
        "fixtures_sha256": fixture_sha,
        "engine_config_sha256": config_sha,
        "asr_config_sha256": asr_config_sha,
        "host": host_metadata(),
        "measurement": {
            "clock": "time.perf_counter_ns",
            "cold_load": "first load for each local model in this process; OS filesystem caches were not purged",
            "peak_memory": "10 ms RSS sampling with psutil when installed; process max-RSS fallback otherwise",
            "rtf": "synthesis_seconds divided by WAV duration_seconds",
            "semantic_integrity": "ASR WER/CER and checks are diagnostic; human review remains independent",
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
        "asr_provenance": asr_config,
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

    asr_adapter: FasterWhisperAdapter | None = None
    asr_unavailable_reason: str | None = None
    if asr_config is not None:
        if asr_model_dir is None:
            raise ValueError("an ASR model directory is required when ASR is enabled")
        try:
            with deny_network():
                asr_adapter = FasterWhisperAdapter(asr_config, asr_model_dir)
        except AsrUnavailable as error:
            asr_unavailable_reason = error.reason

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
        except (EngineUnavailable, ImportError) as error:
            reason = error.reason if isinstance(error, EngineUnavailable) else "missing-dependency"
            for fixture in selected_fixtures:
                manifest["records"].append(
                    unavailable_record(
                        engine_name,
                        fixture,
                        blind_context,
                        reason,
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
                asr = _evaluate_asr(
                    asr_adapter,
                    asr_unavailable_reason,
                    output,
                    fixture,
                    enabled=asr_config is not None,
                )
                objective_status = (
                    "warning"
                    if audio["truncation"]["outside_target"]
                    or audio["repetition"]["exact_repeated_windows"] > 0
                    else "completed"
                )
                record_status = (
                    "warning"
                    if objective_status == "warning"
                    or asr["status"] in {"warning", "failed", "unavailable"}
                    else "completed"
                )
                manifest["records"].append(
                    {
                        "engine": engine_name,
                        "fixture_id": fixture["id"],
                        "locale": fixture["locale"],
                        "category": fixture["category"],
                        "blind_id": blind_id,
                        "status": record_status,
                        "evidence": {
                            "objective_audio": objective_status,
                            "asr_semantic": asr["status"],
                            "human_review": "not-run",
                        },
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
                        "asr": asr,
                    }
                )
            except EngineUnavailable as error:
                output.unlink(missing_ok=True)
                manifest["records"].append(
                    unavailable_record(
                        engine_name,
                        fixture,
                        blind_context,
                        error.reason,
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
        "next_step": "Lock qualified blinded scores and obtain explicit locale and license approval before choosing a replacement.",
    }
    manifest["evidence_readiness"] = evidence_readiness(manifest)
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
        "evidence": {
            "objective_audio": "unavailable",
            "asr_semantic": "not-run",
            "human_review": "not-run",
        },
        "failure": {"type": "EngineUnavailable", "reason": reason},
        "model": None,
        "voice": None,
        "backend": None,
        "cold_load_seconds": None,
        "synthesis_seconds": None,
        "peak_rss_mib": None,
        "incremental_peak_rss_mib": None,
        "rtf": None,
        "audio": None,
        "asr": _empty_asr("not-run", "no-audio-artifact"),
    }


def failed_record(
    engine: str, fixture: dict[str, Any], config_sha: str, error: Exception
) -> dict[str, Any]:
    record = unavailable_record(
        engine, fixture, config_sha, "synthesis or audio validation failed"
    )
    record["status"] = "failed"
    record["evidence"]["objective_audio"] = "failed"
    record["failure"] = {
        "type": type(error).__name__,
        "reason": "synthesis-or-audio-validation-failed",
        "exception_type": type(error).__name__,
    }
    return record


def _empty_asr(status: str, reason: str) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "adapter": None,
        "model": None,
        "model_revision": None,
        "wer": None,
        "cer": None,
        "missing_tail": None,
        "repeated_spans": None,
        "fixture_checks": {},
        "warning_codes": [],
        "transcript_sha256": None,
        "transcript_recorded": False,
    }


def _evaluate_asr(
    adapter: FasterWhisperAdapter | None,
    unavailable_reason: str | None,
    audio_path: Path,
    fixture: dict[str, Any],
    *,
    enabled: bool,
) -> dict[str, Any]:
    if not enabled:
        return _empty_asr("not-run", "not-requested")
    if adapter is None:
        return _empty_asr("unavailable", unavailable_reason or "adapter-unavailable")
    try:
        with deny_network():
            return adapter.evaluate(audio_path, fixture)
    except AsrUnavailable as error:
        return _empty_asr("unavailable", error.reason)
    except AsrFailed:
        return _empty_asr("failed", "local-asr-transcription-failed")
    except Exception:
        return _empty_asr("failed", "local-asr-evaluation-failed")


def evidence_readiness(manifest: dict[str, Any]) -> dict[str, Any]:
    audio_records = [
        record for record in manifest["records"] if record["status"] in {"completed", "warning"}
    ]
    semantic_complete = audio_records and all(
        record["asr"]["status"] in {"completed", "warning"} for record in audio_records
    )
    needs_reference = any(
        (record.get("failure") or {}).get("reason") == "needs-consented-reference"
        for record in manifest["records"]
    )
    review_packet_complete = manifest.get("review_packet", {}).get("status") == "completed"
    if semantic_complete and review_packet_complete:
        status = "ready-for-human-review"
        reason = "Every available audio artifact has objective and local-ASR diagnostic evidence, and the blinded packet is complete."
    elif not audio_records and needs_reference:
        status = "needs-consented-reference"
        reason = "No Chatterbox evidence can be generated without an independently consented local reference."
    else:
        status = "candidate-ineligible"
        reason = "The requested machine-evidence packet is incomplete; inspect per-record evidence states."

    remaining = [
        "Qualified reviewers must lock blinded intelligibility, naturalness, cadence, pronunciation, and accent-fit scores.",
        "A qualified U.S.-Spanish reviewer must decide whether any comparator fits es-US; es-MX and generic Spanish remain non-equivalent.",
        "An authorized legal/product approver must accept the runtime, model, voice/dataset licenses and attribution plan.",
    ]
    if needs_reference:
        remaining.append(
            "Chatterbox evaluation additionally requires a local reference clip with recorded consent and usage rights."
        )
    if any(record["engine"] == "polly" for record in manifest["records"]):
        remaining.append("Any Polly comparison requires separate paid-service authorization.")
    return {"status": status, "reason": reason, "remaining_human_input": remaining}


def summarize(manifest: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for engine in manifest["requested_engines"]:
        records = [record for record in manifest["records"] if record["engine"] == engine]
        successful = [record for record in records if record["status"] in {"completed", "warning"}]
        semantic = [
            record["asr"]
            for record in successful
            if record["asr"]["status"] in {"completed", "warning"}
        ]
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
            "completed": sum(record["status"] == "completed" for record in records),
            "warning": sum(record["status"] == "warning" for record in records),
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
            "semantic_integrity": (
                "diagnostic-completed" if len(semantic) == len(successful) and successful else "incomplete"
            ) if successful else "not-applicable",
            "asr_completed": sum(item["status"] == "completed" for item in semantic),
            "asr_warning": sum(item["status"] == "warning" for item in semantic),
            "asr_unavailable": sum(record["asr"]["status"] == "unavailable" for record in successful),
            "asr_failed": sum(record["asr"]["status"] == "failed" for record in successful),
            "asr_not_run": sum(record["asr"]["status"] == "not-run" for record in successful),
            "median_wer": _median([item["wer"] for item in semantic]),
            "median_cer": _median([item["cer"] for item in semantic]),
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
        if manifest.get("asr_config_sha256") != first.get("asr_config_sha256"):
            raise ValueError("cannot combine manifests from different ASR catalogs")
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
    combined["evidence_readiness"] = evidence_readiness(combined)
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
            if record["status"] not in {"completed", "warning"}:
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
        "| Engine | Completed | Warning | Failed | Unavailable | Median RTF | Median peak RSS MiB | Median cold load s | Median WER | Median CER | Integrity warnings |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for engine, summary in manifest["summary"].items():
        lines.append(
            f"| {engine} | {summary['completed']} | {summary['warning']} | {summary['failed']} | "
            f"{summary['unavailable']} | {_display(summary['median_rtf'])} | "
            f"{_display(summary['median_peak_rss_mib'])} | "
            f"{_display(summary['median_cold_load_seconds'])} | "
            f"{_display(summary['median_wer'])} | {_display(summary['median_cer'])} | "
            f"{summary['integrity_warnings']} |"
        )
    lines.extend(
        [
            "",
            "## Per-fixture semantic diagnostics",
            "",
            "WER/CER are diagnostic edit distances, not automatic pass thresholds. No transcript text is recorded.",
            "",
            "| Engine | Fixture | State | WER | CER | Tail coverage | Extra repeated spans | Fixture checks | Warnings |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for record in manifest["records"]:
        if record["status"] not in {"completed", "warning"}:
            continue
        asr = record["asr"]
        tail = asr.get("missing_tail") or {}
        repeated = asr.get("repeated_spans") or {}
        lines.append(
            f"| {record['engine']} | {record['fixture_id']} | {asr['status']} | "
            f"{_display(asr.get('wer'))} | {_display(asr.get('cer'))} | "
            f"{_display(tail.get('coverage'))} | "
            f"{_display(repeated.get('extra_occurrences'))} | "
            f"{_display_fixture_checks(asr.get('fixture_checks', {}))} | "
            f"{', '.join(asr.get('warning_codes', [])) or '—'} |"
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
            "## Evidence readiness",
            "",
            f"**{manifest['evidence_readiness']['status']}** — {manifest['evidence_readiness']['reason']}",
            "",
            "Remaining human input:",
            *[f"- {item}" for item in manifest['evidence_readiness']['remaining_human_input']],
            "",
            "## Evidence boundaries",
            "",
            f"- Process-cold: `{str(manifest['execution'].get('process_cold', False)).lower()}`; source processes: `{manifest['execution'].get('source_processes', 1)}`.",
            f"- Installed Piper/Faster-Whisper/psutil: `{manifest['execution']['installed_distributions'].get('piper-tts')}` / `{manifest['execution']['installed_distributions'].get('faster-whisper')}` / `{manifest['execution']['installed_distributions'].get('psutil')}`.",
            f"- Network enabled: `{str(manifest['execution'].get('network_enabled', False)).lower()}`; Polly was not contacted.",
            f"- Piper short eSpeak data-path override: `{str(manifest['execution'].get('piper_espeak_data_override', False)).lower()}` (upstream macOS wheel path-length defect).",
            "- Chatterbox was not run without its pinned multi-gigabyte snapshot and a consented reference; Polly was not run without explicit AWS authorization.",
            "- ASR WER/CER, missing-tail, repeated-span, and fixture checks are diagnostic evidence, not human judgement or universal pass thresholds.",
            "- Human intelligibility, naturalness, cadence, pronunciation, and accent-fit scores are not yet locked.",
            "",
            "Generated audio, models, and the private engine key are deliberately not committed. The checksummed public packet is the human-review input.",
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


def _display_fixture_checks(checks: dict[str, Any]) -> str:
    if not checks:
        return "—"
    return ", ".join(
        f"{name} {details['matched']}/{details['expected']}"
        for name, details in checks.items()
    )


def _installed_distributions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for distribution in (
        "piper-tts",
        "chatterbox-tts",
        "boto3",
        "psutil",
        "faster-whisper",
        "ctranslate2",
    ):
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[distribution] = None
    return versions
