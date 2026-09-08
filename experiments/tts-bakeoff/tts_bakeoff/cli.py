from __future__ import annotations

import argparse
import json
from pathlib import Path

from .catalog import ROOT, load_and_validate_asr_config, load_and_validate_catalog
from .fetch import fetch_asr, fetch_engine
from .review import write_review_bundle
from .runner import (
    combine_process_cold_manifests,
    evidence_readiness,
    render_report,
    run_bakeoff,
    write_blinded_sheet,
    write_manifest,
)


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="Guggiana multilingual TTS bake-off")
    subcommands = cli.add_subparsers(dest="command", required=True)

    subcommands.add_parser("validate", help="validate fixtures and immutable provenance")

    fetch = subcommands.add_parser("fetch", help="explicitly download pinned local models")
    fetch.add_argument("--engine", choices=("piper", "chatterbox", "asr"), required=True)
    fetch.add_argument("--model-dir", type=Path, default=ROOT / "models")
    fetch.add_argument("--allow-network", action="store_true")

    run = subcommands.add_parser("run", help="run fixtures and create evidence")
    run.add_argument(
        "--engine",
        choices=("fake", "piper", "chatterbox", "polly"),
        action="append",
        dest="engines",
    )
    run.add_argument("--model-dir", type=Path, default=ROOT / "models")
    run.add_argument("--artifacts-dir", type=Path, default=ROOT / "artifacts")
    run.add_argument("--output", type=Path, default=ROOT / "results" / "latest.json")
    run.add_argument("--score-sheet", type=Path)
    run.add_argument("--report", type=Path)
    run.add_argument("--allow-network", action="store_true")
    run.add_argument("--region")
    run.add_argument("--voice-reference", type=Path)
    run.add_argument("--voice-reference-id")
    run.add_argument("--device", choices=("cpu", "mps", "cuda"), default="cpu")
    run.add_argument("--seed", type=int, default=20260906)
    run.add_argument("--piper-espeak-data-dir", type=Path)
    run.add_argument("--fixture-id", action="append", dest="fixture_ids")
    run.add_argument("--asr", action="store_true", help="run the pinned local ASR diagnostics")
    run.add_argument("--asr-model-dir", type=Path, default=ROOT / "models" / "asr")
    run.add_argument("--review-bundle", type=Path)
    run.add_argument("--review-key", type=Path)

    score = subcommands.add_parser("score-sheet", help="create a blinded sheet from a manifest")
    score.add_argument("manifest", type=Path)
    score.add_argument("output", type=Path)

    report = subcommands.add_parser("report", help="render a Markdown summary")
    report.add_argument("manifest", type=Path)
    report.add_argument("output", type=Path)

    combine = subcommands.add_parser(
        "combine", help="combine disjoint one-process manifests into process-cold evidence"
    )
    combine.add_argument("manifests", type=Path, nargs="+")
    combine.add_argument("--output", type=Path, required=True)
    combine.add_argument("--score-sheet", type=Path)
    combine.add_argument("--report", type=Path)
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    fixtures, config = load_and_validate_catalog()
    asr_config = load_and_validate_asr_config()
    if args.command == "validate":
        print("valid: 20 fixtures, 5 locales, 3 pinned engines, 1 pinned local ASR adapter")
        return 0
    if args.command == "fetch":
        if not args.allow_network:
            raise SystemExit("fetch refused: pass --allow-network to acknowledge model downloads")
        fetched = (
            fetch_asr(asr_config, args.model_dir / "asr")
            if args.engine == "asr"
            else fetch_engine(args.engine, config, args.model_dir)
        )
        print(f"verified {len(fetched)} {args.engine} artifacts under {args.model_dir}")
        return 0
    if args.command == "run":
        engines = args.engines or ["chatterbox", "piper", "polly"]
        if "polly" in engines and args.allow_network and not args.region:
            raise SystemExit("networked Polly runs require an explicit --region")
        if "chatterbox" in engines and args.voice_reference and not args.voice_reference_id:
            raise SystemExit("Chatterbox voice references require an opaque --voice-reference-id")
        if bool(args.review_bundle) != bool(args.review_key):
            raise SystemExit("--review-bundle and --review-key must be supplied together")
        manifest = run_bakeoff(
            fixtures,
            config,
            engines,
            args.artifacts_dir,
            args.model_dir,
            allow_network=args.allow_network,
            region=args.region,
            voice_reference=args.voice_reference,
            voice_reference_id=args.voice_reference_id,
            device=args.device,
            seed=args.seed,
            piper_espeak_data_dir=args.piper_espeak_data_dir,
            fixture_ids=set(args.fixture_ids) if args.fixture_ids else None,
            asr_config=asr_config if args.asr else None,
            asr_model_dir=args.asr_model_dir if args.asr else None,
        )
        if args.review_bundle and args.review_key:
            manifest["review_packet"] = write_review_bundle(
                manifest,
                fixtures,
                args.artifacts_dir,
                args.review_bundle,
                args.review_key,
            )
            manifest["evidence_readiness"] = evidence_readiness(manifest)
        write_manifest(manifest, args.output)
        if args.score_sheet:
            write_blinded_sheet(manifest, args.score_sheet)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(render_report(manifest), encoding="utf-8")
        print(json.dumps(manifest["summary"], indent=2))
        return 0
    if args.command == "combine":
        manifests = [json.loads(path.read_text(encoding="utf-8")) for path in args.manifests]
        manifest = combine_process_cold_manifests(manifests)
        write_manifest(manifest, args.output)
        if args.score_sheet:
            write_blinded_sheet(manifest, args.score_sheet)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(render_report(manifest), encoding="utf-8")
        print(json.dumps(manifest["summary"], indent=2))
        return 0
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.command == "score-sheet":
        write_blinded_sheet(manifest, args.output)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render_report(manifest), encoding="utf-8")
    return 0
