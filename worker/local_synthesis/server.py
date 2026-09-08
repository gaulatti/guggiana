from __future__ import annotations

import argparse
import hmac
import json
import logging
import re
import signal
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .adapters import build_candidate_adapters
from .contract import ContractError
from .service import LocalSynthesisWorker, QueueOverloaded
from .settings import load_settings, read_token

MAX_REQUEST_BYTES = 65_536
JOB_PATH = re.compile(r"^/v1/jobs/([0-9a-f-]{36})(/artifact)?$")
LOGGER = logging.getLogger("guggiana.local_synthesis.server")


def handler_factory(
    worker: LocalSynthesisWorker, token: str
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "GuggianaLocalSynthesis/1"
        sys_version = ""

        def log_message(self, _format: str, *_args: object) -> None:
            # Default access logs contain job IDs and are intentionally disabled.
            return

        def _authorized(self) -> bool:
            supplied = self.headers.get("Authorization", "")
            return supplied.startswith("Bearer ") and hmac.compare_digest(
                supplied[7:], token
            )

        def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _require_auth(self) -> bool:
            if self._authorized():
                return True
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return False

        def do_GET(self) -> None:
            if self.path == "/healthz":
                self._json(
                    HTTPStatus.OK
                    if worker.health()
                    else HTTPStatus.SERVICE_UNAVAILABLE,
                    {"status": "ok" if worker.health() else "failed"},
                )
                return
            if self.path == "/readyz":
                self._json(
                    HTTPStatus.OK if worker.ready() else HTTPStatus.SERVICE_UNAVAILABLE,
                    {"status": "ready" if worker.ready() else "not_ready"},
                )
                return
            if not self._require_auth():
                return
            if self.path == "/metrics":
                body = worker.prometheus_metrics().encode()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            match = JOB_PATH.fullmatch(self.path)
            if not match:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            job_id, artifact_suffix = match.groups()
            if artifact_suffix:
                artifact = worker.artifact(job_id)
                if not artifact or not artifact.is_file():
                    self._json(HTTPStatus.NOT_FOUND, {"error": "artifact_unavailable"})
                    return
                body = artifact.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            status = worker.status(job_id)
            if status is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            else:
                self._json(HTTPStatus.OK, status)

        def do_POST(self) -> None:
            if self.path != "/v1/jobs":
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            if not self._require_auth():
                return
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_REQUEST_BYTES:
                self._json(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "request_too_large"}
                )
                return
            try:
                payload = json.loads(self.rfile.read(length))
                status = worker.submit_payload(payload)
            except json.JSONDecodeError:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                return
            except ContractError as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": error.code})
                return
            except QueueOverloaded:
                self._json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "queue_overloaded"})
                return
            self._json(HTTPStatus.ACCEPTED, status)

        def do_DELETE(self) -> None:
            if not self._require_auth():
                return
            match = JOB_PATH.fullmatch(self.path)
            if not match or match.group(2):
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            status = worker.cancel(match.group(1))
            if status is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            else:
                self._json(HTTPStatus.ACCEPTED, status)

    return Handler


def build_worker(config_path: Path) -> tuple[LocalSynthesisWorker, str, str, int]:
    settings = load_settings(config_path)
    token = read_token(settings.token_file)
    adapters = build_candidate_adapters(
        settings.manifest_path,
        settings.model_root,
        settings.enabled_providers,
        settings.provider_options,
    )
    worker = LocalSynthesisWorker(
        settings.state_directory,
        adapters,
        concurrency=settings.concurrency,
        queue_capacity=settings.queue_capacity,
        timeout_seconds=settings.timeout_seconds,
        max_attempts=settings.max_attempts,
        max_artifact_bytes=settings.max_artifact_bytes,
        max_retained_jobs=settings.max_retained_jobs,
    )
    return worker, token, settings.bind_address, settings.port


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the standalone local synthesis worker"
    )
    parser.add_argument("--config", type=Path, required=True)
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        worker, token, bind_address, port = build_worker(arguments.config)
        worker.start()
    except (RuntimeError, ValueError) as error:
        LOGGER.error(
            json.dumps(
                {"event": "startup_failed", "reason": type(error).__name__},
                separators=(",", ":"),
            )
        )
        return 1
    server = ThreadingHTTPServer((bind_address, port), handler_factory(worker, token))

    def stop(_signal: int, _frame: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        worker.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
