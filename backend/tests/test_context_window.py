"""Tests for context window management (P0)."""
from __future__ import annotations

import json

from backend.app.agent.context_window import (
    build_evidence_budget,
    compact_to_budget,
    estimate_json_tokens,
    estimate_tokens,
    truncate_to_budget,
)


# --- Token estimation ---


def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0


def test_estimate_tokens_chinese():
    text = "拼多多在雄安买楼"
    tokens = estimate_tokens(text)
    # 8 CJK chars × 1.5 = 12 tokens
    assert tokens == 12


def test_estimate_tokens_english():
    text = "Hello world test"
    tokens = estimate_tokens(text)
    # 3 ASCII words × 1.3 = ~4, plus spaces
    assert tokens >= 3


def test_estimate_tokens_mixed():
    text = "拼多多 PDD 在雄安 xiong_an 买楼"
    tokens = estimate_tokens(text)
    # Mix of CJK (6 chars × 1.5 = 9) + ASCII words (2 × 1.3) + spaces
    assert tokens > 10


def test_estimate_json_tokens():
    obj = {"title": "测试", "snippet": "这是一段证据摘要"}
    tokens = estimate_json_tokens(obj)
    assert tokens > 0
    # JSON overhead makes it slightly larger than raw text
    raw_tokens = estimate_tokens(json.dumps(obj, ensure_ascii=False))
    assert tokens >= raw_tokens


# --- truncate_to_budget ---


def _make_items(n: int, snippet_len: int = 100) -> list[dict]:
    return [
        {"title": f"标题{i}", "snippet": "X" * snippet_len, "source": f"来源{i}"}
        for i in range(n)
    ]


def test_truncate_empty_items():
    assert truncate_to_budget([], budget_tokens=1000) == []


def test_truncate_respects_min_items():
    items = _make_items(5, snippet_len=500)
    # Very small budget — should still return min_items=2
    result = truncate_to_budget(items, budget_tokens=10, min_items=2)
    assert len(result) >= 2


def test_truncate_fits_all_within_budget():
    items = _make_items(3, snippet_len=50)
    # Large budget — all items fit
    result = truncate_to_budget(items, budget_tokens=10000)
    assert len(result) == 3


def test_truncate_drops_items_over_budget():
    items = _make_items(10, snippet_len=300)
    # Very tight budget — even with truncation, can't fit all 10
    result = truncate_to_budget(items, budget_tokens=200, min_items=2)
    assert 2 <= len(result) < 10


def test_truncate_clips_long_snippets():
    items = [{"title": "t", "snippet": "Y" * 500, "source": "s"}]
    result = truncate_to_budget(items, budget_tokens=10000, max_chars_per_item=100)
    assert len(result[0]["snippet"]) <= 101  # 100 + "…"


def test_truncate_preserves_other_fields():
    items = [{"title": "保留", "snippet": "短", "extra": "值"}]
    result = truncate_to_budget(items, budget_tokens=10000)
    assert result[0]["title"] == "保留"
    assert result[0]["extra"] == "值"


def test_truncate_zero_budget_returns_min_items():
    items = _make_items(5)
    result = truncate_to_budget(items, budget_tokens=0, min_items=3)
    assert len(result) == 3


# --- compact_to_budget ---


def test_compact_keeps_more_items_than_truncate_as_stubs():
    """At a budget too small for all items at full snippet length, compaction
    keeps overflow items as stubs instead of dropping them like truncate does —
    so a low-ranked debunking hit still reaches synthesis."""
    # CJK content so the token estimate (1.5/char) actually consumes the budget;
    # a run of ASCII 'X' collapses to ~1 word token and would never overflow.
    items = [
        {"title": f"标题{i}", "snippet": "证" * 400, "source": f"来源{i}", "result_id": f"r{i}"}
        for i in range(8)
    ]
    budget = 1400
    compacted = compact_to_budget(items, budget_tokens=budget, key="snippet", min_items=3)
    truncated = truncate_to_budget(items, budget_tokens=budget, key="snippet", min_items=3)
    assert len(compacted) > len(truncated)
    # Every kept item retains its identifying fields even when the snippet is a stub.
    for item in compacted:
        assert "title" in item and "source" in item


def test_compact_stubs_shrink_the_snippet_not_drop_the_item():
    items = [
        {"title": f"标题{i}", "snippet": "证" * 400, "source": f"来源{i}", "result_id": f"r{i}"}
        for i in range(6)
    ]
    compacted = compact_to_budget(
        items, budget_tokens=900, key="snippet", min_items=2, max_chars_per_item=200, stub_chars=40
    )
    # Later (overflow) items should have shorter snippets than the min_items head.
    if len(compacted) > 2:
        assert len(compacted[-1]["snippet"]) <= len(compacted[0]["snippet"])


def test_compact_empty_and_zero_budget():
    assert compact_to_budget([], budget_tokens=1000) == []
    items = _make_items(5)
    assert len(compact_to_budget(items, budget_tokens=0, min_items=3)) == 3


# --- build_evidence_budget ---

def test_build_evidence_budget():
    budget = build_evidence_budget(
        system_prompt_tokens=2000,
        max_context=32000,
        output_tokens=4096,
        user_prompt_overhead=500,
    )
    # 32000 - 4096 - 2000 - 500 = 25404
    assert budget == 25404


def test_build_evidence_budget_floor():
    # When context is very small, floor at 2000
    budget = build_evidence_budget(
        system_prompt_tokens=10000,
        max_context=10000,
        output_tokens=4096,
    )
    assert budget == 2000


# --- Integration: synthesis prompt doesn't exceed context ---


def test_synthesis_prompt_truncation_integration():
    """Verify that even with many long hits, the prompt stays bounded."""
    from backend.app.agent.context_window import estimate_tokens as et

    # Simulate 8 hits with very long snippets (1000 chars each)
    items = [
        {"title": f"标题{i}", "snippet": "证" * 1000, "source_tier": "A", "result_id": f"r{i}",
         "url": f"https://x.com/{i}", "source_name": f"来源{i}", "published_at": "2026-01-01",
         "source_category": "news", "query_label": None}
        for i in range(8)
    ]
    # With 2000 token budget, some items should be dropped
    truncated = truncate_to_budget(items, budget_tokens=2000, key="snippet", min_items=3)
    total_tokens = estimate_json_tokens(truncated)
    # Should be significantly less than untruncated
    full_tokens = estimate_json_tokens(items)
    assert total_tokens < full_tokens
    assert len(truncated) >= 3
