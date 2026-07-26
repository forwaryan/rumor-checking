"""Tests for per-API rate limiting (P3)."""
from __future__ import annotations

import threading
import time

from backend.app.agent.rate_limiter import RateLimiter, TokenBucket


# --- TokenBucket ---


def test_bucket_initial_capacity():
    bucket = TokenBucket(rate=10.0, capacity=5.0)
    assert bucket.available == 5.0


def test_bucket_acquire_consumes_tokens():
    bucket = TokenBucket(rate=10.0, capacity=5.0)
    assert bucket.try_acquire(3.0) is True
    assert bucket.available < 5.0


def test_bucket_acquire_fails_when_empty():
    bucket = TokenBucket(rate=1.0, capacity=2.0)
    assert bucket.try_acquire(2.0) is True
    assert bucket.try_acquire(1.0) is False


def test_bucket_refills_over_time():
    bucket = TokenBucket(rate=100.0, capacity=10.0)
    bucket.try_acquire(10.0)  # Empty it
    time.sleep(0.05)  # Wait for refill (100/s × 0.05s = 5 tokens)
    assert bucket.available >= 4.0  # Allow for timing imprecision


def test_bucket_blocking_acquire():
    bucket = TokenBucket(rate=100.0, capacity=1.0)
    bucket.try_acquire(1.0)  # Empty
    # Should block briefly then succeed after refill
    start = time.monotonic()
    result = bucket.acquire(1.0, timeout=1.0)
    elapsed = time.monotonic() - start
    assert result is True
    assert elapsed < 0.5  # Should refill quickly at 100/s


def test_bucket_acquire_timeout():
    bucket = TokenBucket(rate=0.1, capacity=1.0)
    bucket.try_acquire(1.0)  # Empty
    # Rate is very slow, should timeout
    result = bucket.acquire(1.0, timeout=0.05)
    assert result is False


def test_bucket_never_exceeds_capacity():
    bucket = TokenBucket(rate=1000.0, capacity=5.0)
    time.sleep(0.01)
    assert bucket.available <= 5.0


def test_bucket_thread_safety():
    bucket = TokenBucket(rate=1000.0, capacity=100.0)
    results = []

    def worker():
        for _ in range(10):
            results.append(bucket.try_acquire(1.0))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All 50 should succeed (capacity=100)
    assert sum(results) == 50


# --- RateLimiter ---


def test_limiter_default_bucket():
    limiter = RateLimiter(default_rate=100.0, default_capacity=10.0)
    assert limiter.try_acquire("api/completions") is True


def test_limiter_configure_endpoint():
    limiter = RateLimiter()
    limiter.configure("slow_api", rate=1.0, capacity=2.0)
    assert limiter.try_acquire("slow_api") is True
    assert limiter.try_acquire("slow_api") is True
    assert limiter.try_acquire("slow_api") is False  # Exhausted


def test_limiter_separate_buckets():
    limiter = RateLimiter(default_rate=100.0, default_capacity=2.0)
    limiter.try_acquire("endpoint_a")
    limiter.try_acquire("endpoint_a")
    # endpoint_a is exhausted, but endpoint_b has its own bucket
    assert limiter.try_acquire("endpoint_a") is False
    assert limiter.try_acquire("endpoint_b") is True


def test_limiter_blocking_acquire():
    limiter = RateLimiter(default_rate=100.0, default_capacity=1.0)
    limiter.try_acquire("api")  # Exhaust
    result = limiter.acquire("api", timeout=0.5)
    assert result is True


def test_limiter_endpoints_list():
    limiter = RateLimiter()
    limiter.configure("api1", rate=1.0, capacity=1.0)
    limiter.configure("api2", rate=1.0, capacity=1.0)
    assert set(limiter.endpoints) == {"api1", "api2"}


def test_limiter_high_concurrency():
    limiter = RateLimiter(default_rate=50.0, default_capacity=20.0)
    limiter.configure("gateway", rate=50.0, capacity=20.0)
    acquired = []

    def worker():
        for _ in range(5):
            acquired.append(limiter.try_acquire("gateway"))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 20 capacity, 40 attempts → at most 20 should succeed
    success_count = sum(acquired)
    assert success_count <= 20
    assert success_count >= 15  # Most should get through given initial capacity
