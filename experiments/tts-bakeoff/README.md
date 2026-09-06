# Multilingual TTS bake-off

This standalone experiment compares Chatterbox, Piper, and the current Amazon
Polly baseline without importing Guggiana production code. It covers four text
classes in each of `en-US`, `es-US`, `fr-FR`, `de-DE`, and `pt-BR` (20 fixtures
total). Ordinary validation and tests load no model, contact no provider, and
require no AWS credentials.

The experiment produces objective evidence, not an automatic launch decision.
The committed engine catalog records source/model revisions, artifact
checksums, voice provenance, and licenses. Generated models and WAV files are
ignored. The result manifest, Markdown report, and blinded scoring sheet are
the reviewable outputs.

## Reproduce the dry run

Use a clean CPython 3.11 environment. `uv.lock` freezes every optional engine
dependency and its artifacts; `--frozen` refuses lock drift.

```sh
UV_MANAGED_PYTHON=1 uv sync --frozen --project experiments/tts-bakeoff \
  --python 3.11
UV_MANAGED_PYTHON=1 uv run --frozen --project experiments/tts-bakeoff \
  python experiments/tts-bakeoff/run.py validate
npm run test:tts-bakeoff
```

The fake engine exercises every runner path without network access:

```sh
UV_MANAGED_PYTHON=1 uv run --frozen --project experiments/tts-bakeoff \
  python experiments/tts-bakeoff/run.py run \
  --engine fake \
  --output experiments/tts-bakeoff/results/fake.json \
  --score-sheet experiments/tts-bakeoff/results/fake.blinded.csv \
  --report experiments/tts-bakeoff/results/fake.md
```

## Run Piper locally

Model acquisition is a separate, deliberate network step. It downloads the
five voices from the pinned Piper voices revision and verifies the model
SHA-256 plus the upstream config/model-card MD5 values before use.

```sh
UV_MANAGED_PYTHON=1 uv sync --frozen --project experiments/tts-bakeoff \
  --python 3.11 --extra piper --extra metrics
UV_MANAGED_PYTHON=1 uv run --frozen --project experiments/tts-bakeoff \
  python experiments/tts-bakeoff/run.py fetch \
  --engine piper --allow-network
UV_MANAGED_PYTHON=1 uv run --frozen --project experiments/tts-bakeoff \
  python experiments/tts-bakeoff/run.py run \
  --engine piper --engine chatterbox --engine polly \
  --piper-espeak-data-dir /short/path/espeak-ng-data \
  --output experiments/tts-bakeoff/results/local.json \
  --score-sheet experiments/tts-bakeoff/results/local.blinded.csv \
  --report experiments/tts-bakeoff/results/local.md
```

