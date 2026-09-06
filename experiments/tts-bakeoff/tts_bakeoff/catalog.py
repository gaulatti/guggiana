from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
REQUIRED_LOCALES = ("en-US", "es-US", "fr-FR", "de-DE", "pt-BR")
REQUIRED_CATEGORIES = (
    "headline-byline",
    "numbers-dates-currency",
    "acronyms-quotations",
    "long-form",
)


class CatalogError(ValueError):
    """The committed benchmark catalog is incomplete or contradictory."""


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_digest(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_and_validate_catalog(
    fixtures_path: Path | None = None, config_path: Path | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    fixtures = load_json(fixtures_path or ROOT / "fixtures.json")
    config = load_json(config_path or ROOT / "config" / "engines.json")
    validate_fixtures(fixtures)
    validate_config(config)
    return fixtures, config


def validate_fixtures(catalog: dict[str, Any]) -> None:
    if catalog.get("schema_version") != 1:
        raise CatalogError("fixture schema_version must be 1")
    if tuple(catalog.get("locales", ())) != REQUIRED_LOCALES:
        raise CatalogError("fixture locales must match the five required locales in order")

    fixtures = catalog.get("fixtures")
    if not isinstance(fixtures, list) or len(fixtures) != 20:
        raise CatalogError("fixtures must contain exactly 20 entries")

    ids: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for fixture in fixtures:
        fixture_id = fixture.get("id")
        locale = fixture.get("locale")
        category = fixture.get("category")
        text = fixture.get("text")
        if not isinstance(fixture_id, str) or not fixture_id:
            raise CatalogError("every fixture needs a non-empty id")
        if fixture_id in ids:
            raise CatalogError(f"duplicate fixture id: {fixture_id}")
        ids.add(fixture_id)
        if locale not in REQUIRED_LOCALES or category not in REQUIRED_CATEGORIES:
            raise CatalogError(f"invalid locale/category for {fixture_id}")
        if (locale, category) in pairs:
            raise CatalogError(f"duplicate locale/category fixture: {locale}/{category}")
        pairs.add((locale, category))
        if not isinstance(text, str) or len(text.split()) < 5:
            raise CatalogError(f"fixture text is missing or too short: {fixture_id}")
        if category == "long-form":
            target = fixture.get("target_duration_seconds", {})
            if target != {"min": 45, "max": 60}:
                raise CatalogError(f"long-form target must be 45-60 seconds: {fixture_id}")
            if not 95 <= len(text.split()) <= 155:
                raise CatalogError(f"long-form fixture must contain 95-155 words: {fixture_id}")

    expected = {(locale, category) for locale in REQUIRED_LOCALES for category in REQUIRED_CATEGORIES}
    if pairs != expected:
        raise CatalogError("fixtures must cover every required locale/category pair")


def validate_config(config: dict[str, Any]) -> None:
    if config.get("schema_version") != 1:
        raise CatalogError("engine schema_version must be 1")
    if tuple(config.get("required_locales", ())) != REQUIRED_LOCALES:
        raise CatalogError("engine locales must match the benchmark locales")
    engines = config.get("engines")
    if not isinstance(engines, dict) or set(engines) != {"chatterbox", "piper", "polly"}:
        raise CatalogError("config must define Chatterbox, Piper, and Polly")
    for engine_name, engine in engines.items():
        dependency = engine.get("dependency", {})
        source = engine.get("source", {})
        mapping = engine.get("locale_mapping", {})
        if not dependency.get("version") or not dependency.get("license"):
            raise CatalogError(f"{engine_name} dependency version/license is required")
        if not source.get("url") or not source.get("revision") or not source.get("license"):
            raise CatalogError(f"{engine_name} source provenance is incomplete")
        if set(mapping) != set(REQUIRED_LOCALES):
            raise CatalogError(f"{engine_name} must document every required locale")
        for locale, details in mapping.items():
            if not details.get("accent_evidence"):
                raise CatalogError(f"{engine_name}/{locale} lacks accent evidence")

    for locale, voice in engines["piper"]["locale_mapping"].items():
        if len(voice.get("model_md5", "")) != 32 or len(voice.get("config_md5", "")) != 32:
            raise CatalogError(f"piper/{locale} lacks model checksums")
        if len(voice.get("model_sha256", "")) != 64 or len(voice.get("model_card_md5", "")) != 32:
            raise CatalogError(f"piper/{locale} lacks strong model or model-card checksums")
        if not voice.get("dataset_license"):
            raise CatalogError(f"piper/{locale} lacks voice license provenance")

    chatterbox_models = engines["chatterbox"].get("models", {})
    if not chatterbox_models or any(len(model.get("sha256", "")) != 64 for model in chatterbox_models.values()):
        raise CatalogError("every Chatterbox model needs a SHA-256 checksum")
    for model_name, model in chatterbox_models.items():
        required_files = model.get("required_files", [])
        if not required_files or any(len(item.get("sha256", "")) != 64 for item in required_files):
            raise CatalogError(f"Chatterbox {model_name} has incomplete file SHA-256 data")
    es_gate = config.get("decision_gates", {}).get("es-US", "")
    if "selection is forbidden" not in es_gate:
        raise CatalogError("the es-US launch gate must explicitly prevent unsupported selection")


def host_metadata() -> dict[str, Any]:
    def sysctl(name: str) -> str | None:
        try:
            return subprocess.check_output(["sysctl", "-n", name], text=True).strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    memory_bytes = sysctl("hw.memsize")
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "model": sysctl("hw.model"),
        "chip": sysctl("machdep.cpu.brand_string"),
        "logical_cpu_count": int(sysctl("hw.logicalcpu") or 0) or None,
        "memory_bytes": int(memory_bytes) if memory_bytes and memory_bytes.isdigit() else None,
        "python": platform.python_version(),
    }
