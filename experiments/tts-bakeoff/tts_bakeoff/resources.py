from __future__ import annotations

import resource
import threading
import time
from contextlib import contextmanager
from typing import Iterator


class PeakMemory:
    def __init__(self) -> None:
        self.baseline_bytes = self._rss_bytes()
        self.peak_bytes = self.baseline_bytes
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def _rss_bytes() -> int:
        try:
            import psutil

            return int(psutil.Process().memory_info().rss)
        except ImportError:
            value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # macOS returns bytes; Linux returns KiB.
            return int(value if value > 10_000_000 else value * 1024)

    def _sample(self) -> None:
        while not self._stop.is_set():
            self.peak_bytes = max(self.peak_bytes, self._rss_bytes())
            self._stop.wait(0.01)

    def __enter__(self) -> "PeakMemory":
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        self.peak_bytes = max(self.peak_bytes, self._rss_bytes())

    @property
    def peak_mib(self) -> float:
        return round(self.peak_bytes / (1024 * 1024), 3)

    @property
    def incremental_peak_mib(self) -> float:
        return round(max(0, self.peak_bytes - self.baseline_bytes) / (1024 * 1024), 3)


@contextmanager
def measure_peak_memory() -> Iterator[PeakMemory]:
    measurement = PeakMemory()
    with measurement:
        yield measurement
