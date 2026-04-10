"""Async circuit breaker for external dependencies."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


class CircuitBreakerOpen(RuntimeError):
    """Raised when the breaker is open."""


@dataclass(slots=True)
class CircuitState:
    opened_until: datetime | None = None
    failures: deque[bool] | None = None


class AsyncCircuitBreaker:
    """Simple rolling-window async circuit breaker."""

    def __init__(
        self,
        *,
        failure_rate_threshold: float = 0.5,
        time_window_seconds: int = 60,
        open_duration_seconds: int = 30,
        minimum_calls: int = 3,
    ) -> None:
        self.failure_rate_threshold = failure_rate_threshold
        self.time_window_seconds = time_window_seconds
        self.open_duration_seconds = open_duration_seconds
        self.minimum_calls = minimum_calls
        self._states: dict[str, deque[tuple[datetime, bool]]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def call(self, target: str, func: Any, *args: Any, **kwargs: Any) -> Any:
        lock = self._locks.setdefault(target, asyncio.Lock())
        async with lock:
            self._prune(target)
            if self._is_open(target):
                raise CircuitBreakerOpen(f"circuit open for {target}")
        try:
            result = await func(*args, **kwargs)
        except Exception:
            async with lock:
                self._record(target, False)
            raise
        async with lock:
            self._record(target, True)
        return result

    def _record(self, target: str, success: bool) -> None:
        now = datetime.now(timezone.utc)
        entries = self._states.setdefault(target, deque())
        entries.append((now, success))
        self._prune(target)

    def _prune(self, target: str) -> None:
        entries = self._states.setdefault(target, deque())
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.time_window_seconds)
        while entries and entries[0][0] < cutoff:
            entries.popleft()

    def _is_open(self, target: str) -> bool:
        entries = self._states.get(target, deque())
        if len(entries) < self.minimum_calls:
            return False
        failures = sum(1 for _, success in entries if not success)
        failure_rate = failures / max(1, len(entries))
        if failure_rate < self.failure_rate_threshold:
            return False
        last_failure_time = max(timestamp for timestamp, success in entries if not success)
        return datetime.now(timezone.utc) < last_failure_time + timedelta(seconds=self.open_duration_seconds)
