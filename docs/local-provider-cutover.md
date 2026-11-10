# Local synthesis provider: cancelled cutover and inactive groundwork

**Polly remains Guggiana's production speech provider. The local-provider
cutover is cancelled.** The owner decided on 2026-11-06 to stay on Polly with no
cutover; the tracking issue `gaulatti/guggiana#21` and the deployment issue
`gaulatti/guggiana#30` were closed as not planned. Nothing in this document is a
work item, and no provider, voice-selection, or non-Polly verification step is
required to deploy or operate Guggiana. The deployed Step Functions workflow is
Polly-only and no default has changed.

The code described below was merged before that decision. It is retained as
**inactive groundwork**: it is exported from `src/domain/speech` and covered by
tests, but no Lambda, state machine, or CDK construct imports or configures it.
It may be reused if the owner reopens the question; it should not be extended
or wired in otherwise.

## Retained groundwork (inactive)

`src/domain/speech/worker-request.ts` (`toLocalWorkerRequests`) maps a
provider-neutral `SpeechDocument` to the exact body of the worker's
`POST /v1/jobs`:

- the provider (`piper` or `chatterbox`) is a mandatory argument; there is no
  default and no Polly fallback, and any other name is an error;
- the document is validated first and is never repaired;
- the worker accepts at most 64 segments and 20,000 spoken characters per job,
  so a normal article becomes **several ordered requests**, split only at text
  boundaries (a pause stays with the text it precedes);
- the module is exported but not called by any Lambda, so it is dark.

## Dark provider seam and worker client

Also retained, also uncalled:

- `provider-selection.ts` (`parseSpeechProviderConfig`, `planSpeechProvider`):
  an empty configuration selects **Polly**. `GUGGIANA_SPEECH_ROLLBACK_TO_POLLY=true`
  is the explicit rollback switch: it forces Polly and disables dual-run
  whatever else is set. Dual-run (`GUGGIANA_SPEECH_DUAL_RUN_PROVIDER` plus an
  integer `GUGGIANA_SPEECH_DUAL_RUN_PERCENT`, default 0) only runs a local
  provider beside Polly for a deterministic, operation-keyed sample; the shadow
  audio is never served. Any invalid value is an error, never a fallback. No
  Lambda reads these settings and the CDK stack does not define them.
- `worker-client.ts` (`createLocalWorkerClient`): plain submit / status /
  cancel / artifact calls over the worker's HTTP API with a bearer token, an
  injected `fetch`, a per-call deadline and an artifact size bound.

Where this stays stateless: the client and the selector hold no state and write
nothing. Job and operation state remain in the existing DynamoDB tables and
audio in the existing S3 bucket; the only durable worker state is the worker's
own private SQLite queue, which the caller never reads directly. The owner has decided that no worker is deployed with Guggiana.

- `wav-assembly.ts` (`assembleWavParts`): concatenates the ordered mono PCM16
  WAV artifacts of one article (a normal article is several worker jobs) into a
  single WAV, so the one MP3 encode happens after assembly. It accepts only the
  worker's canonical 44-byte-header files at one sample rate, enforces a caller
  supplied output bound, and fails with a controlled code (`no_parts`,
  `invalid_wav`, `unsupported_format`, `sample_rate_mismatch`,
  `output_too_large`) instead of resampling or repairing. It does not encode MP3
  (no encoder placement was ever decided) and nothing calls it.

Tests assert that the synthesized stack is unchanged (Polly only, no selection
setting) so this code activates nothing.

## Cancelled and not planned

The following were design options for a cutover that will not happen. They are
kept only as history and are not requirements:

- network connectivity between AWS and a loopback-only worker (push, pull, or
  co-located options);
- a provider-selection seam in `lib/workflow/index.ts`, MP3 encoding after WAV
  assembly in `merge_files`, dual-run sampling, and flipping the default;
- per-locale voice quality and license approval for Piper or Chatterbox, worker
  host placement, capacity and cost.

If the owner reopens the decision, start from a new issue and a fresh design;
do not treat the retained code as an approved plan.

Production deployment of this stack has its own gate: see
`docs/deployment-runbook.md`.
