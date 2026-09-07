# Provider-neutral speech-synthesis contract

`src/domain/speech/` defines Guggiana's speech domain independently of AWS
Polly. It is **not wired into the deployed Step Functions workflow.** It exists
so a local engine can be evaluated and implemented against a stable shape, then
adopted only after quality and operational gates pass.

## What the contract owns

| Concern | Contract |
| --- | --- |
| Locales | `SPEECH_LOCALES` (`en-US`, `es-US`, `fr-FR`, `de-DE`, `pt-BR`), `LOCALE_DEFINITIONS` with neutral ISO language/region codes |
| Voice selection | `VOICE_ROLES` — semantic roles (`narrator`), never provider voice IDs |
| Input | `SpeechDocument` = locale + voice role + ordered `SpeechSegment[]` of plain `text` and explicit `pause` (ms). No SSML. |
| Output format | `AudioFormat` — linear PCM (`pcm_s16le`), mono, one sample rate. A single encode happens after assembly, downstream of this contract. |
| Capabilities | `ProviderCapabilities` — provider/model/revision, supported locales and roles, segment and pause bounds, audio format |
| Job lifecycle | `SYNTHESIS_JOB_STATES` = `queued → running → succeeded \| failed` |
| Artifact metadata | `SynthesisArtifactMetadata` — provider, model, **model revision**, voice, locale, duration, sample rate, encoding, **SHA-256 checksum** |
| Failure | `SYNTHESIS_FAILURE_CODES` — bounded set; adapters map engine errors onto it. No invisible fallback. |
| Validation | `validateSpeechDocument(document, capabilities)` — fails closed with a failure code; never repairs input |
| Composition | `composeArticleSpeechDocument({ locale, voice?, title, byline, body })` proves today's title/byline/paragraph shapes are representable without SSML |

### What the contract deliberately excludes

- Polly voice IDs and SSML translation — owned by each provider adapter.
- Step Functions task tokens, S3 keys, and asynchronous callbacks — owned by the
  wiring layer, not the provider API.
- Model installation, IAM changes, and any change to the deployed workflow.

## Adapter boundary

```
SpeechProvider {
  capabilities(): ProviderCapabilities
  createJob(document: SpeechDocument): SynthesisJob   // starts `queued`
  advance(job: SynthesisJob): SynthesisJob            // non-terminal jobs move forward; terminal jobs unchanged
}
```

`createFakeSpeechProvider()` is the deterministic reference implementation used
by contract tests. A real adapter is the only place allowed to know engine
specifics.

### Polly adapter mapping (design only — not implemented here)

| Contract | Polly adapter responsibility |
| --- | --- |
| `SpeechLocale` | select the Polly `LanguageCode` and the voice for the requested `VoiceRole` (today: the single entry per locale in `src/utils/consts/languages.ts`) |
| `SpeechSegment` `text` | wrap in `<speak>…</speak>`, escape SSML characters (`excapeSSMLCharacters`), group into ≤ `maxSegmentChars` chunks (today's `groupParagraphs`, limit 2900) |
| `SpeechSegment` `pause` | emit `<break time="{durationMs}ms"/>` |
| output | Polly returns MP3 today; the adapter must request/represent PCM and defer the single MP3 encode to `merge_files` |
| async job | Polly's `StartSpeechSynthesisTask` + the S3/`polly_listener` callback map to `queued → running → succeeded`; task tokens stay in the state machine, out of `SpeechProvider` |
| metadata | `provider = "polly"`, `model = "polly-neural"`, `modelRevision` pinned by the adapter; checksum computed from the returned artifact |
| errors | Polly throttling/validation errors map to `provider_unavailable` / `unsupported_*` / `segment_too_long` |

## Migration sequence

1. **This change** — land the neutral contract, validation, and fake provider. No
   runtime change. *(current)*
2. **This change** — add an independently runnable, provider-neutral local
   synthesis worker with pinned Piper and Chatterbox adapters, an injected fake
   engine, and an explicit provider on every request (`gaulatti/guggiana#20`).
   It is not wired to Step Functions and does not choose the production default.
3. Add a Polly adapter implementing `SpeechProvider` over the existing
   `pre_polly` / `polly_wait` / `polly_listener` behaviour, with no state-machine
   change.
4. Introduce a provider-selection seam in `lib/workflow/index.ts` that still
   defaults to Polly.
5. Switch the default synthesis path to the local provider once quality and
   operational gates pass (`gaulatti/guggiana#21`); keep Polly IAM/callbacks
   until that has soaked.

Steps 3–5 are separately tracked; each is its own PR. The default-provider
cutover remains gated on human quality, exact-locale, license, and operational
approval.
