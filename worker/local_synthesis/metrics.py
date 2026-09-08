from __future__ import annotations

import threading
from collections import Counter

RESULTS = {"accepted", "rejected", "succeeded", "failed", "cancelled"}
RETRY_CLASSES = {"timeout", "provider_transient"}


class Metrics:
    def __init__(self, providers: set[str]):
        self.providers = set(providers)
        self._jobs: Counter[tuple[str, str]] = Counter()
        self._retries: Counter[tuple[str, str]] = Counter()
        self._duration_sum: Counter[str] = Counter()
        self._duration_count: Counter[str] = Counter()
        self._lock = threading.Lock()

    def job(self, provider: str, result: str) -> None:
        if provider not in self.providers or result not in RESULTS:
            raise ValueError("metric label is not bounded")
        with self._lock:
            self._jobs[(provider, result)] += 1

    def retry(self, provider: str, retry_class: str) -> None:
        if provider not in self.providers or retry_class not in RETRY_CLASSES:
            raise ValueError("metric label is not bounded")
        with self._lock:
            self._retries[(provider, retry_class)] += 1

    def duration(self, provider: str, seconds: float) -> None:
        if provider not in self.providers:
            raise ValueError("metric label is not bounded")
        with self._lock:
            self._duration_sum[provider] += seconds
            self._duration_count[provider] += 1

    def render(self, queue_depth: int, active: int) -> str:
        with self._lock:
            lines = [
                "# HELP guggiana_local_synthesis_jobs_total Bounded worker job outcomes.",
                "# TYPE guggiana_local_synthesis_jobs_total counter",
            ]
            for (provider, result), value in sorted(self._jobs.items()):
                lines.append(
                    f'guggiana_local_synthesis_jobs_total{{provider="{provider}",result="{result}"}} {value}'
                )
            lines.extend(
                [
                    "# HELP guggiana_local_synthesis_retries_total Bounded worker retry classes.",
                    "# TYPE guggiana_local_synthesis_retries_total counter",
                ]
            )
            for (provider, retry_class), value in sorted(self._retries.items()):
                lines.append(
                    f'guggiana_local_synthesis_retries_total{{provider="{provider}",retry_class="{retry_class}"}} {value}'
                )
            lines.extend(
                [
                    "# HELP guggiana_local_synthesis_duration_seconds Synthesis execution time.",
                    "# TYPE guggiana_local_synthesis_duration_seconds summary",
                ]
            )
            for provider in sorted(self._duration_count):
                lines.append(
                    f'guggiana_local_synthesis_duration_seconds_sum{{provider="{provider}"}} {self._duration_sum[provider]:.6f}'
                )
                lines.append(
                    f'guggiana_local_synthesis_duration_seconds_count{{provider="{provider}"}} {self._duration_count[provider]}'
                )
        lines.extend(
            [
                "# HELP guggiana_local_synthesis_queue_depth Queued synthesis jobs.",
                "# TYPE guggiana_local_synthesis_queue_depth gauge",
                f"guggiana_local_synthesis_queue_depth {queue_depth}",
                "# HELP guggiana_local_synthesis_active_jobs Running synthesis jobs.",
                "# TYPE guggiana_local_synthesis_active_jobs gauge",
                f"guggiana_local_synthesis_active_jobs {active}",
            ]
        )
        return "\n".join(lines) + "\n"
