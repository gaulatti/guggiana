# Locale and license approval worksheet

This worksheet records primary-source evidence for the machine-evidence lane. It
does not select an engine, declare a license acceptable, or treat a nearby
locale as exact evidence. Source revisions were rechecked on 2026-09-06.

## Runtime and model evidence

| Candidate | Pinned primary source | Recorded license evidence | Approval still required |
| --- | --- | --- | --- |
| Faster-Whisper ASR | [`faster-whisper` v1.2.1 source commit](https://github.com/SYSTRAN/faster-whisper/tree/65882eee9f5cdbeeb2d877f1131d48cf241b327d) and its [MIT license](https://github.com/SYSTRAN/faster-whisper/blob/65882eee9f5cdbeeb2d877f1131d48cf241b327d/LICENSE) | MIT runtime; the pinned [`Systran/faster-whisper-tiny`](https://huggingface.co/Systran/faster-whisper-tiny/tree/d90ca5fe260221311c53c58e660288d3deb8d356) model card also declares MIT. This model is diagnostic ASR, not a TTS candidate or accent judge. | Confirm use of ASR output as diagnostic evidence only. No universal WER/CER threshold is proposed. |
| Piper runtime | [`piper1-gpl` source commit](https://github.com/OHF-Voice/piper1-gpl/tree/639388b6317fc4731e91d53da42aea68fd4166ff), its [`GPL-3.0-or-later` package declaration](https://github.com/OHF-Voice/piper1-gpl/blob/639388b6317fc4731e91d53da42aea68fd4166ff/setup.py#L48), and [GPLv3 license text](https://github.com/OHF-Voice/piper1-gpl/blob/639388b6317fc4731e91d53da42aea68fd4166ff/COPYING) | GPL-3.0-or-later runtime. Voice/dataset obligations remain individual, as shown below. | Legal/product must approve the intended distribution model, notices, source obligations, and every selected voice/dataset. |
| Chatterbox runtime/models | [`chatterbox` source commit](https://github.com/resemble-ai/chatterbox/tree/5de7a54aa4e5e2baadb0182dde554908b48b85c2) and its [MIT license](https://github.com/resemble-ai/chatterbox/blob/5de7a54aa4e5e2baadb0182dde554908b48b85c2/LICENSE); pinned [multilingual model](https://huggingface.co/ResembleAI/chatterbox/tree/5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18) | MIT is recorded for runtime and pinned model artifacts. Upstream usage requires a reference clip for voice cloning and warns that the reference accent can transfer across languages. | An authorized reference clip needs documented recording consent and usage rights. Legal/product must approve the model and reference-voice plan before evaluation or selection. |
| Amazon Polly baseline | AWS's current [available voices](https://docs.aws.amazon.com/polly/latest/dg/available-voices.html) and [service terms](https://aws.amazon.com/service-terms/) | AWS-managed service; no local model license is represented. | Paid-service authorization, AWS terms review, cost acceptance, and any production decision remain outside this issue. Polly was not contacted. |

## Piper voice evidence

The voice inventory is pinned to
[`rhasspy/piper-voices@375a0fe`](https://huggingface.co/rhasspy/piper-voices/tree/375a0fe641dea077c2a47b4e9a056d6da521eed3).
The harness verifies each model, configuration, and model-card artifact before
use.

| Requested locale | Evaluated voice | Primary model card | Dataset license recorded by upstream | Locale conclusion | Approver decision |
| --- | --- | --- | --- | --- | --- |
| `en-US` | `en_US-ljspeech-high` | [Pinned card](https://huggingface.co/rhasspy/piper-voices/blob/375a0fe641dea077c2a47b4e9a056d6da521eed3/en/en_US/ljspeech/high/MODEL_CARD) | Public domain | Exact locale tag; human quality review still required. | Approve/reject voice, dataset provenance, runtime obligations, and notices. |
| `es-US` | `es_MX-claude-high` | [Pinned card](https://huggingface.co/rhasspy/piper-voices/blob/375a0fe641dea077c2a47b4e9a056d6da521eed3/es/es_MX/claude/high/MODEL_CARD) | Apache-2.0 | **Comparator only.** The pinned Spanish tree contains `es-AR`, `es-ES`, and `es-MX`, but no `es-US`; absence is visible in the [pinned Spanish catalog](https://huggingface.co/rhasspy/piper-voices/tree/375a0fe641dea077c2a47b4e9a056d6da521eed3/es). | A qualified U.S.-Spanish reviewer must decide accent fit; legal/product must not relabel this voice `es-US`. |
| `fr-FR` | `fr_FR-siwis-medium` | [Pinned card](https://huggingface.co/rhasspy/piper-voices/blob/375a0fe641dea077c2a47b4e9a056d6da521eed3/fr/fr_FR/siwis/medium/MODEL_CARD) | CC-BY-4.0 | Exact locale tag; attribution is required. | Approve/reject attribution text and distribution plan. |
| `de-DE` | `de_DE-thorsten-high` | [Pinned card](https://huggingface.co/rhasspy/piper-voices/blob/375a0fe641dea077c2a47b4e9a056d6da521eed3/de/de_DE/thorsten/high/MODEL_CARD) | CC0 | Exact locale tag; human quality review still required. | Approve/reject voice and runtime obligations. |
| `pt-BR` | `pt_BR-faber-medium` | [Pinned card](https://huggingface.co/rhasspy/piper-voices/blob/375a0fe641dea077c2a47b4e9a056d6da521eed3/pt/pt_BR/faber/medium/MODEL_CARD) | CC0 | Exact locale tag; human quality review still required. | Approve/reject voice and runtime obligations. |

## Exact `es-US` catalog audit

- The pinned Piper Spanish catalog exposes Argentina, Spain, and Mexico. It has
  no `es-US` directory or model card. `es-MX` is therefore retained only as a
  blinded comparator.
- The pinned Chatterbox source lists general Spanish (`es`) and its maintained
  [single-language catalog](https://github.com/resemble-ai/chatterbox/blob/5de7a54aa4e5e2baadb0182dde554908b48b85c2/README.md#single-language-pack)
  lists Latam Spanish (`es-mx-latam`) and Spain Spanish (`es-es`), not `es-US`.
- Polly documents an `es-US` voice, but it is a paid managed-service baseline,
  not distributable open-source evidence and was not called by this work.

No maintained, distributable candidate in the audited pinned Piper and
Chatterbox catalogs provides exact `es-US` evidence. This is a source-backed
absence, not a claim that no such model can ever exist.

## Human decision record

Before unblocking an engine or per-locale matrix, record all of the following:

- qualified blinded scores and reviewer qualification for each required locale;
- explicit `es-US` accent-fit approval or rejection without locale relabeling;
- legal approval for runtime, model, voice/dataset, attribution, and reference
  rights as applicable;
- product approval of one engine or an explicit per-locale matrix;
- separate authorization for paid evaluation, production, deployment, or a
  consented reference clip if any of those are later requested.

Until those decisions exist, the only valid overall decision remains
`no-selection`.
