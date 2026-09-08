from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_container_base_is_digest_pinned_and_non_root(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertRegex(
            dockerfile.splitlines()[0],
            r"^FROM python:3\.11\.13-slim-bookworm@sha256:[a-f0-9]{64}$",
        )
        self.assertIn("USER 65532:65532", dockerfile)
        self.assertNotIn("ADD http", dockerfile)
        self.assertNotIn("curl ", dockerfile)

    def test_example_has_no_default_or_cloud_fallback_field(self) -> None:
        configuration = json.loads(
            (ROOT / "config" / "worker.example.json").read_text()
        )
        self.assertNotIn("defaultProvider", configuration)
        self.assertNotIn("fallbackProvider", configuration)
        self.assertNotIn("polly", json.dumps(configuration).lower())
        self.assertEqual(configuration["bindAddress"], "127.0.0.1")
        self.assertEqual(configuration["concurrency"], 1)
        self.assertGreaterEqual(
            configuration["providerOptions"]["piper"]["memoryLimitMiB"], 768
        )
