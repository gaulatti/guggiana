from __future__ import annotations

import copy
import csv
import io
import json
import socket
import struct
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest import mock

EXPERIMENT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EXPERIMENT))

from tts_bakeoff import cli
from tts_bakeoff.adapters import EngineUnavailable, PiperAdapter
from tts_bakeoff.audio import AudioValidationError, inspect_wav
from tts_bakeoff.catalog import (
    CatalogError,
    REQUIRED_CATEGORIES,
    REQUIRED_LOCALES,
    file_digest,
    load_and_validate_catalog,
    validate_fixtures,
)
from tts_bakeoff.fetch import FetchError, _download_verified
from tts_bakeoff.network import NetworkDenied, deny_network
from tts_bakeoff.runner import (
    combine_process_cold_manifests,
    render_report,
    run_bakeoff,
    write_blinded_sheet,
)


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures, cls.config = load_and_validate_catalog()

    def test_fixture_matrix_is_exactly_four_by_five(self) -> None:
        self.assertEqual(20, len(self.fixtures["fixtures"]))
        pairs = {(item["locale"], item["category"]) for item in self.fixtures["fixtures"]}
        self.assertEqual(
            {(locale, category) for locale in REQUIRED_LOCALES for category in REQUIRED_CATEGORIES},
            pairs,
        )

    def test_duplicate_fixture_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.fixtures)
        invalid["fixtures"][1]["id"] = invalid["fixtures"][0]["id"]
        with self.assertRaisesRegex(CatalogError, "duplicate fixture id"):
            validate_fixtures(invalid)

    def test_engine_catalog_has_immutable_and_license_evidence(self) -> None:
        engines = self.config["engines"]
        self.assertEqual("1.8.0", engines["piper"]["dependency"]["version"])
        self.assertEqual(
            "375a0fe641dea077c2a47b4e9a056d6da521eed3",
            engines["piper"]["model_repository"]["revision"],
        )
        for mapping in engines["piper"]["locale_mapping"].values():
            self.assertEqual(64, len(mapping["model_sha256"]))
            self.assertTrue(mapping["dataset_license"])
        self.assertIn("selection is forbidden", self.config["decision_gates"]["es-US"])


class AudioTests(unittest.TestCase):
    def test_silent_wav_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "silent.wav"
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16_000)
                output.writeframes(b"\0\0" * 16_000)
            with self.assertRaisesRegex(AudioValidationError, "silent"):
                inspect_wav(path)

    def test_truncated_pcm_payload_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "truncated.wav"
            # Header claims 2,000 bytes, but the data chunk contains only 200.
            payload = b"\x10\x00" * 100
            riff_size = 36 + 2_000
            header = (
                b"RIFF"
                + struct.pack("<I", riff_size)
                + b"WAVEfmt "
                + struct.pack("<IHHIIHH", 16, 1, 1, 16_000, 32_000, 2, 16)
                + b"data"
                + struct.pack("<I", 2_000)
            )
            path.write_bytes(header + payload)
            with self.assertRaisesRegex(AudioValidationError, "truncated PCM"):
                inspect_wav(path)


class OfflineBoundaryTests(unittest.TestCase):
    def test_socket_connections_are_denied_and_restored(self) -> None:
        original = socket.create_connection
        with deny_network(), self.assertRaises(NetworkDenied):
            socket.create_connection(("example.com", 443))
        with socket.socket() as client, deny_network(), self.assertRaises(NetworkDenied):
            client.connect_ex(("127.0.0.1", 9))
        self.assertIs(original, socket.create_connection)

    def test_piper_checksum_mismatch_fails_closed_before_load(self) -> None:
        fake_module = types.ModuleType("piper")
        fake_module.PiperVoice = mock.Mock()
        with mock.patch.dict(sys.modules, {"piper": fake_module}), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "voice.onnx"
            model.write_bytes(b"wrong")
            Path(f"{model}.json").write_text("{}")
            (root / "MODEL_CARD").write_text("license")
            config = {
                "locale_mapping": {
                    "en-US": {
                        "path": "voice.onnx",
                        "voice": "test",
                        "model_md5": "0" * 32,
                        "model_sha256": "0" * 64,
                        "config_md5": file_digest(Path(f"{model}.json"), "md5"),
                        "model_card_md5": file_digest(root / "MODEL_CARD", "md5"),
                    }
                }
            }
            adapter = PiperAdapter(config, root)
            with self.assertRaisesRegex(EngineUnavailable, "checksum mismatch"):
                adapter._load("en-US")

    def test_failed_fetch_removes_partial_artifact(self) -> None:
        response = io.BytesIO(b"not-the-expected-file")
        with tempfile.TemporaryDirectory() as directory, mock.patch(
            "urllib.request.urlopen", return_value=response
        ):
            destination = Path(directory) / "model.onnx"
            with self.assertRaises(FetchError):
                _download_verified("https://example.invalid/model", destination, "sha256", "0" * 64)
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_suffix(".onnx.part").exists())


class HarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures, cls.config = load_and_validate_catalog()

    def test_fake_run_exercises_all_fixtures_and_blinding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = run_bakeoff(
                self.fixtures,
                self.config,
                ["fake"],
                root / "artifacts",
                root / "models",
            )
            self.assertEqual(20, len(manifest["records"]))
            self.assertTrue(all(record["status"] == "succeeded" for record in manifest["records"]))
            self.assertIsNotNone(manifest["summary"]["fake"]["median_rtf"])
            self.assertIsNotNone(manifest["summary"]["fake"]["median_peak_rss_mib"])
            self.assertEqual("no-selection", manifest["decision"]["status"])
            self.assertNotIn("text", json.dumps(manifest))

            sheet = root / "scores.csv"
            write_blinded_sheet(manifest, sheet)
            with sheet.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(20, len(rows))
            self.assertNotIn("engine", rows[0])
            self.assertIn("Median peak RSS", render_report(manifest))

    def test_unavailable_engine_emits_one_record_per_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch(
            "tts_bakeoff.runner.build_adapter",
            side_effect=EngineUnavailable("private /path must not be emitted"),
        ):
            manifest = run_bakeoff(
                self.fixtures,
                self.config,
                ["piper"],
                Path(directory) / "artifacts",
                Path(directory) / "models",
            )
        self.assertEqual(20, manifest["summary"]["piper"]["unavailable"])
        self.assertNotIn("/path", json.dumps(manifest))

    def test_cli_requires_opaque_id_for_chatterbox_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "private-name.wav"
            reference.touch()
            with self.assertRaisesRegex(SystemExit, "opaque --voice-reference-id"):
                cli.main(
                    [
                        "run",
                        "--engine",
                        "chatterbox",
                        "--voice-reference",
                        str(reference),
                    ]
                )

    def test_disjoint_manifests_combine_as_process_cold_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = run_bakeoff(
                self.fixtures,
                self.config,
                ["fake"],
                root / "artifacts",
                root / "models",
                fixture_ids={"en-US-headline-byline"},
            )
            second = run_bakeoff(
                self.fixtures,
                self.config,
                ["fake"],
                root / "artifacts",
                root / "models",
                fixture_ids={"fr-FR-headline-byline"},
            )
            combined = combine_process_cold_manifests([first, second])
        self.assertTrue(combined["execution"]["process_cold"])
        self.assertEqual(2, combined["execution"]["source_processes"])
        self.assertEqual(2, combined["summary"]["fake"]["succeeded"])


if __name__ == "__main__":
    unittest.main()
