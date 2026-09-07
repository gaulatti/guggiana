from __future__ import annotations

from dataclasses import dataclass
from typing import Any

LOCALES = ("en-US", "es-US", "fr-FR", "de-DE", "pt-BR")
MAX_SEGMENTS = 64
MAX_SEGMENT_CHARACTERS = 2_900
MAX_DOCUMENT_CHARACTERS = 20_000
MAX_PAUSE_MILLISECONDS = 5_000


class ContractError(ValueError):
    """A request does not satisfy the bounded public contract."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Segment:
    kind: str
    text: str | None = None
    duration_ms: int | None = None

    def as_dict(self) -> dict[str, object]:
        if self.kind == "text":
            return {"kind": "text", "text": self.text or ""}
        return {"kind": "pause", "durationMs": self.duration_ms or 0}


@dataclass(frozen=True)
class SynthesisRequest:
    provider: str
    locale: str
    voice_role: str
    segments: tuple[Segment, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "locale": self.locale,
            "voiceRole": self.voice_role,
            "segments": [segment.as_dict() for segment in self.segments],
        }


def _fail(code: str, message: str) -> ContractError:
    return ContractError(code, message)


def parse_request(payload: Any, allowed_providers: set[str]) -> SynthesisRequest:
    if not isinstance(payload, dict):
        raise _fail("invalid_request", "request must be a JSON object")
    expected = {"provider", "locale", "voiceRole", "segments"}
    if set(payload) != expected:
        raise _fail(
            "invalid_request",
            "request fields must be provider, locale, voiceRole, and segments",
        )

    provider = payload.get("provider")
    if not isinstance(provider, str) or provider not in allowed_providers:
        raise _fail(
            "provider_unavailable", "provider must name one explicitly enabled adapter"
        )
    locale = payload.get("locale")
    if not isinstance(locale, str) or locale not in LOCALES:
        raise _fail("unsupported_locale", "locale is not supported")
    if payload.get("voiceRole") != "narrator":
        raise _fail("unsupported_voice_role", "voiceRole must be narrator")
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not 1 <= len(raw_segments) <= MAX_SEGMENTS:
        raise _fail(
            "invalid_request", f"segments must contain 1-{MAX_SEGMENTS} entries"
        )

    parsed: list[Segment] = []
    spoken_characters = 0
    for raw in raw_segments:
        if not isinstance(raw, dict) or raw.get("kind") not in {"text", "pause"}:
            raise _fail("invalid_request", "each segment must be text or pause")
        if raw["kind"] == "text":
            if set(raw) != {"kind", "text"}:
                raise _fail(
                    "invalid_request", "text segments accept only kind and text"
                )
            text = raw.get("text")
            if not isinstance(text, str) or not text.strip():
                raise _fail("empty_document", "text segments must contain spoken text")
            if len(text) > MAX_SEGMENT_CHARACTERS:
                raise _fail(
                    "segment_too_long", "text segment exceeds the configured bound"
                )
            spoken_characters += len(text)
            parsed.append(Segment(kind="text", text=text))
        else:
            if set(raw) != {"kind", "durationMs"}:
                raise _fail(
                    "invalid_request", "pause segments accept only kind and durationMs"
                )
            duration = raw.get("durationMs")
            if (
                isinstance(duration, bool)
                or not isinstance(duration, int)
                or not 0 <= duration <= MAX_PAUSE_MILLISECONDS
            ):
                raise _fail(
                    "invalid_pause", "pause duration is outside the configured bound"
                )
            parsed.append(Segment(kind="pause", duration_ms=duration))

    if spoken_characters == 0:
        raise _fail("empty_document", "document has no spoken text")
    if spoken_characters > MAX_DOCUMENT_CHARACTERS:
        raise _fail(
            "document_too_long", "document exceeds the configured character bound"
        )
    return SynthesisRequest(provider, locale, "narrator", tuple(parsed))
