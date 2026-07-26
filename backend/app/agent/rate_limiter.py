"""Per-API rate limiting — token bucket for gateway protection.

Implements a thread-safe token bucket rate limiter that gates LLM API calls.
Configurable per-endpoint limits prevent high-concurrency scenarios from
overwhelming the gateway.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class TokenBucket:
    """Thread-safe token bucket rate limiter.

    Args:
        rate: Tokens added per second (sustained throughput).
        capacity: Maximum burst size (bucket size).
    """

    rate: float
    capacity: float
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)

    def __post_init__(self):
        self._tokens = self.capacity
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

    def acquire(self, tokens: float = 1.0, *, timeout: float = 30.0) -> bool:
        """Try to consume tokens, blocking up to `timeout` seconds.

        Returns True if tokens were acquired, False if timed out.
        """
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
                # Compute wait inside the lock to avoid TOCTOU
                wait = (tokens - self._tokens) / self.rate if self.rate > 0 else timeout
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(wait, remaining, 0.05))

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Non-blocking attempt to consume tokens."""
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    @property
    def available(self) -> float:
        """Current available tokens (approximate, without refill)."""
        with self._lock:
            self._refill()
            return self._tokens


class RateLimiter:
    """Multi-endpoint rate limiter using per-key token buckets.

    Each endpoint (or API key, or model name) gets its own bucket.
    """

    def __init__(self, default_rate: float = 5.0, default_capacity: float = 10.0):
        self._default_rate = default_rate
        self._default_capacity = default_capacity
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def configure(self, key: str, *, rate: float, capacity: float) -> None:
        """Configure a specific endpoint's rate limit."""
        with self._lock:
            self._buckets[key] = TokenBucket(rate=rate, capacity=capacity)

    def acquire(self, key: str, *, tokens: float = 1.0, timeout: float = 30.0) -> bool:
        """Acquire tokens for the given endpoint. Blocks up to timeout."""
        bucket = self._get_or_create(key)
        return bucket.acquire(tokens, timeout=timeout)

    def try_acquire(self, key: str, *, tokens: float = 1.0) -> bool:
        """Non-blocking acquire for the given endpoint."""
        bucket = self._get_or_create(key)
        return bucket.try_acquire(tokens)

    def _get_or_create(self, key: str) -> TokenBucket:
        with self._lock:
            if key not in self._buckets:
                self._buckets[key] = TokenBucket(
                    rate=self._default_rate,
                    capacity=self._default_capacity,
                )
            return self._buckets[key]

    @property
    def endpoints(self) -> list[str]:
        """List of configured endpoints."""
        with self._lock:
            return list(self._buckets.keys())
