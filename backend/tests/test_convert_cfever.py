from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from backend.scripts.convert_cfever import (
    DEFAULT_RECORDED_AT,
    SOURCE_REVISION,
    build_snapshot,
    convert_dataset,
    evidence_sets,
    select_balanced,
    to_simplified,
    wikipedia_url,
)


def _record(case_id: int, label: str, evidence: list, claim: str | None = None) -> dict:
    return {
        "id": case_id,
        "label": label,
        "claim": claim or f"claim-{case_id}",
        "evidence": evidence,
        "domain": "測試",
    }


def test_select_balanced_avoids_label_order_bias():
    records = [
        _record(1, "supports", [[[1, 1, "甲", 0]]]),
        _record(2, "supports", [[[1, 1, "乙", 0]]]),
        _record(3, "refutes", [[[1, 1, "丙", 0]]]),
        _record(4, "refutes", [[[1, 1, "丁", 0]]]),
        _record(5, "NOT ENOUGH INFO", []),
        _record(6, "NOT ENOUGH INFO", []),
    ]

    selected = select_balanced(records, per_label=1)

    assert len(selected) == 3
    assert {record["label"] for record in selected} == {"supports", "refutes", "NOT ENOUGH INFO"}
    assert selected == select_balanced(list(reversed(records)), per_label=1)


def test_evidence_sets_accepts_standard_and_nei_shapes():
    standard = _record(1, "supports", [[[7, 8, "頁面", 2]], [[7, 9, "頁面", 3]]])
    hugging_face = _record(
        2,
        "refutes",
        [[{"annotation_id": 7, "evidence_id": 8, "page_title": "頁面", "sentence_id": 4}]],
    )
    nei = _record(3, "NOT ENOUGH INFO", [[7, None, None, None]])

    assert evidence_sets(standard) == [[("頁面", 2)], [("頁面", 3)]]
    assert evidence_sets(hugging_face) == [[("頁面", 4)]]
    assert evidence_sets(nei) == []


def test_build_snapshot_maps_label_and_groups_page_lines():
    record = _record(
        42,
        "refutes",
        [[[1, 1, "測試_頁面", 2], [1, 1, "測試_頁面", 1]]],
        claim="錯誤說法",
    )

    snapshot = build_snapshot(
        record,
        {"測試_頁面": {1: "第一句。", 2: "第二句。"}},
        split="dev",
        recorded_at="2024-02-27T00:00:00Z",
    )

    assert snapshot["case_id"] == "cfever_dev_42"
    assert snapshot["expected_claims"][0]["verdict"] == "refuted"
    assert snapshot["metadata"]["provenance"] == "public_dataset"
    assert snapshot["metadata"]["dataset_license"] == "Apache-2.0"
    assert snapshot["retrieval_results"] == [
        {
            "result_id": "wiki_1",
            "title": "测试 页面",
            "url": wikipedia_url("測試_頁面"),
            "source_name": "中文维基百科",
            "published_at": "",
            "snippet": "第一句。 第二句。",
            "source_tier": "B",
        }
    ]
    assert snapshot["metadata"]["text_variant"] == "zh-Hans"


def test_to_simplified_uses_opencc_t2s():
    assert to_simplified("繁體中文與資料庫") == "繁体中文与资料库"


