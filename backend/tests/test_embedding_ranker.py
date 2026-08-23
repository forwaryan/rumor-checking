"""Tests for the semantic embedding reranker and its fallback wiring."""
from __future__ import annotations

import backend.app.services.embedding_ranker as embedding_ranker_module
from backend.app.core.config import get_settings
from backend.app.services import evidence_ranker
from backend.app.services.embedding_ranker import rank_by_embedding
from backend.app.services.evidence_ranker import rank_results
from backend.app.services.retrieval_models import SearchResult


def _hit(result_id: str, title: str, snippet: str, tier: str = "B", authority: float = 0.0) -> SearchResult:
    return SearchResult(
        case_id="real_search",
        query="q",
        result_id=result_id,
        title=title,
        url=f"https://example.com/{result_id}",
        source_name="example.com",
        published_at="2026-07-01",
        snippet=snippet,
        source_tier=tier,
        authority_score=authority,
    )


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class _FakeClient:
    """Stands in for the shared httpx client; returns canned vectors keyed by the
    order of the input texts. index 0 is the query, the rest are results."""

    def __init__(self, vectors_by_text):
        self._vectors_by_text = vectors_by_text
        self.calls = 0

    def post(self, url, headers=None, json=None, timeout=None):  # noqa: A002
        self.calls += 1
        inputs = json["input"]
        data = [
            {"index": i, "embedding": self._vectors_by_text[text]}
            for i, text in enumerate(inputs)
        ]
        return _FakeResponse({"data": data})


def _configure_rerank(monkeypatch):
    monkeypatch.setenv("EVIDENCE_RERANK_ENABLED", "true")
    monkeypatch.setenv("EVIDENCE_EMBED_MODEL", "Qwen3-Embedding-8B-joybuilder")
    monkeypatch.setenv("EVIDENCE_EMBED_API_KEY", "test-embed-key")
    get_settings.cache_clear()


def test_semantic_rank_orders_by_cosine_not_tokens(monkeypatch):
    """The relevant hit shares NO characters with the query, so the token scorer
    would rank it low; semantic vectors put it first."""
    _configure_rerank(monkeypatch)
    query = "美团外卖骑手 新规"
    reference = f"{query} 美团骑手事件"
    on_topic = _hit("r1", "外卖平台调整配送员政策", "某平台宣布骑手接单规则变化")
    off_topic = _hit("r2", "美团点评发布财报", "公司季度营收数据公布")

    # Query vector points along axis 0; on_topic aligns with it, off_topic is orthogonal.
    vectors = {
        reference: [1.0, 0.0],
        f"{on_topic.title} {on_topic.snippet}": [0.9, 0.1],
        f"{off_topic.title} {off_topic.snippet}": [0.1, 0.9],
    }
    monkeypatch.setattr(
        embedding_ranker_module, "_get_shared_client", lambda: _FakeClient(vectors)
    )

    ranked = rank_by_embedding([off_topic, on_topic], query_text=query, event_title="美团骑手事件")
    assert [r.result_id for r in ranked] == ["r1", "r2"]


def test_authority_only_breaks_near_ties(monkeypatch):
    """With near-identical semantic scores, authority decides; with a real
    semantic gap, authority cannot override it."""
    _configure_rerank(monkeypatch)
    query = "测试"
    reference = query
    low_auth = _hit("low", "结果A", "内容A", authority=0.0)
    high_auth = _hit("high", "结果B", "内容B", authority=100.0)
    vectors = {
        reference: [1.0, 0.0],
        "结果A 内容A": [1.0, 0.0],   # identical to query
        "结果B 内容B": [1.0, 0.0],   # identical to query -> tie, authority wins
    }
    monkeypatch.setattr(
        embedding_ranker_module, "_get_shared_client", lambda: _FakeClient(vectors)
    )
    ranked = rank_by_embedding([low_auth, high_auth], query_text=query)
    assert ranked[0].result_id == "high"


def test_rank_results_uses_semantic_when_configured(monkeypatch):
    _configure_rerank(monkeypatch)
    query = "美团外卖骑手 新规"
    reference = query
    on_topic = _hit("r1", "外卖平台调整配送员政策", "骑手接单规则变化")
    off_topic = _hit("r2", "美团点评发布财报", "公司季度营收数据")
    vectors = {
        reference: [1.0, 0.0],
        f"{on_topic.title} {on_topic.snippet}": [0.95, 0.05],
        f"{off_topic.title} {off_topic.snippet}": [0.05, 0.95],
    }
    monkeypatch.setattr(
        embedding_ranker_module, "_get_shared_client", lambda: _FakeClient(vectors)
    )
    ranked = rank_results([off_topic, on_topic], query_text=query)
    assert ranked[0].result_id == "r1"


def test_rank_results_falls_back_when_embedding_raises(monkeypatch):
    """A failing embedding call must fall back to the token scorer, not raise."""
    _configure_rerank(monkeypatch)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(embedding_ranker_module, "rank_by_embedding", _boom)

    query = "樊振东 国家队"
    r1 = _hit("r1", "樊振东回归国家队", "樊振东重返国家队训练基地")
    r2 = _hit("r2", "今日新闻汇总", "各类体育新闻")
    ranked = rank_results([r2, r1], query_text=query, event_title="樊振东回归")
    # Token scorer still works: the char-overlapping hit ranks first.
    assert ranked[0].result_id == "r1"


def test_rank_results_uses_tokens_when_disabled(monkeypatch):
    """With rerank unconfigured, the embedding module is never called."""
    monkeypatch.delenv("EVIDENCE_RERANK_ENABLED", raising=False)
    get_settings.cache_clear()

    def _should_not_be_called(*_args, **_kwargs):
        raise AssertionError("embedding path must not run when disabled")

    monkeypatch.setattr(embedding_ranker_module, "rank_by_embedding", _should_not_be_called)
    query = "樊振东 国家队"
    r1 = _hit("r1", "樊振东回归国家队", "樊振东重返国家队训练基地")
    r2 = _hit("r2", "今日新闻汇总", "各类体育新闻")
    ranked = rank_results([r2, r1], query_text=query)
    assert ranked[0].result_id == "r1"
