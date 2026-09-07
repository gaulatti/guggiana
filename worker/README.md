# Local synthesis worker

This package is an optional, provider-neutral, asynchronous speech worker. It
is not connected to Guggiana's deployed Step Functions/Polly workflow and it
does not choose a replacement provider. Every request must name an adapter that
the operator explicitly enabled; there is no default and no Polly fallback.

The committed adapters cover the two landed bake-off candidates:

- Piper `1.8.0`, runtime commit `639388b6317fc4731e91d53da42aea68fd4166ff`
- Chatterbox `0.1.7`, runtime commit `5de7a54aa4e5e2baadb0182dde554908b48b85c2`

[`config/model-manifest.json`](config/model-manifest.json) pins dependency wheel
checksums, runtime and model revisions, local artifact checksums, and
per-locale license/provenance evidence. An enabled adapter is constructed only
after its installed distribution version and every required local artifact
match that manifest. A mismatch fails startup and readiness; the worker never
downloads or repairs a model.

## Bounded API

The listener is loopback-only and requires a bearer token loaded from a private
file for job, artifact, and metrics routes. `GET /healthz` and `GET /readyz`
return only a controlled state and disclose no configuration.

| Method and route | Result |
| --- | --- |
| `POST /v1/jobs` | Queue one bounded request; returns `202` or `429` when the fixed envelope is full. |
| `GET /v1/jobs/{id}` | Return lifecycle and sanitized artifact/provenance metadata, never request text or an internal path. |
| `DELETE /v1/jobs/{id}` | Cancel queued work or cooperatively terminate the isolated engine process. |
| `GET /v1/jobs/{id}/artifact` | Stream the successful mono PCM16 WAV. |
| `GET /metrics` | Return authenticated Prometheus text with controlled labels only. |

The request accepts exactly `provider`, `locale`, `voiceRole`, and `segments`.
Provider is mandatory. The contract rejects unknown fields, including Step
Functions task tokens and caller-supplied storage paths.

```json
{
  "provider": "piper",
  "locale": "en-US",
  "voiceRole": "narrator",
  "segments": [
    {"kind": "text", "text": "A fixture sentence."},
    {"kind": "pause", "durationMs": 450},
    {"kind": "text", "text": "A second fixture sentence."}
  ]
}
```

Limits are fixed in the contract: 64 segments, 2,900 characters per text
segment, 20,000 spoken characters per job, pauses from 0–5,000 ms, a 64 KiB
HTTP body, 1–4 workers, 1–100 queued jobs, 1–4 attempts, a 15-minute maximum
timeout, a 512 MiB maximum artifact, and at most 1,000 retained terminal jobs.
The example is intentionally smaller: one worker, four queued jobs, two
attempts, 120 seconds, 256 MiB per artifact, and 32 retained jobs.

## Lifecycle and persistence

SQLite runs in WAL/FULL-synchronous mode under `stateDirectory`. Requests are
durable because queued jobs need their text after restart, so the database is
sensitive and is created mode `0600` under a `0700` directory. WAV files are
also `0600`. The status API never returns stored text.

The lifecycle is `queued → running → succeeded | failed | cancelled`. A
retryable engine error or hard timeout returns a job to `queued` until
`maxAttempts`; permanent errors fail once. On restart, interrupted work is
requeued when attempts remain and fails closed as `worker_restarted` when they
do not. Successful artifacts are accepted only when they decode as non-empty,
mono, 16-bit PCM WAV within `maxArtifactBytes`. Metadata records duration,
sample rate, byte length, SHA-256, provider/model/runtime revisions, license,
voice provenance, locale, and the manifest digest. Old terminal rows and their
artifacts are pruned to `maxRetainedJobs`.

## Explicit model acquisition and startup

Ordinary build and test commands never contact a model host. Acquire models
only through the bake-off's explicit, checksum-verifying path, then mount or
copy the verified tree into the configured `modelRoot` without changing its
relative layout:

```sh
UV_MANAGED_PYTHON=1 uv sync --frozen --project experiments/tts-bakeoff \
  --python 3.11 --extra piper
UV_MANAGED_PYTHON=1 uv run --frozen --project experiments/tts-bakeoff \
  python experiments/tts-bakeoff/run.py fetch --engine piper --allow-network
```

