from __future__ import annotations

import hashlib
import os
import queue
import threading
import time
import uuid
import wave
from pathlib import Path
from typing import Any

from .adapters import (
    AdapterCancelled,
    EngineAdapter,
    PermanentEngineError,
    RetryableEngineError,
)
from .contract import SynthesisRequest, parse_request
from .events import EventLogger
from .metrics import Metrics
from .store import TERMINAL_STATES, JobStore


class QueueOverloaded(RuntimeError):
    pass


class WorkerConfigurationError(RuntimeError):
    pass


class ArtifactError(RuntimeError):
    pass


def _artifact_metadata(
    path: Path,
    request: SynthesisRequest,
    engine: Any,
    max_artifact_bytes: int,
) -> dict[str, object]:
    if path.stat().st_size > max_artifact_bytes:
        raise ArtifactError("engine output exceeds the artifact size bound")
    try:
        with wave.open(str(path), "rb") as audio:
            channels = audio.getnchannels()
            width = audio.getsampwidth()
            sample_rate = audio.getframerate()
            frames = audio.getnframes()
    except (OSError, EOFError, wave.Error) as error:
        raise ArtifactError("engine output is not a readable WAV") from error
    if channels != 1 or width != 2 or sample_rate <= 0 or frames <= 0:
        raise ArtifactError("engine output is not mono PCM16 audio")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "mediaType": "audio/wav",
        "encoding": "pcm_s16le",
        "channels": channels,
        "sampleRateHz": sample_rate,
        "durationMs": round(frames * 1000 / sample_rate),
        "bytes": path.stat().st_size,
        "checksumSha256": digest,
        "provider": engine.provider,
        "model": engine.model,
        "modelRevision": engine.model_revision,
        "runtimeRevision": engine.runtime_revision,
        "runtimeLicense": engine.runtime_license,
        "voiceRole": request.voice_role,
        "voiceProvenance": engine.voice_provenance,
        "locale": request.locale,
        "manifestSha256": engine.manifest_sha256,
    }


