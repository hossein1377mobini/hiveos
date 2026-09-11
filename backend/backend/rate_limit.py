"""Minimal in-process sliding-window rate limiter (US-001/US-002 security).

Single uvicorn worker on staging (ADR-023 topology), so an in-memory counter
is sufficient for v0.1; a shared store arrives with horizontal scaling.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from backend.api_errors import ApiError
from backend.config import get_settings


class SlidingWindowLimiter:
    """Allow at most max_events per window_seconds for each key."""

    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            window = self._events[key]
            while window and now - window[0] > self.window_seconds:
                window.popleft()
            if len(window) >= self.max_events:
                return False
            window.append(now)
            return True

    def reset(self) -> None:
        """Drop all counters (used by the test suite between tests)."""
        with self._lock:
            self._events.clear()


def client_key(request: Request) -> str:
    """NB-1 (final review): key the limiter on the real client, not the proxy.

    Behind staging nginx every request arrives from the proxy address, so
    keying on request.client collapsed all users into one counter. When the
    direct peer is a configured trusted proxy (settings.trusted_proxies), the
    leftmost X-Forwarded-For entry (nginx appends the original client) is the
    rate-limit key; direct callers keep their socket address.
    """
    peer = request.client.host if request.client else "unknown"
    if get_settings().trust_proxy_xff(peer):
        xff = request.headers.get("x-forwarded-for", "")
        candidate = xff.split(",")[0].strip()
        if candidate:
            return candidate
    return peer


def rate_limit_dependency(limiter: SlidingWindowLimiter):
    """Build a FastAPI dependency enforcing limiter on the caller's IP."""

    async def _enforce(request: Request) -> None:
        if not limiter.allow(client_key(request)):
            raise ApiError(429, "RATE_LIMITED", "Too many requests; try again shortly.")

    return _enforce
