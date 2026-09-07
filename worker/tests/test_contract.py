from __future__ import annotations

import unittest

from local_synthesis.contract import ContractError, parse_request


def request(
    provider: str = "fake", text: str = "Fixture sentence."
) -> dict[str, object]:
    return {
        "provider": provider,
        "locale": "en-US",
        "voiceRole": "narrator",
        "segments": [
            {"kind": "text", "text": text},
            {"kind": "pause", "durationMs": 100},
        ],
    }


class ContractTests(unittest.TestCase):
    def test_requires_an_explicit_enabled_provider(self) -> None:
        with self.assertRaisesRegex(ContractError, "explicitly enabled") as raised:
            parse_request(request("piper"), {"chatterbox"})
        self.assertEqual(raised.exception.code, "provider_unavailable")

    def test_rejects_task_tokens_and_unknown_fields(self) -> None:
        payload = request()
        payload["taskToken"] = "must-never-cross-this-boundary"
        with self.assertRaises(ContractError):
            parse_request(payload, {"fake"})

    def test_enforces_bounded_text_and_pause_segments(self) -> None:
        payload = request(text="x" * 2_901)
        with self.assertRaisesRegex(ContractError, "segment exceeds"):
            parse_request(payload, {"fake"})
        payload = request()
        payload["segments"] = [
            {"kind": "pause", "durationMs": 5_001},
            {"kind": "text", "text": "x"},
        ]
        with self.assertRaisesRegex(ContractError, "pause duration"):
            parse_request(payload, {"fake"})

    def test_accepts_all_and_only_contract_fields(self) -> None:
        parsed = parse_request(request(), {"fake"})
        self.assertEqual(parsed.provider, "fake")
        self.assertEqual(parsed.locale, "en-US")
        self.assertEqual(parsed.as_dict(), request())
