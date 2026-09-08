from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contract import SynthesisRequest, parse_request

TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, state_directory: Path):
        self.state_directory = state_directory.resolve()
        self.artifact_directory = self.state_directory / "artifacts"
        self.state_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.artifact_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state_directory, 0o700)
        os.chmod(self.artifact_directory, 0o700)
        self.database = self.state_directory / "jobs.sqlite3"
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    locale TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    failure_code TEXT,
                    retry_class TEXT,
                    artifact_json TEXT,
                    artifact_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_state_created ON jobs(state, created_at);
                """
            )
        os.chmod(self.database, 0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def active_count(self) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM jobs WHERE state IN ('queued', 'running', 'retrying')"
            ).fetchone()
        return int(row["count"])

    def state_count(self, state: str) -> int:
        if state not in {
            "queued",
            "running",
            "retrying",
            "succeeded",
            "failed",
            "cancelled",
        }:
            raise ValueError("unknown job state")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM jobs WHERE state=?", (state,)
            ).fetchone()
        return int(row["count"])

    def create(self, job_id: str, request: SynthesisRequest) -> None:
        timestamp = _now()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO jobs(id, provider, locale, request_json, state, created_at, updated_at) VALUES (?, ?, ?, ?, 'queued', ?, ?)",
                (
                    job_id,
                    request.provider,
                    request.locale,
                    json.dumps(request.as_dict(), separators=(",", ":")),
                    timestamp,
                    timestamp,
                ),
            )

    def recover(self, max_attempts: int) -> list[str]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE jobs SET state='failed', failure_code='worker_restarted', retry_class='exhausted', updated_at=? "
                "WHERE state IN ('running', 'retrying') AND attempts >= ?",
                (_now(), max_attempts),
            )
            connection.execute(
                "UPDATE jobs SET state='queued', failure_code=NULL, retry_class=NULL, updated_at=? "
                "WHERE state IN ('running', 'retrying') AND attempts < ?",
                (_now(), max_attempts),
            )
            rows = connection.execute(
                "SELECT id FROM jobs WHERE state='queued' ORDER BY created_at"
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def claim(
        self, job_id: str, allowed_providers: set[str]
    ) -> tuple[SynthesisRequest, int] | None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if row is None or row["state"] != "queued":
                return None
            if row["cancel_requested"]:
                connection.execute(
                    "UPDATE jobs SET state='cancelled', failure_code='cancelled', retry_class=NULL, updated_at=? WHERE id=?",
                    (_now(), job_id),
                )
                return None
            attempts = int(row["attempts"]) + 1
            connection.execute(
                "UPDATE jobs SET state='running', attempts=?, updated_at=? WHERE id=?",
                (attempts, _now(), job_id),
            )
            request = parse_request(json.loads(row["request_json"]), allowed_providers)
        return request, attempts

    def finish(
        self, job_id: str, artifact: dict[str, object], artifact_path: Path
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE jobs SET state='succeeded', artifact_json=?, artifact_path=?, failure_code=NULL, retry_class=NULL, updated_at=? WHERE id=? AND state='running'",
                (
                    json.dumps(artifact, separators=(",", ":")),
                    str(artifact_path),
                    _now(),
                    job_id,
                ),
            )

    def fail(self, job_id: str, code: str, retry_class: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE jobs SET state='failed', failure_code=?, retry_class=?, updated_at=? WHERE id=? AND state='running'",
                (code, retry_class, _now(), job_id),
            )

    def retry(self, job_id: str, code: str, retry_class: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE jobs SET state='queued', failure_code=?, retry_class=?, updated_at=? WHERE id=? AND state='running'",
                (code, retry_class, _now(), job_id),
            )

    def cancel(self, job_id: str) -> str | None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if row is None:
                return None
            state = str(row["state"])
            if state == "queued":
                connection.execute(
                    "UPDATE jobs SET state='cancelled', cancel_requested=1, failure_code='cancelled', updated_at=? WHERE id=?",
                    (_now(), job_id),
                )
                return "cancelled"
            if state == "running":
                connection.execute(
                    "UPDATE jobs SET cancel_requested=1, updated_at=? WHERE id=?",
                    (_now(), job_id),
                )
                return "cancelling"
            return state

    def mark_cancelled(self, job_id: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE jobs SET state='cancelled', cancel_requested=1, failure_code='cancelled', retry_class=NULL, updated_at=? WHERE id=? AND state='running'",
                (_now(), job_id),
            )

    def cancel_requested(self, job_id: str) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
        return bool(row and row["cancel_requested"])

    def status(self, job_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        result: dict[str, Any] = {
            "id": row["id"],
            "provider": row["provider"],
            "locale": row["locale"],
            "state": row["state"],
            "attempts": row["attempts"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
        if row["failure_code"]:
            result["failure"] = {
                "code": row["failure_code"],
                "retryClass": row["retry_class"],
            }
        if row["artifact_json"]:
            result["artifact"] = json.loads(row["artifact_json"])
        return result

    def artifact_path(self, job_id: str) -> Path | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT artifact_path FROM jobs WHERE id=? AND state='succeeded'",
                (job_id,),
            ).fetchone()
        return Path(row["artifact_path"]) if row and row["artifact_path"] else None

    def prune_terminal(self, retain: int) -> int:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT id, artifact_path FROM jobs WHERE state IN ('succeeded', 'failed', 'cancelled') "
                "ORDER BY updated_at DESC LIMIT -1 OFFSET ?",
                (retain,),
            ).fetchall()
            for row in rows:
                raw_path = row["artifact_path"]
                if raw_path:
                    artifact = Path(raw_path).resolve()
                    try:
                        artifact.relative_to(self.artifact_directory)
                    except ValueError:
                        pass
                    else:
                        artifact.unlink(missing_ok=True)
                connection.execute("DELETE FROM jobs WHERE id=?", (row["id"],))
        return len(rows)

    def writable(self) -> bool:
        try:
            with self._connection() as connection:
                connection.execute("SELECT 1").fetchone()
            return os.access(self.state_directory, os.W_OK)
        except sqlite3.Error:
            return False
