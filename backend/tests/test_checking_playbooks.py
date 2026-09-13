import json
from datetime import date, timedelta

from backend.app.models.schemas import ClaimResult, Event, Report, ReportProvenance
from backend.app.services.checking_playbooks import record_checking_experience, select_checking_playbooks


def _playbook(**overrides):
    return {
        "id": "policy_check",
        "kind": "procedure",
        "status": "approved",
        "title": "Check policy dates",
        "match_terms": ["policy", "政策"],
        "instructions": ["Check the official publication and effective dates."],
        "source_url": "repo://backend/tests/test_claim_timeliness.py",
        "reviewed_at": date.today().isoformat(),
        **overrides,
    }


def _write(directory, filename, payload):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(json.dumps(payload), encoding="utf-8")


def test_only_matching_approved_procedures_are_loaded(tmp_path):
    _write(tmp_path, "approved.json", _playbook())
    _write(tmp_path, "draft.json", _playbook(id="draft_policy", status="draft"))
    _write(tmp_path, "conclusion.json", _playbook(id="old_verdict", verdict="supported"))
    _write(tmp_path, "experience.json", {"kind": "experience", "status": "draft"})
    selected = select_checking_playbooks("这条政策今天生效吗？", playbook_dir=tmp_path)
    assert [playbook["id"] for playbook in selected] == ["policy_check"]
    assert "match_terms" not in selected[0]
    assert "verdict" not in selected[0]
    assert select_checking_playbooks("a sports result", playbook_dir=tmp_path) == []
    assert select_checking_playbooks("policyholder", playbook_dir=tmp_path) == []


def test_expired_future_malformed_and_oversized_playbooks_are_ignored(tmp_path):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    _write(tmp_path, "expired.json", _playbook(reviewed_at=yesterday, expires_at=yesterday))
    _write(tmp_path, "future.json", _playbook(reviewed_at=tomorrow))
    _write(tmp_path, "oversized.json", {"content": "政策" * 24000})
    _write(tmp_path, "invalid_source.json", _playbook(source_url="https://user:password@example.com"))
    (tmp_path / "malformed.json").write_text("broken", encoding="utf-8")
    assert select_checking_playbooks("policy 政策", playbook_dir=tmp_path) == []


def test_symlinked_playbooks_are_not_loaded(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(_playbook()), encoding="utf-8")
    directory = tmp_path / "playbooks"
    directory.mkdir()
    (directory / "linked.json").symlink_to(source)
    assert select_checking_playbooks("policy", playbook_dir=directory) == []


def test_selection_is_ranked_bounded_and_deterministic(tmp_path):
    for index in range(5):
        _write(tmp_path, f"{index}.json", _playbook(id=f"policy_{index}"))
    _write(tmp_path, "best.json", _playbook(id="best", match_terms=["政策", "今天"]))
    selected = select_checking_playbooks("政策今天生效", playbook_dir=tmp_path, limit=20)
    assert [playbook["id"] for playbook in selected] == ["best", "policy_0", "policy_1"]
    assert select_checking_playbooks("政策", playbook_dir=tmp_path, limit=0) == []


def test_repository_playbooks_match_supported_cases():
    selected = select_checking_playbooks("网传今天发布最新补贴政策")
    assert {playbook["id"] for playbook in selected} == {"policy_scope", "stale_news", "source_independence"}


def _report():
    return Report(
        mode="safe_mode",
        event=Event(title="Private title", summary="Private summary", source_url="", source_name="", published_at="", keywords=[], mode="safe_mode"),
        final_summary="Private conclusion",
        claim_results=[ClaimResult(claim="Private claim", claim_type="fact", verdict="insufficient", confidence="low", notes="")],
        provenance=ReportProvenance(
            source_type="backend_mock", event_source="input_normalized", claim_source="rule",
            evidence_source="none", timeline_source="none", retrieval_provider="mock",
            retrieval_cache_status=None, provider_used=False, fallback_used=False, fallback_reasons=[],
        ),
    )


def test_experience_records_counts_without_raw_input_or_conclusions(tmp_path):
    run_id = "a" * 32
    record_checking_experience(run_id=run_id, raw_input="Private policy query", report=_report(), output_dir=tmp_path)
    path = tmp_path / f"experience-{run_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "draft"
    assert payload["claim_counts"]["insufficient"] == 1
    assert payload["playbook_ids"] == ["policy_scope"]
    assert "Private" not in path.read_text(encoding="utf-8")
    assert select_checking_playbooks("policy", playbook_dir=tmp_path) == []


def test_experience_storage_failure_does_not_break_analysis(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("occupied", encoding="utf-8")
    record_checking_experience(run_id="a" * 32, raw_input="policy", report=_report(), output_dir=blocked)
    record_checking_experience(run_id="../invalid", raw_input="policy", report=_report(), output_dir=tmp_path)
    assert not list(tmp_path.glob("experience-*.json"))
