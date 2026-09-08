from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_synthesis.adapters import build_candidate_adapters
from local_synthesis.contract import LOCALES
from local_synthesis.manifest import (
    ManifestError,
    VerifiedProvider,
    load_manifest,
    verify_provider,
)

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parent


def fixture_manifest(checksum: str) -> dict[str, object]:
    locales = {locale: {"datasetLicense": "fixture-only"} for locale in LOCALES}
    return {
        "schemaVersion": 1,
        "providers": {
            "fixture": {
                "model": "fixture-model",
                "modelRevision": "1" * 40,
                "runtimeRevision": "2" * 40,
                "runtimeLicense": "MIT",
                "voiceProvenance": "synthetic fixture",
                "dependency": {
                    "distribution": "fixture",
                    "version": "1",
                    "wheelSha256": "a" * 64,
                },
                "locales": locales,
                "artifacts": [
                    {"path": "model.bin", "algorithm": "sha256", "checksum": checksum}
                ],
            }
        },
    }


class ManifestTests(unittest.TestCase):
    def test_committed_manifest_pins_both_candidate_runtimes_models_and_licenses(
        self,
    ) -> None:
        manifest, _ = load_manifest(ROOT / "config" / "model-manifest.json")
        self.assertEqual(set(manifest["providers"]), {"piper", "chatterbox"})
        for provider in manifest["providers"].values():
            self.assertRegex(provider["modelRevision"], r"^[a-f0-9]{40}$")
            self.assertRegex(provider["runtimeRevision"], r"^[a-f0-9]{40}$")
            self.assertTrue(provider["runtimeLicense"])
            self.assertEqual(set(provider["locales"]), set(LOCALES))
            self.assertTrue(
                all(locale["datasetLicense"] for locale in provider["locales"].values())
            )
            self.assertTrue(
                all(
                    len(artifact["checksum"]) in {32, 64}
                    for artifact in provider["artifacts"]
                )
            )

    def test_worker_pins_are_derived_from_landed_bakeoff_evidence(self) -> None:
        manifest, _ = load_manifest(ROOT / "config" / "model-manifest.json")
        evidence = json.loads(
            (
                REPOSITORY / "experiments" / "tts-bakeoff" / "config" / "engines.json"
            ).read_text()
        )
        for name in ("piper", "chatterbox"):
            actual = manifest["providers"][name]
            expected = evidence["engines"][name]
            self.assertEqual(
                actual["dependency"]["version"], expected["dependency"]["version"]
            )
            self.assertEqual(actual["runtimeRevision"], expected["source"]["revision"])
        self.assertEqual(
            manifest["providers"]["piper"]["modelRevision"],
            evidence["engines"]["piper"]["model_repository"]["revision"],
        )
        self.assertEqual(
            manifest["providers"]["chatterbox"]["modelRevision"],
            evidence["engines"]["chatterbox"]["models"]["multilingual-v3"]["revision"],
        )

    def test_verification_accepts_an_exact_fixture_and_rejects_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider_root = root / "fixture"
            provider_root.mkdir()
            artifact = provider_root / "model.bin"
            artifact.write_bytes(b"verified")
            checksum = hashlib.sha256(b"verified").hexdigest()
            manifest = fixture_manifest(checksum)
            verified = verify_provider(
                "fixture", manifest, "b" * 64, root, verify_installed_distribution=False
            )
            self.assertEqual(verified.model_revision, "1" * 40)
            artifact.write_bytes(b"corrupt")
            with self.assertRaisesRegex(ManifestError, "does not match"):
                verify_provider(
                    "fixture",
                    manifest,
                    "b" * 64,
                    root,
                    verify_installed_distribution=False,
                )

    def test_rejects_artifact_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = fixture_manifest(hashlib.sha256(b"x").hexdigest())
            manifest["providers"]["fixture"]["artifacts"][0]["path"] = "../escape"
            with self.assertRaisesRegex(ManifestError, "escapes"):
                verify_provider(
                    "fixture",
                    manifest,
                    "b" * 64,
                    root,
                    verify_installed_distribution=False,
                )

    def test_configuration_can_enable_either_verified_candidate_without_a_default(
        self,
    ) -> None:
        details = {
            "voiceProvenance": "fixture",
            "locales": {locale: {"datasetLicense": "fixture"} for locale in LOCALES},
        }

        def verified(name: str, *_args: object, **_kwargs: object) -> VerifiedProvider:
            return VerifiedProvider(
                name, "model", "1" * 40, "2" * 40, "MIT", "3" * 64, details
            )

        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "local_synthesis.adapters.load_manifest", return_value=({}, "3" * 64)
            ),
            patch(
                "local_synthesis.adapters.verify_provider", side_effect=verified
            ) as verifier,
        ):
            root = Path(directory)
            piper = build_candidate_adapters(
                root / "manifest.json",
                root,
                ["piper"],
                {"piper": {"memoryLimitMiB": 768}},
            )
            self.assertEqual(set(piper), {"piper"})

            reference = root / "reference.wav"
            reference.write_bytes(b"consented-fixture")
            chatterbox = build_candidate_adapters(
                root / "manifest.json",
                root,
                ["chatterbox"],
                {
                    "chatterbox": {
                        "memoryLimitMiB": 12_288,
                        "device": "cpu",
                        "voiceReferencePath": str(reference),
                        "voiceReferenceSha256": hashlib.sha256(
                            reference.read_bytes()
                        ).hexdigest(),
                        "voiceConsentId": "opaque-fixture-consent",
                    }
                },
            )
            self.assertEqual(set(chatterbox), {"chatterbox"})
            self.assertEqual(
                [call.args[0] for call in verifier.call_args_list],
                ["piper", "chatterbox"],
            )
