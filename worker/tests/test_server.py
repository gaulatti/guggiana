from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from local_synthesis import FakeAdapter, LocalSynthesisWorker
from local_synthesis.server import handler_factory

from .test_contract import request


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.worker = LocalSynthesisWorker(
            Path(self.temporary.name) / "state", {"fake": FakeAdapter()}
        )
        self.worker.start()
        self.token = "fixture-token-that-is-at-least-32-characters"
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), handler_factory(self.worker, self.token)
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.worker.close()
        self.temporary.cleanup()

    def call(
        self,
        path: str,
        method: str = "GET",
        body: object | None = None,
        authorized: bool = True,
    ) -> tuple[int, bytes]:
        headers = {}
        data = None
        if authorized:
            headers["Authorization"] = f"Bearer {self.token}"
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        try:
            with urllib.request.urlopen(
                urllib.request.Request(
                    self.base + path, data=data, headers=headers, method=method
                ),
                timeout=2,
            ) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            try:
                return error.code, error.read()
            finally:
                error.close()

    def test_http_lifecycle_requires_auth_and_serves_artifact(self) -> None:
        self.assertEqual(self.call("/healthz", authorized=False)[0], 200)
        self.assertEqual(self.call("/readyz", authorized=False)[0], 200)
        self.assertEqual(self.call("/metrics", authorized=False)[0], 401)
        status, body = self.call("/v1/jobs", "POST", request())
        self.assertEqual(status, 202)
        job_id = json.loads(body)["id"]
        self.worker.wait(job_id)
        status, body = self.call(f"/v1/jobs/{job_id}")
        self.assertEqual(status, 200)
        self.assertNotIn("segments", json.loads(body))
        status, audio = self.call(f"/v1/jobs/{job_id}/artifact")
        self.assertEqual(status, 200)
        self.assertEqual(audio[:4], b"RIFF")

    def test_http_rejects_unknown_fields_without_fallback(self) -> None:
        payload = request()
        payload["taskToken"] = "forbidden"
        status, body = self.call("/v1/jobs", "POST", payload)
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body), {"error": "invalid_request"})
