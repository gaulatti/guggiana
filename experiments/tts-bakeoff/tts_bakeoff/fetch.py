from __future__ import annotations

import os
import shutil
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .catalog import file_digest


class FetchError(RuntimeError):
    """A pinned artifact could not be acquired and verified."""


def fetch_engine(engine: str, config: dict[str, Any], model_dir: Path) -> list[Path]:
    if engine == "piper":
        return fetch_piper(config["engines"]["piper"], model_dir / "piper")
    if engine == "chatterbox":
        return fetch_chatterbox(config["engines"]["chatterbox"], model_dir / "chatterbox")
    raise FetchError("Polly is a managed service and has no downloadable model artifact")


def fetch_piper(engine: dict[str, Any], destination: Path) -> list[Path]:
    repository = engine["model_repository"]
    base = f"{repository['url']}/resolve/{repository['revision']}"
    fetched: list[Path] = []
    for mapping in engine["locale_mapping"].values():
        model_path = Path(mapping["path"])
        card_path = model_path.parent / "MODEL_CARD"
        artifacts = (
            (model_path, "sha256", mapping["model_sha256"]),
            (Path(f"{model_path}.json"), "md5", mapping["config_md5"]),
            (card_path, "md5", mapping["model_card_md5"]),
        )
        for remote_path, algorithm, expected in artifacts:
            local = destination / remote_path
            _download_verified(f"{base}/{remote_path.as_posix()}", local, algorithm, expected)
            fetched.append(local)
    return fetched


def fetch_chatterbox(engine: dict[str, Any], destination: Path) -> list[Path]:
    fetched: list[Path] = []
    benchmark_models = {mapping["model"] for mapping in engine["locale_mapping"].values()}
    for model_name in sorted(benchmark_models):
        model = engine["models"][model_name]
        model_destination = destination / model_name
        for artifact in model["required_files"]:
            remote = (
                "https://huggingface.co/"
                f"{artifact['repository']}/resolve/{artifact['revision']}/"
                f"{urllib.parse.quote(artifact['source_file'])}"
            )
            local = model_destination / artifact["local_file"]
            _download_verified(remote, local, "sha256", artifact["sha256"])
            fetched.append(local)
    return fetched


def _download_verified(
    url: str, destination: Path, algorithm: str, expected: str
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and file_digest(destination, algorithm) == expected:
        return
    partial = destination.with_suffix(destination.suffix + ".part")
    partial.unlink(missing_ok=True)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "guggiana-tts-bakeoff/1"})
        with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
        actual = file_digest(partial, algorithm)
        if actual != expected:
            raise FetchError(
                f"checksum mismatch for {destination.name}: expected {expected}, got {actual}"
            )
        os.replace(partial, destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
