from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contract import LOCALES


class ManifestError(RuntimeError):
    """An enabled adapter cannot prove its immutable runtime inputs."""


HEX_DIGEST = re.compile(r"^[a-f0-9]+$")


def _is_digest(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and bool(HEX_DIGEST.fullmatch(value))
    )


@dataclass(frozen=True)
class VerifiedProvider:
    name: str
    model: str
    model_revision: str
    runtime_revision: str
    runtime_license: str
    manifest_sha256: str
    details: dict[str, Any]


def file_digest(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        parsed = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise ManifestError("model manifest is absent or invalid") from error
    if not isinstance(parsed, dict) or parsed.get("schemaVersion") != 1:
        raise ManifestError("model manifest schema is unsupported")
    return parsed, hashlib.sha256(raw).hexdigest()


def _inside(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise ManifestError("artifact path must be relative")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise ManifestError(
            "artifact path escapes the configured model root"
        ) from error
    return candidate


def verify_provider(
    name: str,
    manifest: dict[str, Any],
    manifest_sha256: str,
    model_root: Path,
    *,
    verify_installed_distribution: bool = True,
) -> VerifiedProvider:
    providers = manifest.get("providers")
    if not isinstance(providers, dict) or name not in providers:
        raise ManifestError(f"enabled provider {name} is not pinned in the manifest")
    details = providers[name]
    if not isinstance(details, dict):
        raise ManifestError(f"provider {name} manifest is invalid")
    required_strings = ("model", "modelRevision", "runtimeRevision", "runtimeLicense")
    if any(
        not isinstance(details.get(field), str) or not details[field]
        for field in required_strings
    ):
        raise ManifestError(
            f"provider {name} lacks model, revision, or license provenance"
        )
    if not _is_digest(details["modelRevision"], 40) or not _is_digest(
        details["runtimeRevision"], 40
    ):
        raise ManifestError(f"provider {name} revisions must be immutable commits")
    if (
        not isinstance(details.get("voiceProvenance"), str)
        or not details["voiceProvenance"]
    ):
        raise ManifestError(f"provider {name} lacks voice provenance")
    locales = details.get("locales")
    if not isinstance(locales, dict) or set(locales) != set(LOCALES):
        raise ManifestError(f"provider {name} must pin every product locale")
    if any(
        not isinstance(value, dict) or not value.get("datasetLicense")
        for value in locales.values()
    ):
        raise ManifestError(f"provider {name} lacks per-locale license evidence")
    dependency = details.get("dependency")
    if not isinstance(dependency, dict):
        raise ManifestError(f"provider {name} lacks a pinned dependency")
    distribution = dependency.get("distribution")
    version = dependency.get("version")
    wheel_sha256 = dependency.get("wheelSha256")
    if not all(
        isinstance(value, str) and value for value in (distribution, version)
    ) or not _is_digest(wheel_sha256, 64):
        raise ManifestError(
            f"provider {name} dependency is not version/checksum pinned"
        )
    if verify_installed_distribution:
        try:
            installed = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as error:
            raise ManifestError(
                f"provider {name} pinned dependency is not installed"
            ) from error
        if installed != version:
            raise ManifestError(
                f"provider {name} dependency version does not match its pin"
            )
        import_name = details.get("importName")
        if (
            not isinstance(import_name, str)
            or importlib.util.find_spec(import_name) is None
        ):
            raise ManifestError(f"provider {name} runtime module is unavailable")

    artifacts = details.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ManifestError(f"provider {name} has no pinned model artifacts")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ManifestError(f"provider {name} artifact entry is invalid")
        relative = artifact.get("path")
        algorithm = artifact.get("algorithm")
        checksum = artifact.get("checksum")
        if not all(
            isinstance(value, str) and value
            for value in (relative, algorithm, checksum)
        ):
            raise ManifestError(f"provider {name} artifact lacks path or checksum")
        try:
            hashlib.new(algorithm)
        except ValueError as error:
            raise ManifestError(
                f"provider {name} uses an unsupported checksum"
            ) from error
        expected_length = hashlib.new(algorithm).digest_size * 2
        if not _is_digest(checksum, expected_length):
            raise ManifestError(f"provider {name} artifact checksum is malformed")
        candidate = _inside(model_root / name, relative)
        if not candidate.is_file() or file_digest(candidate, algorithm) != checksum:
            raise ManifestError(
                f"provider {name} model manifest does not match local artifacts"
            )
    return VerifiedProvider(
        name=name,
        model=details["model"],
        model_revision=details["modelRevision"],
        runtime_revision=details["runtimeRevision"],
        runtime_license=details["runtimeLicense"],
        manifest_sha256=manifest_sha256,
        details=details,
    )
