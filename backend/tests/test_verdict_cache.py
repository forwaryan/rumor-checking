"""Tests for cross-session verdict cache (P2)."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

from backend.app.agent.verdict_cache import (
    CachedVerdict,
    DiskVerdictCache,
    MemoryVerdictCache,
    fingerprint,
)


# --- Fingerprinting ---


def test_fingerprint_deterministic():
    fp1 = fingerprint("拼多多在雄安买楼")
    fp2 = fingerprint("拼多多在雄安买楼")
    assert fp1 == fp2
    assert len(fp1) == 32


def test_fingerprint_ignores_whitespace():
    fp1 = fingerprint("拼多多 在 雄安 买楼")
    fp2 = fingerprint("拼多多在雄安买楼")
    assert fp1 == fp2


def test_fingerprint_ignores_punctuation():
    fp1 = fingerprint("拼多多在雄安买楼？")
    fp2 = fingerprint("拼多多在雄安买楼")
    assert fp1 == fp2


def test_fingerprint_case_insensitive():
    fp1 = fingerprint("PDD Xiong An")
    fp2 = fingerprint("pdd xiong an")
    assert fp1 == fp2


def test_fingerprint_different_for_different_text():
    fp1 = fingerprint("拼多多在雄安买楼")
    fp2 = fingerprint("京东在北京买楼")
    assert fp1 != fp2


# --- CachedVerdict ---


def _make_verdict(*, ttl: float = 3600, cached_at: float | None = None) -> CachedVerdict:
    return CachedVerdict(
        fingerprint="abc123",
        raw_input="test rumor",
        verdict="insufficient",
        confidence="medium",
        claim_results_json='[{"claim": "test"}]',
        cached_at=cached_at or time.time(),
        ttl_seconds=ttl,
    )


def test_cached_verdict_fresh():
    v = _make_verdict(ttl=3600)
    assert v.is_fresh is True


def test_cached_verdict_stale():
    v = _make_verdict(ttl=1, cached_at=time.time() - 2)
    assert v.is_fresh is False


def test_cached_verdict_serialization():
    v = _make_verdict()
    d = v.to_dict()
    restored = CachedVerdict.from_dict(d)
    assert restored.fingerprint == v.fingerprint
    assert restored.verdict == v.verdict
    assert restored.cached_at == v.cached_at


# --- MemoryVerdictCache ---


def test_memory_cache_put_get():
    cache = MemoryVerdictCache()
    v = _make_verdict()
    cache.put(v)
    result = cache.get("abc123")
    assert result is not None
    assert result.verdict == "insufficient"


def test_memory_cache_miss():
    cache = MemoryVerdictCache()
    assert cache.get("nonexistent") is None


def test_memory_cache_stale_eviction():
    cache = MemoryVerdictCache()
    v = _make_verdict(ttl=0.001, cached_at=time.time() - 1)
    cache.put(v)
    # Should be evicted on get (stale)
    assert cache.get("abc123") is None


def test_memory_cache_invalidate():
    cache = MemoryVerdictCache()
    cache.put(_make_verdict())
    cache.invalidate("abc123")
    assert cache.get("abc123") is None


def test_memory_cache_max_entries():
    cache = MemoryVerdictCache(max_entries=3)
    for i in range(5):
        v = CachedVerdict(
            fingerprint=f"fp_{i}",
            raw_input=f"rumor {i}",
            verdict="insufficient",
            confidence="low",
            claim_results_json="[]",
            cached_at=time.time() + i * 0.001,  # Slightly different times
        )
        cache.put(v)
    assert cache.size <= 3


# --- DiskVerdictCache ---


def test_disk_cache_put_get():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = DiskVerdictCache(Path(tmpdir))
        v = _make_verdict()
        cache.put(v)
        result = cache.get("abc123")
        assert result is not None
        assert result.verdict == "insufficient"


def test_disk_cache_survives_new_instance():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache1 = DiskVerdictCache(Path(tmpdir))
        cache1.put(_make_verdict())

        cache2 = DiskVerdictCache(Path(tmpdir))
        result = cache2.get("abc123")
        assert result is not None


def test_disk_cache_stale():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = DiskVerdictCache(Path(tmpdir))
        v = _make_verdict(ttl=0.001, cached_at=time.time() - 1)
        cache.put(v)
        assert cache.get("abc123") is None


def test_disk_cache_invalidate():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = DiskVerdictCache(Path(tmpdir))
        cache.put(_make_verdict())
        cache.invalidate("abc123")
        assert cache.get("abc123") is None


def test_disk_cache_corrupted_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = DiskVerdictCache(Path(tmpdir))
        # Write garbage
        (Path(tmpdir) / "bad_fp.json").write_text("not json", encoding="utf-8")
        assert cache.get("bad_fp") is None
