from __future__ import annotations

import json
import logging

EVENTS = {"job_accepted", "job_started", "job_retrying", "job_finished", "job_rejected"}
RESULTS = {
    "accepted",
    "running",
    "retrying",
    "succeeded",
    "failed",
    "cancelled",
    "rejected",
}
RETRY_CLASSES = {"none", "timeout", "provider_transient", "permanent", "exhausted"}


class EventLogger:
    """Structured logs with only controlled fields; never content or identifiers."""

    def __init__(self, providers: set[str], logger: logging.Logger | None = None):
        self.providers = providers
        self.logger = logger or logging.getLogger("guggiana.local_synthesis")

    def emit(
        self, event: str, provider: str, result: str, retry_class: str = "none"
    ) -> None:
        if (
            event not in EVENTS
            or provider not in self.providers
            or result not in RESULTS
            or retry_class not in RETRY_CLASSES
        ):
            raise ValueError("structured event contains an unbounded field")
        self.logger.info(
            json.dumps(
                {
                    "event": event,
                    "provider": provider,
                    "result": result,
                    "retryClass": retry_class,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
