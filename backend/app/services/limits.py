"""In-memory abuse and cost limits for the public demo. One instance, so memory is enough: a
restart forgets the counters, and the global daily caps bound the damage either way."""

import time
from collections import deque

from fastapi import FastAPI

from app.errors import AppError

MINUTE = 60
HOUR = 3600
DAY = 86400
MAX_KEYS = 20000


class Limits:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}

    def _window(self, key: str, seconds: int, now: float) -> deque[float]:
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= MAX_KEYS:
                self._evict(now)
            hits = self._hits[key] = deque()
        while hits and now - hits[0] >= seconds:
            hits.popleft()
        return hits

    def _evict(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] >= DAY]:
            del self._hits[key]
        if len(self._hits) >= MAX_KEYS:
            self._hits.clear()  # Under a flood the per-key view is lost; global caps still hold.

    def count(self, key: str, seconds: int) -> int:
        return len(self._window(key, seconds, time.monotonic()))

    def allow(self, key: str, limit: int, seconds: int) -> bool:
        """Record one hit unless the window is full."""
        now = time.monotonic()
        hits = self._window(key, seconds, now)
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    def full(self, key: str, limit: int, seconds: int) -> bool:
        return self.count(key, seconds) >= limit

    def record(self, key: str, seconds: int) -> None:
        now = time.monotonic()
        self._window(key, seconds, now).append(now)


def limits_for(app: FastAPI) -> Limits:
    limits = getattr(app.state, "limits", None)
    if limits is None:
        limits = app.state.limits = Limits()
    return limits


def rate_limited(message: str, retry_after: int) -> AppError:
    return AppError(429, "RATE_LIMITED", message, {"retry_after_seconds": retry_after})
