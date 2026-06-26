from __future__ import annotations

import asyncio
import time
from collections import defaultdict


class TokenBucket:
    """Simple per-key token bucket. Tokens refill at `capacity` per `interval` seconds."""

    def __init__(self, capacity: int, interval: float = 60.0) -> None:
        self.capacity = capacity
        self.interval = interval
        self._tokens: dict[str, float] = defaultdict(lambda: float(capacity))
        self._last: dict[str, float] = defaultdict(time.monotonic)
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last[key]
            refill = elapsed * (self.capacity / self.interval)
            self._tokens[key] = min(self.capacity, self._tokens[key] + refill)
            self._last[key] = now
            if self._tokens[key] >= 1.0:
                self._tokens[key] -= 1.0
                return True
            return False

    def reset(self) -> None:
        self._tokens.clear()
        self._last.clear()
