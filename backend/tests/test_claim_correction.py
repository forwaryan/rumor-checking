from __future__ import annotations

import json

from backend.app.models.schemas import ClaimResult, EvidenceItem
from backend.app.services import model_health
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
    monkeypatch.setattr(model_health.httpx, "post", boom)

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


def test_chinese_numeral_parser():
    from backend.app.services.claim_correction import _parse_chinese_numeral as p
    assert p("三千") == 3000
    assert p("两千") == 2000
    assert p("五万") == 50000
    assert p("两千零五十") == 2050
    assert p("一百二十三") == 123
    assert p("一亿") == 100_000_000
    assert p("三千五百") == 3500
    assert p("九十九") == 99
    assert p("abc") is None  # non-numeric run
    # Multi-level compounds must not double-count the leading section.
    assert p("一千万") == 10_000_000
    assert p("两亿三千万") == 230_000_000
    assert p("一万零一") == 10_001
    # Bare unit chars with NO digit word are NOT numbers (万元/十字路口/千米).
    assert p("万") is None
    assert p("十") is None
    assert p("千") is None


def test_bare_scale_units_do_not_pollute_grounding_pool():
    # Regression: a bare "万" in "万元营收" must not inject 10000 into the pool, or a
    # hallucinated "10000人" would ground against unrelated revenue wording.
    from backend.app.services.claim_correction import (
        _extract_numbers_from_text as f,
        _actual_is_grounded as g,
    )
    assert f("公司万元营收增长") == set() or "10000" not in f("公司万元营收增长")
    assert f("万达广场十字路口") == set() or not (f("万达广场十字路口") & {"10000", "10"})
    assert g("实际10000人", f("公司万元营收增长")) is False


def test_number_extraction_bridges_chinese_and_arabic():
    from backend.app.services.claim_correction import _extract_numbers_from_text as f
    # Chinese numerals must yield their Arabic value so the two scripts cross-ground.
    assert "3000" in f("员工突破三千人")
    assert "2000" in f("约两千名员工")
    assert "50000" in f("投资五万元")
    # Arabic still works, with the Chinese-unit-stripped variant.
    assert "2000" in f("突破2000人")


def test_correction_grounds_across_number_scripts():
    # The C fix: evidence written in Chinese numerals ("两千") must ground an Arabic
    # correction ("2000"). Before the fix the pool had no digit form of 两千, so the
    # correct figure was discarded as a hallucination.
    claims = [_claim("某公司招了5000人。", "refuted", evidence=[_ev("官方通报：实际入职约两千人")])]
    resp = json.dumps([
        {"correction": {"original": "5000人", "actual": "实际约2000人", "source": "官方通报"}}
    ])
    out = annotate_claim_corrections(
        claims, all_evidence_titles=["官方通报：实际入职约两千人"],
        completion_fn=lambda system, user: resp,
    )
    assert out[0].correction is not None
    assert "2000" in out[0].correction["actual"]
