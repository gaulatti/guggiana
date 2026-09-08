from __future__ import annotations

import io
import json
import logging
import os
import sqlite3
import tempfile
import time
import unittest
import wave
from contextlib import closing
from pathlib import Path

from local_synthesis import (
    FakeAdapter,
    LocalSynthesisWorker,
    QueueOverloaded,
    parse_request,
)
from local_synthesis.events import EventLogger

from .test_contract import request


class WorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.state = Path(self.temporary.name) / "state"
        self.workers: list[LocalSynthesisWorker] = []

    def tearDown(self) -> None:
        for worker in self.workers:
            worker.close()
        self.temporary.cleanup()

    def worker(
        self, adapter: FakeAdapter | None = None, **options: object
    ) -> LocalSynthesisWorker:
        worker = LocalSynthesisWorker(
            self.state, {"fake": adapter or FakeAdapter()}, **options
        )
        self.workers.append(worker)
        return worker

    def wait_for_state(
        self, worker: LocalSynthesisWorker, job_id: str, state: str
    ) -> None:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            status = worker.status(job_id)
            if status and status["state"] == state:
                return
            time.sleep(0.005)
        self.fail(f"job did not reach {state}")

    def test_fixture_job_completes_with_pcm_metadata_and_durable_artifact(self) -> None:
        worker = self.worker()
        worker.start()
        submitted = worker.submit_payload(request())
        done = worker.wait(submitted["id"])
        self.assertEqual(done["state"], "succeeded")
        self.assertEqual(done["artifact"]["encoding"], "pcm_s16le")
        self.assertEqual(done["artifact"]["sampleRateHz"], 16_000)
        self.assertRegex(done["artifact"]["checksumSha256"], r"^[a-f0-9]{64}$")
        self.assertEqual(done["artifact"]["provider"], "fake")
        artifact = worker.artifact(done["id"])
        self.assertIsNotNone(artifact)
        assert artifact is not None
        self.assertEqual(os.stat(artifact).st_mode & 0o777, 0o600)
        with wave.open(str(artifact), "rb") as audio:
            self.assertEqual((audio.getnchannels(), audio.getsampwidth()), (1, 2))

        restarted = self.worker()
        self.assertEqual(restarted.status(done["id"])["artifact"], done["artifact"])

    def test_restart_recovers_interrupted_job(self) -> None:
        first = self.worker()
        job_id = "11111111-1111-4111-8111-111111111111"
        first.store.create(job_id, parse_request(request(), {"fake"}))
        with closing(sqlite3.connect(first.store.database)) as connection, connection:
            connection.execute(
                "UPDATE jobs SET state='running', attempts=1 WHERE id=?", (job_id,)
            )
        restarted = self.worker()
        restarted.start()
        done = restarted.wait(job_id)
        self.assertEqual(done["state"], "succeeded")
        self.assertEqual(done["attempts"], 2)

    def test_overload_is_rejected_without_unbounded_queueing(self) -> None:
        worker = self.worker(
            FakeAdapter(delay_seconds=0.2), concurrency=1, queue_capacity=1
        )
        worker.start()
        first = worker.submit_payload(request())
        self.wait_for_state(worker, first["id"], "running")
        worker.submit_payload(request())
        with self.assertRaises(QueueOverloaded):
            worker.submit_payload(request())

    def test_timeout_retries_then_fails_with_bounded_class(self) -> None:
        worker = self.worker(
            FakeAdapter(delay_seconds=0.08),
            timeout_seconds=0.02,
            max_attempts=2,
            retry_backoff_seconds=0,
        )
        worker.start()
        done = worker.wait(worker.submit_payload(request())["id"])
        self.assertEqual(done["state"], "failed")
        self.assertEqual(done["attempts"], 2)
        self.assertEqual(
            done["failure"], {"code": "timeout", "retryClass": "exhausted"}
        )

    def test_running_job_can_be_cancelled(self) -> None:
        worker = self.worker(FakeAdapter(delay_seconds=0.2))
        worker.start()
        submitted = worker.submit_payload(request())
        self.wait_for_state(worker, submitted["id"], "running")
        worker.cancel(submitted["id"])
        done = worker.wait(submitted["id"])
        self.assertEqual(done["state"], "cancelled")
        self.assertIsNone(worker.artifact(submitted["id"]))

    def test_queued_job_can_be_cancelled_before_engine_execution(self) -> None:
        worker = self.worker(
            FakeAdapter(delay_seconds=0.2), concurrency=1, queue_capacity=1
        )
        worker.start()
        running = worker.submit_payload(request())
        self.wait_for_state(worker, running["id"], "running")
        queued = worker.submit_payload(request())
        cancelled = worker.cancel(queued["id"])
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertIsNone(worker.artifact(queued["id"]))

    def test_terminal_retention_prunes_old_metadata_and_artifact(self) -> None:
        worker = self.worker(max_retained_jobs=1)
        worker.start()
        first = worker.wait(worker.submit_payload(request())["id"])
        first_artifact = worker.artifact(first["id"])
        self.assertIsNotNone(first_artifact)
        worker.wait(worker.submit_payload(request())["id"])
        self.assertIsNone(worker.status(first["id"]))
        assert first_artifact is not None
        self.assertFalse(first_artifact.exists())

    def test_retryable_and_permanent_failures_have_distinct_lifecycle(self) -> None:
        retrying = self.worker(
            FakeAdapter(retryable_failures=1), retry_backoff_seconds=0
        )
        retrying.start()
        recovered = retrying.wait(retrying.submit_payload(request())["id"])
        self.assertEqual((recovered["state"], recovered["attempts"]), ("succeeded", 2))

        second_state = Path(self.temporary.name) / "permanent"
        permanent = LocalSynthesisWorker(
            second_state, {"fake": FakeAdapter(permanent_failure=True)}
        )
        self.workers.append(permanent)
        permanent.start()
        failed = permanent.wait(permanent.submit_payload(request())["id"])
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["attempts"], 1)
        self.assertEqual(failed["failure"]["retryClass"], "permanent")

    def test_logs_and_metrics_exclude_content_ids_paths_and_voice_labels(self) -> None:
        stream = io.StringIO()
        logger = logging.getLogger(f"worker-test-{id(self)}")
        logger.handlers = [logging.StreamHandler(stream)]
        logger.setLevel(logging.INFO)
        event_logger = EventLogger({"fake"}, logger)
        worker = LocalSynthesisWorker(
            self.state, {"fake": FakeAdapter()}, event_logger=event_logger
        )
        self.workers.append(worker)
        worker.start()
        done = worker.wait(
            worker.submit_payload(request(text="PRIVATE ARTICLE TEXT"))["id"]
        )
        logs = stream.getvalue()
        metrics = worker.prometheus_metrics()
        self.assertNotIn("PRIVATE ARTICLE TEXT", logs + metrics)
        self.assertNotIn(done["id"], logs + metrics)
        self.assertNotIn("voice", metrics)
        self.assertIn('provider="fake",result="succeeded"', metrics)
        for line in logs.splitlines():
            self.assertEqual(
                set(json.loads(line)), {"event", "provider", "result", "retryClass"}
            )
