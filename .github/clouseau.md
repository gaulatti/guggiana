# Guggiana review contract

Guggiana is an AWS serverless content-to-speech pipeline defined as one CDK
stack (`GuggianaStack`). Step Functions orchestrate translation, speech
synthesis and audio merging for articles; DynamoDB holds content and task state;
S3 holds the audio artifacts. Renditions are lazy: only locales a caller
explicitly requests are translated and synthesized, with per-locale atomic
claims so concurrent callers never duplicate work. A provider-neutral speech
contract (`src/domain/speech/`), an optional local synthesis worker (`worker/`)
and a TTS bake-off (`experiments/tts-bakeoff/`) support replacing Polly; none of
them is wired into the deployed workflow until the cutover work says so.

Preserve the public API and durable status contracts, locale identifiers,
per-locale atomic claims, bounded retries, and the guarantee that provider
failure is visible rather than silently replaced by another provider.
Translation and storage contracts remain valuable. No synthesis input text,
article content, signed URL or artifact location belongs in logs or metrics.
Metric labels stay bounded to controlled enums.

Assess purpose and evidence rather than the number of changed files or lines.
Bug fixes, meaningful tests that raise coverage, dependency repairs and
operational maintenance can serve this existing pipeline without a new product
decision. New capabilities need repository documentation or linked acceptance
criteria that establish their need and boundaries. Production deployment is a
separate, explicitly authorized operation described in
`docs/deployment-runbook.md`; a merge is not a deployment claim, and no change
here deploys, rotates credentials or touches an AWS account.

Ask gaulatti for a second opinion for a product-direction or authority decision:
for example choosing a new TTS engine or voice policy, voice cloning,
introducing a new public API surface, or changing the production provider
default. Ordinary implementation uncertainty and repairable bugs belong to
automated investigation. Changes to review controls, coverage exclusions, or
this purpose contract require explicit owner confirmation.

Every material capability and mechanism must independently score at least 80 for
fit, need and proportionality under Clouseau's shared protocol. A causal technical
finding at or above 70 blocks; unrelated features or good scores cannot average
away a defect. Integrity and review-completeness gates remain independent.

Tests must assert actual production behavior and failure outcomes. Reject
fabricated coverage, disabled tests, swallowed errors, unconditional assertions
and mocks that replace the behavior being claimed. The gate requires exactly 100% line and branch
coverage of the TypeScript application source in `src/` is mandatory for every
contribution. The CDK constructs in `lib/`, the Python worker
(`worker/local_synthesis`) and the TTS bake-off (`experiments/tts-bakeoff`) are
outside the exact-coverage gate for now (the Python trees measure about 70% and
include offline adapters for engines that cannot run in hosted CI); their own
unit tests still run in CI, and a change that touches Python code must add tests
for the code it touches. Narrowing or widening the gate is a review-control
change that requires owner confirmation.

A passing local Clouseau review may be reused only through a signed receipt from
an enrolled trusted workstation and the matching native GitHub author. CI must
independently verify current protected policy, exact head/base and engine content,
expiry, evidence and deterministic scores. All native tests, exact coverage and
branch protections remain mandatory. Clouseau owns the shared scoring,
investigation, repair bounds, evidence ledger, native approval and auto-merge;
this repository owns its purpose and real tests.
