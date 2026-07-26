from __future__ import annotations

import json

from backend.app.models.schemas import ClaimResult, EvidenceItem
from backend.app.services import claim_correction
from backend.app.services.claim_correction import annotate_claim_corrections


def _ev(title: str) -> EvidenceItem:
    return EvidenceItem(
        title=title, url=f"https://example.com/{abs(hash(title)) % 999}",
        source_name="src", published_at="2026-07-01", snippet=title,
        relevance_reason="r", source_tier="B",
    )


def _claim(claim: str, verdict: str, *, evidence=None) -> ClaimResult:
    return ClaimResult(
        claim=claim, claim_type="fact", verdict=verdict, confidence="medium",
        evidence=evidence or [], notes="n",
    )


def test_correction_grounds_against_pool_titles_when_claim_has_no_bound_evidence():
    # A refuted claim with NO bound evidence: the correct figure lives only in the
    # retrieval pool (all_evidence_titles). Before the fix, grounding scanned only
    # cr.evidence (empty) and discarded the correction as a hallucination.
    claims = [_claim("拼多多在雄安招了6000名员工。", "refuted", evidence=[])]
    pool = ["拼多多雄安公司最新进展：员工规模突破2000人，专项招聘全速推进"]
    resp = json.dumps([
        {"correction": {"original": "招了6000名员工", "actual": "员工规模突破2000人", "source": "拼多多雄安公司最新进展"}}
    ])

    out = annotate_claim_corrections(
        claims, all_evidence_titles=pool, completion_fn=lambda system, user: resp
    )
    assert out[0].correction is not None
    assert out[0].correction["actual"] == "员工规模突破2000人"


def test_correction_still_discards_ungrounded_number():
    # Monotonic anti-hallucination: an actual figure absent from BOTH bound evidence
    # and the pool must still be dropped, even with the pool now in the grounding set.
    claims = [_claim("某地新增1万个岗位。", "refuted", evidence=[])]
    pool = ["官方通报：新增岗位约3000个"]
    resp = json.dumps([
        {"correction": {"original": "1万个岗位", "actual": "实际新增9999个岗位", "source": "官方通报"}}
    ])

    out = annotate_claim_corrections(
        claims, all_evidence_titles=pool, completion_fn=lambda system, user: resp
    )
    assert out[0].correction is None  # 9999 grounded nowhere -> discarded


def test_completion_fn_is_used_and_bypasses_httpx(monkeypatch):
    # When a completion_fn is injected, the bare httpx POST path must never fire
    # (that path picks a fast model that times out on the real gateway).
    def boom(*args, **kwargs):
        raise AssertionError("httpx.post must not be called when completion_fn is provided")
    monkeypatch.setattr(claim_correction.httpx, "post", boom)

    calls = {"n": 0}

    def fake_complete(system: str, user: str) -> str:
        calls["n"] += 1
        return json.dumps([
            {"correction": {"original": "5栋楼", "actual": "1栋办公楼", "source": "挂牌公告"}}
        ])

    claims = [_claim("拼多多买了5栋楼。", "refuted", evidence=[_ev("拼多多雄安办公楼正式挂牌，1栋职场")])]
    out = annotate_claim_corrections(claims, completion_fn=fake_complete)

    assert calls["n"] == 1
    assert out[0].correction is not None
    assert out[0].correction["actual"] == "1栋办公楼"


def test_correction_no_op_when_completion_fn_returns_empty():
    # A failed/empty LLM layer must degrade to unchanged results, not crash.
    claims = [_claim("某事。", "refuted", evidence=[_ev("标题2000")])]
    out = annotate_claim_corrections(claims, completion_fn=lambda system, user: "")
    assert out[0].correction is None