class LocalSynthesisWorker:
    def __init__(
        self,
        state_directory: Path,
        adapters: dict[str, EngineAdapter],
        *,
        concurrency: int = 1,
        queue_capacity: int = 4,
        timeout_seconds: float = 120,
        max_attempts: int = 2,
        retry_backoff_seconds: float = 0.05,
        max_artifact_bytes: int = 268_435_456,
        max_retained_jobs: int = 32,
        event_logger: EventLogger | None = None,
    ):
        if not adapters:
            raise WorkerConfigurationError(
                "at least one adapter must be enabled explicitly"
            )
        if not 1 <= concurrency <= 4 or not 1 <= queue_capacity <= 100:
            raise WorkerConfigurationError(
                "concurrency or queue capacity is outside the safety envelope"
            )
        if not 0 < timeout_seconds <= 900 or not 1 <= max_attempts <= 4:
            raise WorkerConfigurationError(
                "timeout or retry count is outside the safety envelope"
            )
        if (
            not 1_048_576 <= max_artifact_bytes <= 536_870_912
            or not 1 <= max_retained_jobs <= 1_000
        ):
            raise WorkerConfigurationError(
                "artifact size or retention is outside the safety envelope"
            )
        if set(adapters) != {adapter.name for adapter in adapters.values()}:
            raise WorkerConfigurationError("adapter registry names do not match")
        self.adapters = adapters
        self.allowed_providers = set(adapters)
        self.concurrency = concurrency
        self.queue_capacity = queue_capacity
        self.max_inflight = concurrency + queue_capacity
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.max_artifact_bytes = max_artifact_bytes
        self.max_retained_jobs = max_retained_jobs
        self.store = JobStore(state_directory)
        self.metrics = Metrics(self.allowed_providers)
        self.events = event_logger or EventLogger(self.allowed_providers)
        self._queue: queue.Queue[str] = queue.Queue(maxsize=self.max_inflight)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._cancellations: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._started = False

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            recovered = self.store.recover(self.max_attempts)
            if len(recovered) > self.max_inflight:
                raise WorkerConfigurationError(
                    "persisted jobs exceed the configured queue envelope"
                )
            self._stop.clear()
            for index in range(self.concurrency):
                thread = threading.Thread(
                    target=self._run, name=f"local-synthesis-{index}", daemon=True
                )
                thread.start()
                self._threads.append(thread)
            for job_id in recovered:
                self._queue.put_nowait(job_id)
            self._started = True

    def submit_payload(self, payload: Any) -> dict[str, Any]:
        request = parse_request(payload, self.allowed_providers)
        return self.submit(request)

    def submit(self, request: SynthesisRequest) -> dict[str, Any]:
        if request.provider not in self.allowed_providers:
            raise ValueError("provider is not enabled")
        with self._lock:
            if not self._started:
                raise WorkerConfigurationError("worker is not started")
            if self.store.active_count() >= self.max_inflight:
                self.metrics.job(request.provider, "rejected")
                self.events.emit("job_rejected", request.provider, "rejected")
                raise QueueOverloaded("worker queue is full")
            job_id = str(uuid.uuid4())
            self.store.create(job_id, request)
            self._queue.put_nowait(job_id)
        self.metrics.job(request.provider, "accepted")
        self.events.emit("job_accepted", request.provider, "accepted")
        status = self.store.status(job_id)
        assert status is not None
        return status

    def status(self, job_id: str) -> dict[str, Any] | None:
        return self.store.status(job_id)

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        state = self.store.cancel(job_id)
        if state is None:
            return None
        with self._lock:
            cancellation = self._cancellations.get(job_id)
            if cancellation:
                cancellation.set()
        status = self.store.status(job_id)
        self.store.prune_terminal(self.max_retained_jobs)
        return status

    def artifact(self, job_id: str) -> Path | None:
        return self.store.artifact_path(job_id)

    def health(self) -> bool:
        return self.store.writable()

    def ready(self) -> bool:
        return (
            self._started
            and not self._stop.is_set()
            and self.store.writable()
            and bool(self.adapters)
        )

    def prometheus_metrics(self) -> str:
        return self.metrics.render(
            self.store.state_count("queued") + self.store.state_count("retrying"),
            self.store.state_count("running"),
        )

    def wait(self, job_id: str, timeout_seconds: float = 5) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            status = self.store.status(job_id)
            if status is None:
                raise KeyError(job_id)
            if status["state"] in TERMINAL_STATES:
                return status
            time.sleep(0.01)
        raise TimeoutError("job did not become terminal")

    def close(self) -> None:
        self._stop.set()
        for _ in self._threads:
            try:
                self._queue.put_nowait("")
            except queue.Full:
                break
        for thread in self._threads:
            thread.join(timeout=5)
        self._threads.clear()
        self._started = False

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if not job_id:
                self._queue.task_done()
                continue
            try:
                self._process(job_id)
            finally:
                self._queue.task_done()

    def _process(self, job_id: str) -> None:
        claimed = self.store.claim(job_id, self.allowed_providers)
        if claimed is None:
            return
        request, attempt = claimed
        cancellation = threading.Event()
        with self._lock:
            self._cancellations[job_id] = cancellation
        if self.store.cancel_requested(job_id):
            cancellation.set()
        self.events.emit("job_started", request.provider, "running")
        partial = self.store.artifact_directory / f"{job_id}.partial.wav"
        final = self.store.artifact_directory / f"{job_id}.wav"
        started = time.monotonic()
        try:
            result = self.adapters[request.provider].synthesize(
                request, partial, cancellation, self.timeout_seconds, attempt
            )
            if cancellation.is_set() or self.store.cancel_requested(job_id):
                raise AdapterCancelled()
            metadata = _artifact_metadata(
                partial, request, result, self.max_artifact_bytes
            )
            os.replace(partial, final)
            os.chmod(final, 0o600)
            self.store.finish(job_id, metadata, final)
            self.metrics.job(request.provider, "succeeded")
            self.metrics.duration(request.provider, time.monotonic() - started)
            self.events.emit("job_finished", request.provider, "succeeded")
            self.store.prune_terminal(self.max_retained_jobs)
        except AdapterCancelled:
            partial.unlink(missing_ok=True)
            self.store.mark_cancelled(job_id)
            self.metrics.job(request.provider, "cancelled")
            self.events.emit("job_finished", request.provider, "cancelled")
            self.store.prune_terminal(self.max_retained_jobs)
        except RetryableEngineError as error:
            partial.unlink(missing_ok=True)
            retry_class = error.retry_class
            if cancellation.is_set() or self.store.cancel_requested(job_id):
                self.store.mark_cancelled(job_id)
                self.metrics.job(request.provider, "cancelled")
                self.events.emit("job_finished", request.provider, "cancelled")
                self.store.prune_terminal(self.max_retained_jobs)
            elif attempt < self.max_attempts:
                self.store.retry(job_id, retry_class, retry_class)
                self.metrics.retry(request.provider, retry_class)
                self.events.emit(
                    "job_retrying", request.provider, "retrying", retry_class
                )
                if not self._stop.wait(self.retry_backoff_seconds):
                    self._queue.put(job_id)
            else:
                self.store.fail(job_id, retry_class, "exhausted")
                self.metrics.job(request.provider, "failed")
                self.events.emit(
                    "job_finished", request.provider, "failed", "exhausted"
                )
                self.store.prune_terminal(self.max_retained_jobs)
        except (PermanentEngineError, ArtifactError):
            partial.unlink(missing_ok=True)
            self.store.fail(job_id, "synthesis_failed", "permanent")
            self.metrics.job(request.provider, "failed")
            self.events.emit("job_finished", request.provider, "failed", "permanent")
            self.store.prune_terminal(self.max_retained_jobs)
        # Fail closed for an unexpected adapter/runtime defect without logging
        # its potentially content-bearing message.
        except Exception:  # noqa: BLE001
            partial.unlink(missing_ok=True)
            self.store.fail(job_id, "synthesis_failed", "permanent")
            self.metrics.job(request.provider, "failed")
            self.events.emit("job_finished", request.provider, "failed", "permanent")
            self.store.prune_terminal(self.max_retained_jobs)
        finally:
            with self._lock:
                self._cancellations.pop(job_id, None)
