from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .audio import inspect_wav
from .catalog import REQUIRED_LOCALES, file_digest


class AsrUnavailable(RuntimeError):
    """The optional local ASR dependency or its verified model is unavailable."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class AsrFailed(RuntimeError):
    """The verified local ASR runtime could not evaluate an audio artifact."""


_NUMBER_RULES = {
    "en-US": {"decimal": ".", "thousands": ","},
    "es-US": {"decimal": ",", "thousands": "."},
    "fr-FR": {"decimal": ",", "thousands": " "},
    "de-DE": {"decimal": ",", "thousands": "."},
    "pt-BR": {"decimal": ",", "thousands": "."},
}

_MONTHS = {
    "en-US": {
        "january", "february", "march", "april", "may", "june", "july",
        "august", "september", "october", "november", "december",
    },
    "es-US": {
        "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
        "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    },
    "fr-FR": {
        "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre",
    },
    "de-DE": {
        "januar", "februar", "märz", "april", "mai", "juni", "juli",
        "august", "september", "oktober", "november", "dezember",
    },
    "pt-BR": {
        "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
        "agosto", "setembro", "outubro", "novembro", "dezembro",
    },
}

_CURRENCY_TERMS = {
    "en-US": {"dollar", "dollars", "usd"},
    "es-US": {"dólar", "dólares", "usd"},
    "fr-FR": {"euro", "euros", "eur"},
    "de-DE": {"euro", "eur"},
    "pt-BR": {"real", "reais", "brl"},
}


def normalize_text(text: str, locale: str) -> str:
    """Return locale-aware, deterministic text for word/character comparison."""
    if locale not in REQUIRED_LOCALES:
        raise AsrUnavailable("unsupported-locale")
    value = unicodedata.normalize("NFKC", text).casefold()
    for symbol, name in {"$": " usd ", "€": " eur ", "£": " gbp "}.items():
        value = value.replace(symbol, name)
    rules = _NUMBER_RULES[locale]
    thousands = re.escape(rules["thousands"])
    decimal = re.escape(rules["decimal"])
    if rules["thousands"] == " ":
        value = re.sub(r"(?<=\d)[\s\u00a0\u202f](?=\d{3}(?:\D|$))", "", value)
    else:
        value = re.sub(rf"(?<=\d){thousands}(?=\d{{3}}(?:\D|$))", "", value)
    if rules["decimal"] != ".":
        value = re.sub(rf"(?<=\d){decimal}(?=\d)", ".", value)
    tokens = re.findall(r"\d+(?:\.\d+)?|[^\W\d_]+", value, flags=re.UNICODE)
    return " ".join(tokens)


def _edit_distance(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_item in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_item in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_item != right_item),
                )
            )
        previous = current
    return previous[-1]


def _lcs_length(left: list[str], right: list[str]) -> int:
    previous = [0] * (len(right) + 1)
    for left_item in left:
        current = [0]
        for right_index, right_item in enumerate(right, start=1):
            current.append(
                previous[right_index - 1] + 1
                if left_item == right_item
                else max(previous[right_index], current[-1])
            )
        previous = current
    return previous[-1]


def _contains_sequence(tokens: list[str], expected: list[str]) -> bool:
    if not expected:
        return True
    width = len(expected)
    return any(
        tokens[index : index + width] == expected
        for index in range(len(tokens) - width + 1)
    )


def _count_preserved(reference: Iterable[str], hypothesis: list[str]) -> dict[str, int]:
    expected = Counter(reference)
    observed = Counter(hypothesis)
    total = sum(expected.values())
    matched = sum(min(count, observed[token]) for token, count in expected.items())
    return {"expected": total, "matched": matched, "missing": total - matched}


def _acronyms(text: str) -> list[str]:
    values: list[str] = []
    for token in re.findall(r"[^\W\d_]+(?:\.[^\W\d_]+)*\.?", text, flags=re.UNICODE):
        letters = "".join(character for character in token if character.isalpha())
        if len(letters) >= 2 and letters.isupper():
            values.append(letters.casefold())
    return values


def _quoted_sequences(text: str, locale: str) -> list[list[str]]:
    matches = re.findall(r"[\"“„«](.*?)[\"“”»]", text)
    normalized = [normalize_text(value, locale).split() for value in matches]
    return [value for value in normalized if value]


def _unexpected_repeated_spans(
    reference: list[str], hypothesis: list[str], width: int = 3
) -> dict[str, int]:
    def spans(tokens: list[str]) -> Counter[tuple[str, ...]]:
        return Counter(tuple(tokens[index : index + width]) for index in range(len(tokens) - width + 1))

    reference_spans = spans(reference)
    hypothesis_spans = spans(hypothesis)
    unexpected = {
        span: count - reference_spans.get(span, 0)
        for span, count in hypothesis_spans.items()
        if count > 1 and count > reference_spans.get(span, 0)
    }
    return {
        "span_tokens": width,
        "unique_unexpected_spans": len(unexpected),
        "extra_occurrences": sum(unexpected.values()),
    }


def semantic_metrics(
    reference_text: str, transcript: str, locale: str, category: str
) -> dict[str, Any]:
    reference_normalized = normalize_text(reference_text, locale)
    transcript_normalized = normalize_text(transcript, locale)
    reference_words = reference_normalized.split()
    transcript_words = transcript_normalized.split()
    word_edits = _edit_distance(reference_words, transcript_words)
    reference_chars = list(reference_normalized)
    transcript_chars = list(transcript_normalized)
    character_edits = _edit_distance(reference_chars, transcript_chars)

    tail_size = min(12, len(reference_words))
    reference_tail = reference_words[-tail_size:]
    hypothesis_tail = transcript_words[-max(tail_size * 2, tail_size) :]
    tail_matched = _lcs_length(reference_tail, hypothesis_tail)
    repeated = _unexpected_repeated_spans(reference_words, transcript_words)

    checks: dict[str, dict[str, int] | dict[str, bool | int]] = {}
    if category == "numbers-dates-currency":
        numeric = [
            token
            for token in reference_words
            if any(character.isdigit() for character in token)
        ]
        months = [token for token in reference_words if token in _MONTHS[locale]]
        currency = [token for token in reference_words if token in _CURRENCY_TERMS[locale]]
        checks = {
            "numbers": _count_preserved(numeric, transcript_words),
            "dates": _count_preserved(months, transcript_words),
            "currency": _count_preserved(currency, transcript_words),
        }
    elif category == "acronyms-quotations":
        acronyms = _acronyms(reference_text)
        quoted = _quoted_sequences(reference_text, locale)
        checks = {
            "acronyms": _count_preserved(acronyms, transcript_words),
            "quotations": {
                "expected": len(quoted),
                "matched": sum(
                    _contains_sequence(transcript_words, sequence) for sequence in quoted
                ),
                "missing": sum(
                    not _contains_sequence(transcript_words, sequence) for sequence in quoted
                ),
            },
        }

    warning_codes: list[str] = []
    if tail_matched != tail_size:
        warning_codes.append("tail-coverage-incomplete")
    if repeated["extra_occurrences"]:
        warning_codes.append("unexpected-repetition")
    for name, result in checks.items():
        if result["missing"]:
            warning_codes.append(f"{name}-not-preserved")

    return {
        "status": "warning" if warning_codes else "completed",
        "normalization": f"unicode-nfkc-casefold-{locale}-v1",
        "reference_words": len(reference_words),
        "transcript_words": len(transcript_words),
        "word_errors": word_edits,
        "wer": round(word_edits / max(1, len(reference_words)), 6),
        "reference_characters": len(reference_chars),
        "character_errors": character_edits,
        "cer": round(character_edits / max(1, len(reference_chars)), 6),
        "missing_tail": {
            "evaluated_words": tail_size,
            "matched_words": tail_matched,
            "coverage": round(tail_matched / max(1, tail_size), 6),
        },
        "repeated_spans": repeated,
        "fixture_checks": checks,
        "warning_codes": warning_codes,
        "transcript_sha256": hashlib.sha256(transcript.encode("utf-8")).hexdigest(),
        "transcript_recorded": False,
    }


def verify_asr_model(config: dict[str, Any], model_dir: Path) -> dict[str, str]:
    verified: dict[str, str] = {}
    for artifact in config["model"]["artifacts"]:
        path = model_dir / artifact["path"]
        if not path.is_file():
            raise AsrUnavailable("missing-verified-model")
        algorithm = artifact["checksum_algorithm"]
        actual = file_digest(path, algorithm)
        if actual != artifact["checksum"]:
            raise AsrUnavailable("model-checksum-mismatch")
        verified[artifact["path"]] = actual
    return verified


class FasterWhisperAdapter:
    def __init__(self, config: dict[str, Any], model_dir: Path):
        self.config = config
        self.model_dir = model_dir
        self.verified_artifacts = verify_asr_model(config, model_dir)
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise AsrUnavailable("missing-dependency") from error
        runtime = config["runtime"]
        try:
            self.model = WhisperModel(
                str(model_dir),
                device=runtime["device"],
                compute_type=runtime["compute_type"],
                local_files_only=True,
            )
        except Exception as error:
            raise AsrUnavailable("model-load-failed") from error

    def evaluate(self, audio_path: Path, fixture: dict[str, Any]) -> dict[str, Any]:
        locale = fixture["locale"]
        language = self.config["locale_mapping"].get(locale)
        if language is None:
            raise AsrUnavailable("unsupported-locale")
        inspect_wav(audio_path)
        runtime = self.config["runtime"]
        try:
            segments, info = self.model.transcribe(
                str(audio_path),
                language=language,
                beam_size=runtime["beam_size"],
                temperature=runtime["temperature"],
                condition_on_previous_text=runtime["condition_on_previous_text"],
                vad_filter=False,
            )
            transcript = " ".join(
                segment.text.strip() for segment in segments if segment.text.strip()
            )
        except Exception as error:
            raise AsrFailed("local-asr-transcription-failed") from error
        evidence = semantic_metrics(fixture["text"], transcript, locale, fixture["category"])
        evidence.update(
            {
                "adapter": "faster-whisper",
                "model": self.config["model"]["name"],
                "model_revision": self.config["model"]["revision"],
                "requested_language": language,
                "detected_language": getattr(info, "language", None),
                "detected_language_probability": round(
                    float(getattr(info, "language_probability", 0.0)), 6
                ),
            }
        )
        return evidence
