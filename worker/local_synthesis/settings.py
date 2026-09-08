from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SettingsError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    bind_address: str
    port: int
    state_directory: Path
    token_file: Path
    manifest_path: Path
    model_root: Path
    enabled_providers: list[str]
    provider_options: dict[str, dict[str, object]]
    concurrency: int
    queue_capacity: int
    timeout_seconds: float
    max_attempts: int
    max_artifact_bytes: int
    max_retained_jobs: int


def _resolve(base: Path, raw: Any, field: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise SettingsError(f"{field} must be a non-empty path")
    path = Path(raw)
    return (path if path.is_absolute() else base / path).resolve()


def load_settings(path: Path) -> Settings:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise SettingsError("worker configuration is absent or invalid") from error
    expected = {
        "schemaVersion",
        "bindAddress",
        "port",
        "stateDirectory",
        "tokenFile",
        "modelManifest",
        "modelRoot",
        "enabledProviders",
        "providerOptions",
        "concurrency",
        "queueCapacity",
        "timeoutSeconds",
        "maxAttempts",
        "maxArtifactBytes",
        "maxRetainedJobs",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != expected
        or payload.get("schemaVersion") != 1
    ):
        raise SettingsError("worker configuration fields or schema are invalid")
    if payload["bindAddress"] not in {"127.0.0.1", "::1"}:
        raise SettingsError("the standalone worker must bind to a loopback address")
    if (
        isinstance(payload["port"], bool)
        or not isinstance(payload["port"], int)
        or not 1 <= payload["port"] <= 65535
    ):
        raise SettingsError("port is invalid")
    enabled = payload["enabledProviders"]
    if (
        not isinstance(enabled, list)
        or not enabled
        or any(name not in {"piper", "chatterbox"} for name in enabled)
    ):
        raise SettingsError("enable at least one named candidate provider explicitly")
    if len(enabled) != len(set(enabled)):
        raise SettingsError("enabled providers must be unique")
    options = payload["providerOptions"]
    if not isinstance(options, dict) or any(
        name not in {"piper", "chatterbox"} or not isinstance(value, dict)
        for name, value in options.items()
    ):
        raise SettingsError("providerOptions is invalid")
    integers = (
        "concurrency",
        "queueCapacity",
        "maxAttempts",
        "maxArtifactBytes",
        "maxRetainedJobs",
    )
    if any(
        isinstance(payload[name], bool) or not isinstance(payload[name], int)
        for name in integers
    ) or (
        isinstance(payload["timeoutSeconds"], bool)
        or not isinstance(payload["timeoutSeconds"], (int, float))
    ):
        raise SettingsError("worker bounds must be numeric")
    base = path.resolve().parent
    return Settings(
        bind_address=payload["bindAddress"],
        port=payload["port"],
        state_directory=_resolve(base, payload["stateDirectory"], "stateDirectory"),
        token_file=_resolve(base, payload["tokenFile"], "tokenFile"),
        manifest_path=_resolve(base, payload["modelManifest"], "modelManifest"),
        model_root=_resolve(base, payload["modelRoot"], "modelRoot"),
        enabled_providers=list(enabled),
        provider_options={name: dict(value) for name, value in options.items()},
        concurrency=int(payload["concurrency"]),
        queue_capacity=int(payload["queueCapacity"]),
        timeout_seconds=float(payload["timeoutSeconds"]),
        max_attempts=int(payload["maxAttempts"]),
        max_artifact_bytes=int(payload["maxArtifactBytes"]),
        max_retained_jobs=int(payload["maxRetainedJobs"]),
    )


def read_token(path: Path) -> str:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        token = path.read_text().strip()
    except OSError as error:
        raise SettingsError("API token file is unavailable") from error
    if mode & 0o077:
        raise SettingsError("API token file must not be readable by group or others")
    if len(token) < 32:
        raise SettingsError("API token must contain at least 32 characters")
    return token