Chatterbox uses its separate `--extra chatterbox` fetch. It additionally needs
a local reference WAV, its SHA-256, and an opaque consent-record ID in
`providerOptions.chatterbox`. The private mapping from that ID to a person or
recording does not belong in this repository, logs, metrics, or API response.

Copy `config/worker.example.json` outside the checkout, update only the local
paths, write a random API token of at least 32 characters to its configured
token file, and set that file to mode `0600`. `enabledProviders` controls which
verified adapters start; the example enables only the objectively measured
Piper lane as a local fixture. That is not a production/default selection, and
requests must still say `"provider": "piper"`.

```sh
PYTHONPATH=worker uv run --frozen --project experiments/tts-bakeoff \
  --extra piper python -m local_synthesis --config /private/path/worker.json
```

The worker does no synthetic warmup: each candidate runs in an isolated child
process, so the first and every later job includes process-cold model load.
This preserves hard timeout/cancellation semantics and matches the bake-off's
process-cold measurement. Readiness proves configuration, package versions,
manifest checksums, licenses, and storage; it does not claim audio quality.

## Resource envelope

The M1 Max bake-off is authoritative for the only measured candidate. Piper
rendered 20/20 fixtures on CPU with median RTF `0.043523`, median cold load
`0.667202 s`, median process RSS `407.1795 MiB`, and maximum process RSS
`546.984 MiB`. The example declares a `768 MiB` Piper limit, allows one engine
process, and needs a host/container supervisor that actually enforces that
limit. The application setting records the reviewed envelope; it cannot impose
a host memory cgroup by itself.

Chatterbox was not acquired or measured in the landed evidence. Its example
`12288 MiB` value is an explicit provisional local safety cap, not a measured
requirement or production recommendation. Keep Chatterbox disabled until its
multi-gigabyte snapshot, consented reference, selected CPU/MPS/CUDA device, and
an enforced host limit have been reviewed. macOS Docker cannot expose MPS; use
a host-managed Python process for MPS evidence. Production host placement,
capacity, cost, and quality/default selection remain outside this worker.

The container package uses an immutable Python 3.11.13 multi-platform image
digest and runs as uid/gid `65532`. It deliberately contains neither candidate
runtime nor model. Build a derived runtime image from checksum-verified local
wheels, mount models read-only, mount `/state` read-write, mount token/reference
files read-only, retain loopback/host-only networking, drop capabilities, use a
read-only root filesystem, and apply the reviewed memory/PID/CPU limits.

```sh
docker build --file worker/Dockerfile --tag guggiana-local-synthesis:0.1.0 worker
```

## Observability and security

Structured events contain only `event`, `provider`, `result`, and
`retryClass`. Metrics use controlled provider/result/retry labels and expose
job outcomes, retries, duration sum/count, queue depth, and running jobs. Text,
article/task/job IDs, paths, voice IDs, URLs, reference IDs, and free-form errors
are never log or metric fields. Default HTTP access logging is disabled because
request paths contain job IDs.

Terminate TLS and operator identity at a same-host reverse proxy if needed;
production networking is not supplied here. Restrict the token to submit,
status, cancellation, artifact, and metrics access for this one worker. Back up
the private state directory atomically, and delete it only through an explicit
retention/recovery procedure. Do not put credentials or models in the image.

To update a candidate, rerun the frozen bake-off acquisition and evidence path,
review the upstream runtime/model/voice licenses, record new immutable commits
and checksums in the manifest, update the frozen dependency lock, repeat fake
lifecycle tests plus a deliberate real-engine fixture run, and review the new
resource envelope before enabling it. Never turn a failed verification into a
network fetch or fallback.

## Verification

```sh
PYTHONPATH=worker python3 -m unittest discover -s worker/tests -t worker -v
PYTHONPATH=worker python3 -m compileall -q worker/local_synthesis worker/tests
uv build --project worker
docker build --file worker/Dockerfile --tag guggiana-local-synthesis:test worker
```

The tests cover the real loopback HTTP protocol with a fake engine, PCM media
inspection, restart recovery and persisted metadata, overload, timeout/retry
exhaustion, cancellation, permanent versus retryable failures, model corruption
and path traversal, token permissions, and log/metric privacy. They do not
download or execute Piper/Chatterbox, deploy, contact AWS, choose a default, or
prove production/device/license approval.
