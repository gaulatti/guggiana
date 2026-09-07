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
from tts_bakeoff.asr import AsrUnavailable, FasterWhisperAdapter, normalize_text, semantic_metrics, verify_asr_model
from tts_bakeoff.audio import AudioValidationError, inspect_wav
from tts_bakeoff.catalog import (
    CatalogError,
    REQUIRED_CATEGORIES,
    REQUIRED_LOCALES,
    file_digest,
    load_and_validate_asr_config,
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
from tts_bakeoff.review import write_review_bundle


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures, cls.config = load_and_validate_catalog()
        cls.asr_config = load_and_validate_asr_config()

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

    def test_asr_catalog_is_pinned_and_covers_every_locale(self) -> None:
        self.assertEqual("1.2.1", self.asr_config["dependency"]["version"])
        self.assertEqual(
            "d90ca5fe260221311c53c58e660288d3deb8d356",
            self.asr_config["model"]["revision"],
        )
        self.assertEqual(set(REQUIRED_LOCALES), set(self.asr_config["locale_mapping"]))
        self.assertTrue(
            all(
                artifact["checksum_algorithm"] == "sha256"
                and len(artifact["checksum"]) == 64
                for artifact in self.asr_config["model"]["artifacts"]
            )
        )


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

class SemanticIntegrityTests(unittest.TestCase):
    def test_exact_match_has_zero_error(self) -> None:
        evidence = semantic_metrics(
            "The NOAA team said, “The API is ready.”",
            "The NOAA team said, “The API is ready.”",
            "en-US",
            "acronyms-quotations",
        )
        self.assertEqual("completed", evidence["status"])
        self.assertEqual(0.0, evidence["wer"])
        self.assertEqual(0.0, evidence["cer"])
        self.assertEqual(0, evidence["fixture_checks"]["acronyms"]["missing"])
        self.assertEqual(0, evidence["fixture_checks"]["quotations"]["missing"])

    def test_case_and_punctuation_normalize_deterministically(self) -> None:
        self.assertEqual(
            normalize_text("HELLO, World!", "en-US"),
            normalize_text("hello world", "en-US"),
        )
        self.assertEqual("12.75 1204", normalize_text("12,75; 1.204", "pt-BR"))

    def test_numeric_date_and_currency_preservation_is_explicit(self) -> None:
        evidence = semantic_metrics(
            "On September 6, 2026, it cost $12.75.",
            "On September 6 2026 it cost USD 12.75",
            "en-US",
            "numbers-dates-currency",
        )
        for check in evidence["fixture_checks"].values():
            self.assertEqual(0, check["missing"])

    def test_german_low_high_quotation_marks_are_checked(self) -> None:
        evidence = semantic_metrics(
            "Das Team sagte: „Die API ist bereit“.",
            "Das Team sagte die API ist bereit.",
            "de-DE",
            "acronyms-quotations",
        )
        self.assertEqual(1, evidence["fixture_checks"]["quotations"]["expected"])
        self.assertEqual(1, evidence["fixture_checks"]["quotations"]["matched"])

    def test_tail_truncation_is_a_warning(self) -> None:
        evidence = semantic_metrics(
            "one two three four five six seven eight nine ten eleven twelve thirteen",
            "one two three four five six seven",
            "en-US",
            "long-form",
        )
        self.assertEqual("warning", evidence["status"])
        self.assertIn("tail-coverage-incomplete", evidence["warning_codes"])
        self.assertLess(evidence["missing_tail"]["coverage"], 1.0)

    def test_unexpected_repeated_span_is_a_warning(self) -> None:
        evidence = semantic_metrics(
            "alpha beta gamma delta epsilon",
            "alpha beta gamma alpha beta gamma delta epsilon",
            "en-US",
            "headline-byline",
        )
        self.assertEqual("warning", evidence["status"])
        self.assertGreater(evidence["repeated_spans"]["extra_occurrences"], 0)

    def test_unsupported_locale_is_unavailable(self) -> None:
        with self.assertRaisesRegex(AsrUnavailable, "unsupported-locale"):
            normalize_text("hello", "it-IT")

    def test_missing_model_is_unavailable(self) -> None:
        config = load_and_validate_asr_config()
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            AsrUnavailable, "missing-verified-model"
        ):
            verify_asr_model(config, Path(directory))

    def test_corrupt_audio_is_rejected_before_transcription(self) -> None:
        adapter = object.__new__(FasterWhisperAdapter)
        adapter.config = load_and_validate_asr_config()
        adapter.model = mock.Mock()
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "corrupt.wav"
            audio.write_bytes(b"not a wave")
            with self.assertRaises((AudioValidationError, wave.Error, EOFError)):
                adapter.evaluate(
                    audio,
                    {
                        "locale": "en-US",
                        "category": "headline-byline",
                        "text": "hello world",
                    },
                )
            adapter.model.transcribe.assert_not_called()


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
            self.assertTrue(all(record["status"] == "completed" for record in manifest["records"]))
            self.assertIsNotNone(manifest["summary"]["fake"]["median_rtf"])
            self.assertIsNotNone(manifest["summary"]["fake"]["median_peak_rss_mib"])
            self.assertEqual("no-selection", manifest["decision"]["status"])
            self.assertEqual("candidate-ineligible", manifest["evidence_readiness"]["status"])
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

    def test_corrupt_engine_output_emits_failed_objective_state(self) -> None:
        class CorruptAdapter:
            def synthesize(self, fixture: dict[str, object], destination: Path) -> object:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"not a wave")
                return types.SimpleNamespace(
                    cold_load_seconds=0.0,
                    synthesis_seconds=0.1,
                    model="test",
                    voice="test",
                    backend="test",
                )

        with tempfile.TemporaryDirectory() as directory, mock.patch(
            "tts_bakeoff.runner.build_adapter", return_value=CorruptAdapter()
        ):
            manifest = run_bakeoff(
                self.fixtures,
                self.config,
                ["fake"],
                Path(directory) / "artifacts",
                Path(directory) / "models",
                fixture_ids={"en-US-headline-byline"},
            )
        record = manifest["records"][0]
        self.assertEqual("failed", record["status"])
        self.assertEqual("failed", record["evidence"]["objective_audio"])
        self.assertEqual("not-run", record["evidence"]["asr_semantic"])

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
        self.assertEqual(2, combined["summary"]["fake"]["completed"])

    def test_enabled_but_missing_asr_is_not_conflated_with_completed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = run_bakeoff(
                self.fixtures,
                self.config,
                ["fake"],
                root / "artifacts",
                root / "models",
                asr_config=load_and_validate_asr_config(),
                asr_model_dir=root / "models" / "asr",
                fixture_ids={"en-US-headline-byline"},
            )
        self.assertEqual("warning", manifest["records"][0]["status"])
        self.assertEqual("completed", manifest["records"][0]["evidence"]["objective_audio"])
        self.assertEqual("unavailable", manifest["records"][0]["evidence"]["asr_semantic"])

    def test_review_bundle_is_blinded_checksummed_and_keyed_separately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / "artifacts"
            manifest = run_bakeoff(
                self.fixtures,
                self.config,
                ["fake"],
                artifacts,
                root / "models",
                fixture_ids={"en-US-headline-byline"},
            )
            bundle = root / "bundle"
            key = root / "private" / "engine-key.json"
            result = write_review_bundle(manifest, self.fixtures, artifacts, bundle, key)
            public = json.loads((bundle / "reviewer-manifest.json").read_text())
            private = json.loads(key.read_text())
            self.assertEqual("completed", result["status"])
            self.assertFalse(public["engine_identity_present"])
            self.assertFalse(public["source_identifiers_present"])
            self.assertNotIn("source_run_id", public)
            self.assertNotIn('"engine":', json.dumps(public))
            self.assertEqual("fake", private["records"][0]["engine"])
            self.assertNotEqual(
                manifest["records"][0]["blind_id"], public["clips"][0]["audio_id"]
            )
            self.assertTrue((bundle / "SHA256SUMS").is_file())
            self.assertTrue((bundle / public["clips"][0]["filename"]).is_file())
            source_hashes = {
                record["audio"]["sha256"]
                for record in manifest["records"]
                if record["audio"] is not None
            }
            public_hashes = {clip["sha256"] for clip in public["clips"]}
            self.assertTrue(source_hashes.isdisjoint(public_hashes))
            self.assertFalse(result["source_checksums_reused"])
            self.assertFalse(result["public_packet_checksums_recorded_in_result"])
            source_identifiers = {
                manifest["run_id"],
                *source_hashes,
                *(record["audio"]["artifact"] for record in manifest["records"]),
            }
            serialized_public = json.dumps(public)
            self.assertTrue(
                all(identifier not in serialized_public for identifier in source_identifiers)
            )


if __name__ == "__main__":
    unittest.main()
