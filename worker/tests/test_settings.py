from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from local_synthesis.settings import SettingsError, load_settings, read_token


def settings() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "bindAddress": "127.0.0.1",
        "port": 8787,
        "stateDirectory": "state",
        "tokenFile": "token",
        "modelManifest": "manifest.json",
        "modelRoot": "models",
        "enabledProviders": ["piper"],
        "providerOptions": {"piper": {"memoryLimitMiB": 768}},
        "concurrency": 1,
        "queueCapacity": 4,
        "timeoutSeconds": 120,
        "maxAttempts": 2,
        "maxArtifactBytes": 268435456,
        "maxRetainedJobs": 32,
    }


class SettingsTests(unittest.TestCase):
    def test_requires_loopback_and_explicit_provider(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker.json"
            payload = settings()
            payload["bindAddress"] = "0.0.0.0"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(SettingsError, "loopback"):
                load_settings(path)
            payload["bindAddress"] = "127.0.0.1"
            payload["enabledProviders"] = []
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(SettingsError, "at least one"):
                load_settings(path)

    def test_token_is_file_only_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "token"
            token.write_text("x" * 32)
            os.chmod(token, 0o600)
            self.assertEqual(read_token(token), "x" * 32)
            os.chmod(token, 0o644)
            with self.assertRaisesRegex(SettingsError, "group or others"):
                read_token(token)

    def test_integer_bounds_are_not_silently_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker.json"
            payload = settings()
            payload["concurrency"] = 1.5
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(SettingsError, "numeric"):
                load_settings(path)