@pytest.mark.parametrize("verified_claims", [False, True])
def test_convert_dataset_writes_balanced_replay_and_manifest(tmp_path: Path, monkeypatch, verified_claims):
    claims_path = tmp_path / "dev.jsonl"
    records = [
        _record(1, "supports", [[[1, 1, "甲", 0]]]),
        _record(2, "refutes", [[[1, 2, "乙", 1]]]),
        _record(3, "NOT ENOUGH INFO", [[1, None, None, None]]),
    ]
    claims_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    if verified_claims:
        monkeypatch.setattr(
            "backend.scripts.convert_cfever.PINNED_DEV_SHA256",
            hashlib.sha256(claims_path.read_bytes()).hexdigest(),
        )
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    wiki_pages = [
        {"id": "甲", "text": "", "lines": "0\t甲證據"},
        {"id": "乙", "text": "", "lines": "0\t其他\n1\t乙證據"},
    ]
    (wiki_dir / "wiki-001.jsonl").write_text(
        "".join(json.dumps(page, ensure_ascii=False) + "\n" for page in wiki_pages),
        encoding="utf-8",
    )
    output_dir = tmp_path / "snapshots"

    manifest = convert_dataset(
        claims_path=claims_path,
        wiki_dir=wiki_dir,
        output_dir=output_dir,
        per_label=1,
        split="dev",
        recorded_at="2024-02-27T00:00:00Z",
        allow_unverified=not verified_claims,
    )

    assert manifest["snapshot_count"] == 3
    assert manifest["label_counts"] == {
        "supported": 1,
        "refuted": 1,
        "insufficient": 1,
    }
    assert len(list(output_dir.glob("*.json"))) == 3
    nei = json.loads((output_dir / "cfever_dev_3.json").read_text(encoding="utf-8"))
    assert nei["retrieval_results"] == []
    assert nei["expected_claims"][0]["evidence"] == []
    assert (tmp_path / "snapshots.manifest.json").exists()
    assert manifest["source_revision"] == (SOURCE_REVISION if verified_claims else None)
    assert manifest["claims_sha256"] == hashlib.sha256(claims_path.read_bytes()).hexdigest()
    assert manifest["sampling"]["selected_source_ids"] == [1, 2, 3]
    assert manifest["sampling"]["topic_counts"] == {"测试": 3}
    assert nei["metadata"]["review_status"] == "quarantined"
    assert nei["metadata"]["source_revision"] is None
    assert nei["metadata"]["claims_source_revision"] == (SOURCE_REVISION if verified_claims else None)
    assert nei["metadata"]["provenance"] == "unverified_import"
    assert nei["expected_claims"][0]["evaluation"]["score_confidence"] is False


def test_build_snapshot_rejects_missing_evidence_line():
    record = _record(9, "supports", [[[1, 1, "頁面", 8]]])

    with pytest.raises(ValueError, match="missing line 8"):
        build_snapshot(
            record,
            {"頁面": {0: "只有第零行"}},
            split="dev",
            recorded_at="2024-02-27T00:00:00Z",
        )


@pytest.mark.parametrize("pointer", [
    [1, 1, "頁面", -1], [1, 1, "頁面", True], [1, 1, "頁面", "0"],
    [1, 1, " ", 0], [1, 1, None, 0], [1, 1, "頁面"],
    {"page_title": "頁面"}, "bad-pointer",
])
def test_evidence_sets_rejects_partial_malformed_groups(pointer):
    record = _record(10, "supports", [[[1, 1, "頁面", 0], pointer]])
    with pytest.raises(ValueError, match="invalid evidence pointer"):
        evidence_sets(record)


@pytest.mark.parametrize("evidence", [None, {}, [None], [[]], []])
def test_evidence_sets_rejects_invalid_or_empty_support(evidence):
    with pytest.raises(ValueError):
        evidence_sets(_record(10, "supports", evidence))


def test_snapshot_preserves_alternative_groups_and_all_original_locations():
    record = _record(10, "supports", [
        [[1, 1, "甲", 0], [1, 2, "乙", 1]],
        [[2, 3, "丙", 2]],
        [[3, 4, "甲", 3]],
    ])
    snapshot = build_snapshot(
        record, {"甲": {0: "甲零", 3: "甲三"}, "乙": {1: "乙一"}, "丙": {2: "丙二"}},
        split="dev", recorded_at="2024-02-27T00:00:00Z",
    )
    expected = snapshot["expected_claims"][0]
    assert [[item["url"] for item in group] for group in expected["evidence_sets"]] == [
        sorted([wikipedia_url("甲"), wikipedia_url("乙")]),
        [wikipedia_url("丙")], [wikipedia_url("甲")],
    ]
    assert len(expected["evidence"]) == 1
    assert len(snapshot["retrieval_results"]) == 3
    assert next(item for item in snapshot["retrieval_results"] if item["title"] == "甲")["snippet"] == "甲零 甲三"
    assert snapshot["metadata"]["original_evidence_sets"][2] == [
        {"page_title": "甲", "sentence_id": 3},
    ]
    assert snapshot["metadata"]["original_claim"] == record["claim"]


