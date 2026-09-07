# Guggiana deployment runbook

Guggiana is an environment-agnostic CDK stack named `GuggianaStack`. The AWS
CLI profile and Region active when CDK runs therefore select the deployment
target. Never infer that target from a previous operator's machine.

## Preflight

Start from a clean checkout of the reviewed commit. Record the complete commit
SHA and verify that the associated GitHub Actions run is green. Then install the
locked toolchain and run the same offline gates as CI before synthesizing:

```bash
npm ci
uv lock --check --project experiments/tts-bakeoff
npm run test:tts-bakeoff
npm run test:coverage -- --runInBand
npm run build
npx cdk --version
npx cdk synth --quiet GuggianaStack
```

Verify the active identity and Region independently. Stop if either differs
from the authorized target:

```bash
aws sts get-caller-identity
aws configure get region
```

Inspect the complete CloudFormation change set without creating one:

```bash
npx cdk diff --no-change-set --no-color GuggianaStack
```

Capture the SHA, identity, Region, CLI version, synthesized template, and full
diff in the deployment record. Treat a missing stack as a first deployment,
not an empty update. Review every new resource and every IAM addition before
requesting approval.

## Deploy

Only an explicitly authorized operator may deploy the reviewed SHA to the
verified target:

```bash
npx cdk deploy GuggianaStack --require-approval broadening
```

Do not bypass the approval prompt for broadened IAM statements. Do not deploy a
different local tree after its diff was reviewed.

## Verification

After deployment, record the stack status and its physical resources:

```bash
aws cloudformation describe-stacks --stack-name GuggianaStack
aws cloudformation list-stack-resources --stack-name GuggianaStack
```

The stack does not publish API Gateway, a Lambda Function URL, or a network
health endpoint. CloudFormation success alone is therefore infrastructure
evidence, not end-to-end service proof. A production verification must use the
authorized integration that invokes the `get` workflow and must avoid logging
article text, signed URLs, or other content.

For a representative lazy-rendition cycle, capture only bounded evidence:

1. Request one approved locale for a non-sensitive fixture and record start and
   completion latency.
2. Confirm exactly one workflow execution and one stored output for that locale.
3. Repeat the same request and confirm the stored output is reused without a
   second synthesis execution.
4. Record bounded hit/miss, workflow outcome, dependency failure, and cost
   metrics; do not record content IDs, URLs, text, or signed artifacts.
5. Confirm the provider used by the execution. The current landed workflow is
   Polly-only; local-provider proof is not possible until the separately tracked
   worker and production cutover are merged and approved.

## Rollback

Before deployment, record the previous deployed SHA and template when they
exist. To roll back an update, redeploy that exact reviewed revision and verify
the resulting CloudFormation events. For a failed first deployment, preserve
the stack events for diagnosis and let CloudFormation roll back the create.
Never destroy the stack or delete its S3/DynamoDB data as a rollback shortcut.