`piper-tts` 1.8.0's macOS arm64 wheel still exhibits the upstream
[eSpeak data-path truncation bug](https://github.com/OHF-Voice/piper1-gpl/issues/272)
when its installed path exceeds the native 159-byte limit. Until the reviewed
[upstream fix](https://github.com/OHF-Voice/piper1-gpl/pull/281) ships, copy the
wheel's bundled `piper/espeak-ng-data` directory to a path under that limit and
pass `--piper-espeak-data-dir`. The manifest records that an override was used
without publishing the local path.

The run command denies socket access to local engines. With no Chatterbox
snapshot/reference and no explicit Polly network permission, those engines
emit a structured `unavailable` record for every applicable fixture instead of
silently disappearing.

## Run Chatterbox or Polly deliberately

Chatterbox acquisition is multi-gigabyte and explicit:

```sh
UV_MANAGED_PYTHON=1 uv sync --frozen --project experiments/tts-bakeoff \
  --python 3.11 --extra chatterbox --extra metrics
UV_MANAGED_PYTHON=1 uv run --frozen --project experiments/tts-bakeoff \
  python experiments/tts-bakeoff/run.py fetch \
  --engine chatterbox --allow-network
```

Supply a locally held reference clip only with documented recording consent
and usage rights. The opaque ID belongs in evidence; its private mapping to a
person/clip does not.

```sh
UV_MANAGED_PYTHON=1 uv run --frozen --project experiments/tts-bakeoff \
  python experiments/tts-bakeoff/run.py run \
  --engine chatterbox --device mps \
  --voice-reference /path/to/consented-reference.wav \
  --voice-reference-id consent-record-042
```

The runner uses a pinned local snapshot and `from_local`, because upstream
`from_pretrained` resolves a floating `main`. Chatterbox uses the PerTh
watermarker. A seed is recorded, but MPS results are not guaranteed to be
bit-for-bit deterministic.

Polly makes paid AWS calls only when both network and region are explicit:

```sh
UV_MANAGED_PYTHON=1 uv sync --frozen --project experiments/tts-bakeoff \
  --python 3.11 --extra polly --extra metrics
UV_MANAGED_PYTHON=1 uv run --frozen --project experiments/tts-bakeoff \
  python experiments/tts-bakeoff/run.py run \
  --engine polly --allow-network --region us-east-1
```

## Measurement and review contract

- Cold load is the first load of each local model in the process. Filesystem
  caches are not purged, so this is process-cold, not machine-cold.
- Synthesis time spans engine inference/network response through completed WAV
  materialization, measured with a monotonic nanosecond clock.
- RTF is synthesis time divided by decoded output duration.
- Peak RSS is sampled every 10 ms with the pinned `psutil` metrics extra. A
  lifetime max-RSS fallback exists for dry tests and is identified in the
  manifest; benchmark evidence should install `metrics`.
- WAV decoding validates the declared PCM length, non-silent energy, duration,
  format, size, and checksum. Duration-target and exact repeated-window checks
  are alerts, not claims of semantic correctness.
- Semantic truncation/repetition remains `unverified` without ASR transcript
  comparison or human review. Optional ASR WER is explicitly `not-run`/null
  when unavailable.
- Give reviewers only the randomized-name WAV directory and blinded CSV. Keep
  the engine-keyed manifest private until all scores are locked.

Reviewers score intelligibility, naturalness, cadence, pronunciation, and
accent fit from 1–5. A replacement cannot be selected until every required
locale has applicable output and blinded review, semantic-integrity warnings
are resolved, and the engine plus every selected voice/license is approved.

## Current locale and license boundary

The maintained [Piper runtime](https://github.com/OHF-Voice/piper1-gpl) is
GPL-3.0-or-later and voice licenses are individual. The pinned comparison set
uses public-domain/Apache-2.0/CC-BY-4.0/CC0 datasets as recorded in
`config/engines.json`. The [Chatterbox runtime](https://github.com/resemble-ai/chatterbox)
and pinned model repositories are MIT, but a reference voice has separate
consent/rights obligations. [Polly voices](https://docs.aws.amazon.com/polly/latest/dg/available-voices.html)
remain governed by AWS service terms.

Neither open-source candidate provides exact `es-US` evidence: Piper supplies
an `es-MX` voice, while Chatterbox supplies a general `es` model and an
`es-MX`/Latin-American pack. Those are comparators only. No open-source
selection is defensible until qualified U.S.-Spanish reviewers approve the
accent and the license gate passes.

## Committed M1 Max evidence

[`results/m1-max-piper-2026-09-06.json`](results/m1-max-piper-2026-09-06.json)
contains 20 fresh-process Piper runs on an Apple M1 Max with the pinned metrics
extra. The accompanying [report](results/m1-max-piper-2026-09-06.md) summarizes
the objective results, and the [blinded sheet](results/m1-max-piper-2026-09-06.blinded.csv)
is ready for human scoring. The WAV files remain untracked. Chatterbox and Polly
are represented as structured unavailable results, so the committed decision is
explicitly `no-selection`.