def test_snapshot_rejects_missing_reference_even_in_alternative_group():
    record = _record(10, "supports", [[[1, 1, "甲", 0]], [[2, 2, "乙", 0]]])
    with pytest.raises(ValueError, match="missing page"):
        build_snapshot(record, {"甲": {0: "完整"}}, split="dev", recorded_at="2024-02-27T00:00:00Z")


def test_sampling_spreads_domains_and_is_input_order_independent():
    records = [
        dict(_record(index, label, [[1, None, None, None]] if label == "NOT ENOUGH INFO"
                     else [[[1, 1, "頁面", 0]]]), domain=f"topic-{index % 3}")
        for offset, label in enumerate(["supports", "refutes", "NOT ENOUGH INFO"])
        for index in range(offset * 30, (offset + 1) * 30)
    ]
    selected = select_balanced(records, per_label=3, seed=17)
    assert selected == select_balanced(records[::2] + records[1::2], per_label=3, seed=17)
    assert selected != select_balanced(records, per_label=3, seed=18)
    for label in ["supports", "refutes", "NOT ENOUGH INFO"]:
        assert len({record["domain"] for record in selected if record["label"] == label}) == 3


@pytest.mark.parametrize("case_id", [True, -1, "../outside", None])
def test_snapshot_rejects_invalid_case_id(case_id):
    with pytest.raises(ValueError, match="invalid CFEVER id"):
        build_snapshot(_record(case_id, "NOT ENOUGH INFO", []), {}, split="dev", recorded_at=DEFAULT_RECORDED_AT)


@pytest.mark.parametrize("split", ["../outside", "/tmp/output", "", "dev/extra", ".."])
def test_snapshot_rejects_unsafe_split(split):
    with pytest.raises(ValueError, match="invalid split"):
        build_snapshot(_record(1, "NOT ENOUGH INFO", []), {}, split=split, recorded_at=DEFAULT_RECORDED_AT)


def test_snapshot_rejects_empty_claim():
    record = _record(1, "NOT ENOUGH INFO", [])
    record["claim"] = "  "
    with pytest.raises(ValueError, match="empty or invalid claim"):
        build_snapshot(record, {}, split="dev", recorded_at=DEFAULT_RECORDED_AT)


def test_converter_rejects_duplicate_ids_before_writing(tmp_path):
    claims_path = tmp_path / "claims.jsonl"
    records = [_record(1, "NOT ENOUGH INFO", []), _record(1, "supports", [[[1, 1, "甲", 0]]])]
    claims_path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    output_dir = tmp_path / "output"
    with pytest.raises(ValueError, match="duplicate CFEVER id"):
        convert_dataset(claims_path=claims_path, wiki_dir=tmp_path, output_dir=output_dir,
                        per_label=1, split="dev", recorded_at=DEFAULT_RECORDED_AT, allow_unverified=True)
    assert not output_dir.exists()


def test_converter_requires_explicit_unverified_mode(tmp_path):
    claims_path = tmp_path / "claims.jsonl"
    claims_path.write_text("{}\n", encoding="utf-8")
    output_dir = tmp_path / "output"
    with pytest.raises(ValueError, match="does not match pinned dev"):
        convert_dataset(claims_path=claims_path, wiki_dir=tmp_path, output_dir=output_dir,
                        per_label=1, split="dev", recorded_at=DEFAULT_RECORDED_AT)
    assert not output_dir.exists()


def test_converter_rejects_missing_alternative_before_writing(tmp_path):
    claims_path = tmp_path / "claims.jsonl"
    records = [
        _record(1, "supports", [[[1, 1, "甲", 0]], [[2, 2, "乙", 8]]]),
        _record(2, "refutes", [[[1, 1, "甲", 0]]]),
        _record(3, "NOT ENOUGH INFO", []),
    ]
    claims_path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    wiki_pages = [{"id": "甲", "lines": "0\t甲零"}, {"id": "乙", "lines": "0\t乙零"}]
    (tmp_path / "wiki-001.jsonl").write_text("\n".join(json.dumps(page) for page in wiki_pages), encoding="utf-8")
    output_dir = tmp_path / "output"
    with pytest.raises(ValueError, match="missing line 8"):
        convert_dataset(claims_path=claims_path, wiki_dir=tmp_path, output_dir=output_dir,
                        per_label=1, split="dev", recorded_at=DEFAULT_RECORDED_AT, allow_unverified=True)
    assert not output_dir.exists()


