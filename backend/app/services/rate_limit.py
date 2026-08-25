"""In-process sliding-window rate limiter.

Each AI query can call a paid provider, so the endpoint is capped per user.
This is deliberately dependency-free and per-process: with a single API
instance it is sufficient, and it fails open rather than blocking the app.
Move to Redis if the API is ever scaled to multiple workers.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, *, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """Record a hit. Returns (allowed, seconds_until_retry)."""
        if self.limit <= 0:
            return True, 0

        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.popleft()

            if len(hits) >= self.limit:
                retry_after = max(1, int(hits[0] + self.window - now) + 1)
                return False, retry_after

            hits.append(now)

            # Keep the table from growing without bound on long-lived processes.
            if len(self._hits) > 10_000:
                for stale_key in [k for k, v in self._hits.items() if not v]:
                    del self._hits[stale_key]

            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
