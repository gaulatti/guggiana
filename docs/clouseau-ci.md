# Clouseau CI

Pull requests are verified and reviewed by the public
[Clouseau](https://github.com/gaulatti/clouseau) engine through
`.github/workflows/ci.yml`. Review contract: `.github/clouseau.md`;
configuration: `.github/clouseau.json`; local agent recipe:
`.clouseau-local.json`.

## What the `verify` job runs

- frozen TTS bake-off lock check and offline tests, local synthesis worker
  offline tests, `compileall`, wheel build and the worker base-image build
  (unchanged from the former coverage workflow);
- Clouseau's own approval-policy tests and this repository's workflow routing
  tests (`.github/tests`);
- `tsc --noEmit` and `npm run test:coverage`;
- the exact-100% gate: every line and branch of the non-test TypeScript in
  `src/` (Istanbul report `coverage/coverage-final.json`).

The former Codecov upload was removed: the exact gate replaces a percentage
service and needed an OIDC upload that failed the build when unavailable.

## Coverage scope (deliberate, documented exclusion)

Only the TypeScript `src/` tree is gated. `lib/` (CDK constructs, covered by
Jest assertions but not gated), `worker/local_synthesis` (about 70% measured)
and `experiments/tts-bakeoff/tts_bakeoff` (offline adapters for engines that
cannot run on hosted runners) are excluded for now. Their unit tests still run
in CI. Any change to Python code must add tests for the code it touches.
Changing this scope needs owner confirmation.

## Local review

`.clouseau-local.json` runs `tsc`, the coverage suite and the worker offline
suite, then checks `src/` for exact coverage. See `AGENTS.md` for the required
pre-PR review.

## Operator setup

Repository secrets used by the workflow: `DEEPSEEK_API_KEY` and
`TYPESAFE_API_KEY` (CI AI review) and `DEPLOYMENT_TOKEN` (the bounded repair
author). The workflow never deploys. Protected central Clouseau `main` is
resolved at the start of each run and frozen for it; there is no static engine
pin to update.