@pytest.mark.parametrize("manifest_name", ["output", "output/cfever_dev_1.json", "output/cfever_dev_1.json/manifest.json"])
def test_converter_rejects_manifest_collision_before_writing(tmp_path, manifest_name):
    claims_path = tmp_path / "claims.jsonl"
    records = [
        _record(1, "supports", [[[1, 1, "甲", 0]]]),
        _record(2, "refutes", [[[1, 1, "甲", 0]]]),
        _record(3, "NOT ENOUGH INFO", []),
    ]
    claims_path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    (tmp_path / "wiki-001.jsonl").write_text(json.dumps({"id": "甲", "lines": "0\t甲零"}), encoding="utf-8")
    output_dir = tmp_path / "output"
    with pytest.raises(ValueError, match="manifest path collides"):
        convert_dataset(claims_path=claims_path, wiki_dir=tmp_path, output_dir=output_dir,
                        per_label=1, split="dev", recorded_at=DEFAULT_RECORDED_AT, allow_unverified=True,
                        manifest_path=tmp_path / manifest_name)
    assert not output_dir.exists()


@pytest.fixture
def conversion_inputs(tmp_path):
    claims_path = tmp_path / "claims.jsonl"
    records = [
        _record(1, "supports", [[[1, 1, "甲", 0]]]),
        _record(2, "refutes", [[[1, 1, "甲", 0]]]),
        _record(3, "NOT ENOUGH INFO", []),
    ]
    claims_path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    (tmp_path / "wiki-001.jsonl").write_text(json.dumps({"id": "甲", "lines": "0\t甲零"}), encoding="utf-8")
    return {
        "claims_path": claims_path, "wiki_dir": tmp_path, "output_dir": tmp_path / "output",
        "per_label": 1, "split": "dev", "recorded_at": DEFAULT_RECORDED_AT, "allow_unverified": True,
    }


@pytest.mark.parametrize("recorded_at", ["not-a-date", "2026-02-30T00:00:00Z", "", None])
def test_build_snapshot_rejects_invalid_recorded_at(recorded_at):
    with pytest.raises(ValueError, match="recorded_at"):
        build_snapshot(_record(1, "NOT ENOUGH INFO", []), {}, split="dev", recorded_at=recorded_at)


@pytest.mark.parametrize("recorded_at", ["not-a-date", "2026-02-30T00:00:00Z", "", None])
def test_converter_rejects_invalid_recorded_at_without_any_output(conversion_inputs, recorded_at):
    conversion_inputs["recorded_at"] = recorded_at
    with pytest.raises(ValueError, match="recorded_at"):
        convert_dataset(**conversion_inputs)
    assert not conversion_inputs["output_dir"].exists()
    assert not (conversion_inputs["output_dir"].parent / "output.manifest.json").exists()


@pytest.mark.parametrize("relative_path", ["manifest.json", "nested/manifest.json"])
def test_converter_rejects_manifest_inside_output_before_writing(conversion_inputs, relative_path):
    manifest_path = conversion_inputs["output_dir"] / relative_path
    with pytest.raises(ValueError, match="manifest must be outside"):
        convert_dataset(**conversion_inputs, manifest_path=manifest_path)
    assert not conversion_inputs["output_dir"].exists()


def test_converter_validates_every_final_snapshot_before_writing(conversion_inputs, monkeypatch):
    def malformed_snapshot(record, pages, **kwargs):
        snapshot = build_snapshot(record, pages, **kwargs)
        if record["id"] == 2:
            snapshot["retrieval_results"][0]["source_tier"] = "invalid"
        return snapshot

    monkeypatch.setattr("backend.scripts.convert_cfever.build_snapshot", malformed_snapshot)
    with pytest.raises(ValueError, match="source_tier"):
        convert_dataset(**conversion_inputs)
    assert not conversion_inputs["output_dir"].exists()
    assert not (conversion_inputs["output_dir"].parent / "output.manifest.json").exists()
