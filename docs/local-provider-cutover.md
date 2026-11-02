# Local synthesis provider cutover: groundwork and open decisions

Tracking issue: `gaulatti/guggiana#21`. **This document and the code it
mentions do not switch anything.** The deployed Step Functions workflow is still
Polly-only and no default has changed.

## Landed groundwork

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

Also landed, also uncalled:

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
own private SQLite queue, which the caller never reads directly. Whether a
worker belongs in Guggiana at all is still the owner's decision (below).

- `wav-assembly.ts` (`assembleWavParts`): concatenates the ordered mono PCM16
  WAV artifacts of one article (a normal article is several worker jobs) into a
  single WAV, so the one MP3 encode happens after assembly. It accepts only the
  worker's canonical 44-byte-header files at one sample rate, enforces a caller
  supplied output bound, and fails with a controlled code (`no_parts`,
  `invalid_wav`, `unsupported_format`, `sample_rate_mismatch`,
  `output_too_large`) instead of resampling or repairing. It does not encode MP3
  (the encoder placement below is still undecided) and nothing calls it.

Tests assert that the synthesized stack is unchanged (Polly only, no selection
setting) so merging this activates nothing.

## Decisions only the owner can make

### 1. How AWS reaches a loopback-only worker with a bearer token

| Option | Shape | Trade-offs |
| --- | --- | --- |
| A. Push | Worker on EC2/Fargate behind an internal load balancer with TLS. Lambdas in the VPC submit, poll and fetch; the state machine uses `Wait` + poll instead of task tokens. | New network surface, TLS and token distribution, VPC Lambdas, always-on host. Requires relaxing the worker's loopback-only listener. |
| B. Pull (recommended) | A small relay on the worker host reads jobs from an SQS queue, calls the loopback worker, uploads the WAV to S3 and signals completion (callback reusing the existing task-token pattern, or an S3 event). | No inbound exposure; the worker stays loopback-only and the token never leaves the host. Needs one new component and queue/S3 IAM, and a heartbeat for host-down detection. |
| C. Co-locate | Run the worker as an ECS task beside a Lambda container image. | Largest change to the deployed shape; models are multi-hundred-MB. |

Recommendation: B. It preserves the worker's security posture and gives the
state machine a durable queue for retries and for the explicit rollback switch.

### 2. Cutover mechanics (not implemented)

1. Introduce a provider-selection seam in `lib/workflow/index.ts` defaulting to
   Polly, behind explicit configuration (needs the owner's approval because it
   is a new configuration surface).
2. Call `assembleWavParts` on the returned WAV chunks and encode MP3 once in
   `merge_files` (the assembly is landed; the encoder in the Lambda image or
   layer is not).
3. Dual-run a bounded fixture sample and record cost, latency and resource use.
4. Flip the default only after all five locales and the long-form fixtures pass
   human quality, license and operational review. Rollback is flipping the
   configuration back; Polly IAM, callbacks and states stay until the new path
   has soaked.

### 3. Still unmeasured or unapproved

- Only Piper has measured resource evidence; Chatterbox has not been acquired.
- Per-locale voice quality and license approval is a human decision.
- Worker host placement, capacity and cost are not defined anywhere.
- Production deployment of this stack has its own gate: see
  `docs/deployment-runbook.md`.
