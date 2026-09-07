# Multilingual TTS bake-off report

Run `d4bf3c0a95dd1295` on `Apple M1 Max`.

| Engine | Completed | Warning | Failed | Unavailable | Median RTF | Median peak RSS MiB | Median cold load s | Median WER | Median CER | Integrity warnings |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| piper | 3 | 17 | 0 | 0 | 0.033372 | 1608.0465 | 0.582175 | 0.212437 | 0.081752 | 0 |
| chatterbox | 0 | 0 | 0 | 20 | — | — | — | — | — | 0 |
| polly | 0 | 0 | 0 | 20 | — | — | — | — | — | 0 |

## Per-fixture semantic diagnostics

WER/CER are diagnostic edit distances, not automatic pass thresholds. No transcript text is recorded.

| Engine | Fixture | State | WER | CER | Tail coverage | Extra repeated spans | Fixture checks | Warnings |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| piper | en-US-headline-byline | warning | 0.125 | 0.075269 | 0.833333 | 0 | — | tail-coverage-incomplete |
| piper | en-US-numbers-dates-currency | warning | 0.166667 | 0.110092 | 0.916667 | 0 | numbers 4/5, dates 1/1, currency 1/1 | tail-coverage-incomplete, numbers-not-preserved |
| piper | en-US-acronyms-quotations | warning | 0.045455 | 0.018519 | 1.0 | 0 | acronyms 2/4, quotations 1/1 | acronyms-not-preserved |
| piper | en-US-long-form | completed | 0.016129 | 0.003817 | 1.0 | 0 | — | — |
| piper | es-US-headline-byline | warning | 0.176471 | 0.053097 | 0.75 | 0 | — | tail-coverage-incomplete |
| piper | es-US-numbers-dates-currency | warning | 0.347826 | 0.15748 | 0.666667 | 0 | numbers 3/5, dates 1/1, currency 1/1 | tail-coverage-incomplete, numbers-not-preserved |
| piper | es-US-acronyms-quotations | warning | 0.28 | 0.088235 | 0.75 | 0 | acronyms 1/5, quotations 0/1 | tail-coverage-incomplete, acronyms-not-preserved, quotations-not-preserved |
| piper | es-US-long-form | completed | 0.101449 | 0.027778 | 1.0 | 0 | — | — |
| piper | fr-FR-headline-byline | warning | 0.380952 | 0.206612 | 0.75 | 0 | — | tail-coverage-incomplete |
| piper | fr-FR-numbers-dates-currency | warning | 0.136364 | 0.042373 | 0.916667 | 0 | numbers 3/5, dates 1/1, currency 1/1 | tail-coverage-incomplete, numbers-not-preserved |
| piper | fr-FR-acronyms-quotations | warning | 0.357143 | 0.134615 | 0.5 | 0 | acronyms 0/3, quotations 0/1 | tail-coverage-incomplete, acronyms-not-preserved, quotations-not-preserved |
| piper | fr-FR-long-form | warning | 0.171233 | 0.059341 | 0.916667 | 0 | — | tail-coverage-incomplete |
| piper | de-DE-headline-byline | warning | 0.692308 | 0.151515 | 0.5 | 0 | — | tail-coverage-incomplete |
| piper | de-DE-numbers-dates-currency | warning | 0.380952 | 0.112 | 0.75 | 0 | numbers 3/5, dates 1/1, currency 1/1 | tail-coverage-incomplete, numbers-not-preserved |
| piper | de-DE-acronyms-quotations | warning | 0.26087 | 0.068702 | 0.666667 | 0 | acronyms 2/4, quotations 0/1 | tail-coverage-incomplete, acronyms-not-preserved, quotations-not-preserved |
| piper | de-DE-long-form | completed | 0.184874 | 0.036117 | 1.0 | 0 | — | — |
| piper | pt-BR-headline-byline | warning | 0.368421 | 0.107143 | 0.583333 | 0 | — | tail-coverage-incomplete |
| piper | pt-BR-numbers-dates-currency | warning | 0.478261 | 0.198413 | 0.583333 | 0 | numbers 1/5, dates 1/1, currency 1/1 | tail-coverage-incomplete, numbers-not-preserved |
| piper | pt-BR-acronyms-quotations | warning | 0.24 | 0.097744 | 0.833333 | 0 | acronyms 1/4, quotations 0/1 | tail-coverage-incomplete, acronyms-not-preserved, quotations-not-preserved |
| piper | pt-BR-long-form | warning | 0.177305 | 0.062361 | 0.833333 | 0 | — | tail-coverage-incomplete |

## Decision

**no-selection** — Objective results alone cannot pass the required blinded human, locale-accent, semantic-integrity, and license gates.

es-US: No open-source candidate has exact es-US accent evidence. Piper es-MX and Chatterbox es-MX/LatAm are comparators only; selection is forbidden until blinded es-US reviewer scores and license approval are recorded.

## Evidence readiness

**ready-for-human-review** — Every available audio artifact has objective and local-ASR diagnostic evidence, and the blinded packet is complete.

Remaining human input:
- Qualified reviewers must lock blinded intelligibility, naturalness, cadence, pronunciation, and accent-fit scores.
- A qualified U.S.-Spanish reviewer must decide whether any comparator fits es-US; es-MX and generic Spanish remain non-equivalent.
- An authorized legal/product approver must accept the runtime, model, voice/dataset licenses and attribution plan.
- Chatterbox evaluation additionally requires a local reference clip with recorded consent and usage rights.
- Any Polly comparison requires separate paid-service authorization.

## Evidence boundaries

- Process-cold: `false`; source processes: `1`.
- Installed Piper/Faster-Whisper/psutil: `1.8.0` / `1.2.1` / `7.2.2`.
- Network enabled: `false`; Polly was not contacted.
- Piper short eSpeak data-path override: `true` (upstream macOS wheel path-length defect).
- Chatterbox was not run without its pinned multi-gigabyte snapshot and a consented reference; Polly was not run without explicit AWS authorization.
- ASR WER/CER, missing-tail, repeated-span, and fixture checks are diagnostic evidence, not human judgement or universal pass thresholds.
- Human intelligibility, naturalness, cadence, pronunciation, and accent-fit scores are not yet locked.

Generated audio, models, and the private engine key are deliberately not committed. The checksummed public packet is the human-review input.
