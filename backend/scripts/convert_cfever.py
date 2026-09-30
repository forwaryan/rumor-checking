"""Convert CFEVER claims and Wikipedia evidence into replay snapshots."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from opencc import OpenCC

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.services.eval_snapshot_validation import validate_snapshot  # noqa: E402

LABEL_MAP = {
    "supports": "supported",
    "refutes": "refuted",
    "NOT ENOUGH INFO": "insufficient",
}
LABEL_ORDER = tuple(LABEL_MAP)
DEFAULT_RECORDED_AT = "2024-02-27T00:00:00Z"
SOURCE_REPOSITORY = "https://huggingface.co/datasets/IKMLab-team/cfever"
SOURCE_REVISION = "1f8fa4bd290832d7ad3109f49e347eb5dc77b7ad"
PINNED_DEV_SHA256 = "c4bdeaebc90e8a21768919d212ff4a25cd8bf0edef00f64f0197066e7b034ddc"
DEFAULT_SEED = 20260913
UPSTREAM_REPOSITORY = "https://github.com/IKMLab/CFEVER-data"
SIMPLIFIER = OpenCC("t2s")


def _read_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            records.append(value)
    return records


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_record(record: dict) -> None:
    case_id = record.get("id")
    if isinstance(case_id, bool) or not isinstance(case_id, int) or case_id < 0:
        raise ValueError(f"invalid CFEVER id: {case_id!r}")
    if not isinstance(record.get("claim"), str) or not record["claim"].strip():
        raise ValueError(f"CFEVER case {case_id}: empty or invalid claim")
    if record.get("label") not in LABEL_MAP:
        raise ValueError(f"unsupported CFEVER label: {record.get('label')!r}")
    if not isinstance(record.get("domain", ""), str):
        raise ValueError(f"CFEVER case {case_id}: domain must be a string")


def _validate_split(split: str) -> None:
    if not isinstance(split, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", split):
        raise ValueError(f"invalid split: {split!r}")


def _validate_recorded_at(recorded_at: str) -> None:
    if not isinstance(recorded_at, str) or not recorded_at.strip():
        raise ValueError("recorded_at must be a nonempty ISO timestamp")
    try:
        datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"recorded_at must be an ISO timestamp: {recorded_at!r}") from exc


def topic_group(record: dict) -> str:
    domain = record.get("domain")
    if isinstance(domain, str) and domain.strip():
        return to_simplified(domain.strip())
    pages = sorted({page for group in evidence_sets(record) for page, _ in group})
    return pages[0] if pages else "unknown"


def select_balanced(
    records: list[dict], per_label: int, seed: int = DEFAULT_SEED
) -> list[dict]:
    if per_label < 1:
        raise ValueError("per_label must be at least 1")

    buckets: dict[str, list[dict]] = defaultdict(list)
    seen_ids: set[int] = set()
    for record in records:
        _validate_record(record)
        evidence_sets(record)
        if record["id"] in seen_ids:
            raise ValueError(f"duplicate CFEVER id: {record['id']}")
        seen_ids.add(record["id"])
        buckets[record["label"]].append(record)

    shortages = {
        label: per_label - len(buckets[label])
        for label in LABEL_ORDER
        if len(buckets[label]) < per_label
    }
    if shortages:
        details = ", ".join(f"{label}: missing {count}" for label, count in shortages.items())
        raise ValueError(f"not enough CFEVER records for a balanced subset ({details})")

    generator = random.Random(seed)
    selected = []
    for label in LABEL_ORDER:
        topics: dict[str, list[dict]] = defaultdict(list)
        for record in sorted(buckets[label], key=lambda item: item["id"]):
            topics[topic_group(record)].append(record)
        topic_names = sorted(topics)
        generator.shuffle(topic_names)
        for name in topic_names:
            generator.shuffle(topics[name])
        label_selected = []
        while len(label_selected) < per_label:
            for name in topic_names:
                if topics[name]:
                    label_selected.append(topics[name].pop())
                    if len(label_selected) == per_label:
                        break
        selected.extend(label_selected)
    return sorted(selected, key=lambda record: int(record["id"]))


def _is_reference(value: object) -> bool:
    if isinstance(value, dict):
        return "page_title" in value and "sentence_id" in value
    return (
        isinstance(value, list)
        and len(value) == 4
        and not isinstance(value[0], (list, dict))
    )


def _reference_location(value: object) -> tuple[object, object]:
    if isinstance(value, dict):
        return value.get("page_title"), value.get("sentence_id")
    if isinstance(value, list) and len(value) >= 4:
        return value[2], value[3]
    return None, None


def evidence_sets(record: dict) -> list[list[tuple[str, int]]]:
    raw_evidence = record.get("evidence")
    if not isinstance(raw_evidence, list):
        raise ValueError(f"CFEVER case {record.get('id')}: evidence must be a list")
    if raw_evidence and all(_is_reference(item) for item in raw_evidence):
        raw_sets = [raw_evidence]
    else:
        raw_sets = raw_evidence

    normalized: list[list[tuple[str, int]]] = []
    for raw_set in raw_sets:
        if not isinstance(raw_set, list) or not raw_set:
            raise ValueError(f"CFEVER case {record.get('id')}: invalid evidence set")
        references: list[tuple[str, int]] = []
        for raw_reference in raw_set:
            if not _is_reference(raw_reference):
                raise ValueError(f"CFEVER case {record.get('id')}: invalid evidence pointer")
            page_id, line_number = _reference_location(raw_reference)
            if record.get("label") == "NOT ENOUGH INFO" and page_id is None and line_number is None:
                continue
            if (
                not isinstance(page_id, str)
                or not page_id.strip()
                or isinstance(line_number, bool)
                or not isinstance(line_number, int)
                or line_number < 0
            ):
                raise ValueError(f"CFEVER case {record.get('id')}: invalid evidence pointer")
            references.append((page_id, line_number))
        if references:
            normalized.append(sorted(set(references)))
    if record.get("label") != "NOT ENOUGH INFO" and not normalized:
        raise ValueError(f"CFEVER case {record.get('id')} has no usable evidence")
    return normalized


def select_evidence_set(record: dict) -> list[tuple[str, int]]:
    candidates = evidence_sets(record)
    if not candidates:
        return []
    return min(candidates, key=lambda group: (len(group), group))


def _parse_numbered_lines(value: object) -> dict[int, str]:
    if not isinstance(value, str):
        return {}
    parsed: dict[int, str] = {}
    for raw_line in value.splitlines():
        number, separator, remainder = raw_line.partition("\t")
        if separator and number.isdigit():
            parsed[int(number)] = remainder.split("\t", 1)[0].strip()
    return parsed


def load_wikipedia_pages(wiki_dir: Path, required_pages: set[str]) -> dict[str, dict[int, str]]:
    paths = sorted(wiki_dir.glob("wiki-*.jsonl"))
    if not paths:
        raise ValueError(f"no wiki-*.jsonl files found in {wiki_dir}")

    pages: dict[str, dict[int, str]] = {}
    remaining = set(required_pages)
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                try:
                    page = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
                page_id = page.get("id")
                if page_id not in remaining:
                    continue
                pages[page_id] = _parse_numbered_lines(page.get("lines"))
                remaining.remove(page_id)
                if not remaining:
                    return pages
    if remaining:
        missing = ", ".join(sorted(remaining)[:10])
        suffix = " ..." if len(remaining) > 10 else ""
        raise ValueError(f"missing {len(remaining)} Wikipedia pages: {missing}{suffix}")
    return pages


def wikipedia_url(page_id: str) -> str:
    slug = quote(page_id.replace(" ", "_"), safe="()_")
    return f"https://zh.wikipedia.org/wiki/{slug}"


def to_simplified(value: str) -> str:
    return SIMPLIFIER.convert(value)


def build_snapshot(
    record: dict,
    pages: dict[str, dict[int, str]],
    *,
    split: str,
    recorded_at: str,
    source_verified: bool = True,
) -> dict:
    """Build a snapshot; source_verified asserts caller-reviewed claims and evidence."""
    _validate_record(record)
    _validate_split(split)
    _validate_recorded_at(recorded_at)
    label = record.get("label")
    if label not in LABEL_MAP:
        raise ValueError(f"unsupported CFEVER label: {label!r}")

    reference_sets = evidence_sets(record)
    references = sorted({reference for group in reference_sets for reference in group})
    if label != "NOT ENOUGH INFO" and not references:
        raise ValueError(f"CFEVER case {record.get('id')} has no usable evidence")

    grouped_lines: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for page_id, line_number in references:
        page_lines = pages.get(page_id)
        if page_lines is None:
            raise ValueError(f"CFEVER case {record.get('id')}: missing page {page_id!r}")
        snippet = page_lines.get(line_number)
        if not snippet:
            raise ValueError(
                f"CFEVER case {record.get('id')}: missing line {line_number} in page {page_id!r}"
            )
        grouped_lines[page_id].append((line_number, snippet))

    retrieval_results = []
    for index, page_id in enumerate(sorted(grouped_lines), start=1):
        numbered_snippets = sorted(set(grouped_lines[page_id]))
        snippet = to_simplified(" ".join(text for _, text in numbered_snippets))
        url = wikipedia_url(page_id)
        display_title = to_simplified(page_id.replace("_", " "))
        retrieval_results.append(
            {
                "result_id": f"wiki_{index}",
                "title": display_title,
                "url": url,
                "source_name": "中文维基百科",
                "published_at": "",
                "snippet": snippet,
                "source_tier": "B",
            }
        )

    expected_sets = []
    for group in reference_sets:
        group_pages: dict[str, list[int]] = defaultdict(list)
        for page_id, line_number in group:
            group_pages[page_id].append(line_number)
        expected_sets.append([
            {
                "url": wikipedia_url(page_id),
                "title": (
                    f"{to_simplified(page_id.replace('_', ' '))}"
                    f"（第 {','.join(map(str, sorted(line_numbers)))} 行）"
                ),
            }
            for page_id, line_numbers in sorted(group_pages.items())
        ])
    expected_evidence = min(
        expected_sets, key=lambda group: (len(group), json.dumps(group, sort_keys=True)), default=[]
    )

    verdict = LABEL_MAP[label]
    claim = to_simplified(record["claim"])
    return {
        "case_id": f"cfever_{split}_{record['id']}",
        "recorded_at": recorded_at,
        "raw_input": claim,
        "retrieval_results": retrieval_results,
        "expected_claims": [
            {
                "claim": claim,
                "claim_type": "fact",
                "verdict": verdict,
                "confidence": "low" if verdict == "insufficient" else "high",
                "evidence": expected_evidence,
                "evidence_sets": expected_sets,
                "evaluation": {"score_confidence": False},
            }
        ],
        "metadata": {
            "source": "CFEVER",
            "provenance": "public_dataset" if source_verified else "unverified_import",
            "source_case_id": record["id"],
            "source_revision": SOURCE_REVISION if source_verified else None,
            "review_status": "approved" if source_verified else "quarantined",
            "review_reason": (
                "Source claims and evidence verified by caller against pinned upstream."
                if source_verified else "Input claims or Wikipedia evidence require source review."
            ),
            "annotation_source": "upstream_label",
            "confidence_source": "converter_derived_not_upstream_gold",
            "dataset_license": "Apache-2.0",
            "evidence_license": "CC BY-SA (source-dump version)",
            "split": split,
            "domain": to_simplified(record.get("domain", "")),
            "topic_group": topic_group(record),
            "original_label": label,
            "original_claim": record["claim"],
            "original_evidence_sets": [
                [{"page_title": page_id, "sentence_id": line_number}
                 for page_id, line_number in group]
                for group in reference_sets
            ],
            "text_variant": "zh-Hans",
            "source_text_variant": "zh-Hant",
            "text_conversion": "OpenCC t2s",
            "categories": ["external_benchmark", "wikipedia_evidence"],
        },
    }


def convert_dataset(
    *,
    claims_path: Path,
    wiki_dir: Path,
    output_dir: Path,
    per_label: int,
    split: str,
    recorded_at: str,
    manifest_path: Path | None = None,
    seed: int = DEFAULT_SEED,
    allow_unverified: bool = False,
) -> dict:
    _validate_split(split)
    _validate_recorded_at(recorded_at)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"output directory must be empty: {output_dir}")

    claims_digest = _sha256(claims_path)
    claims_verified = split == "dev" and claims_digest == PINNED_DEV_SHA256
    if not claims_verified and not allow_unverified:
        raise ValueError("claims digest/split does not match pinned dev; use --allow-unverified for quarantine")
    selected = select_balanced(_read_jsonl(claims_path), per_label, seed)
    selected_references = {
        reference
        for record in selected
        for group in evidence_sets(record)
        for reference in group
    }
    required_pages = {page_id for page_id, _ in selected_references}
    pages = load_wikipedia_pages(wiki_dir, required_pages) if required_pages else {}
    snapshots = [
        build_snapshot(record, pages, split=split, recorded_at=recorded_at, source_verified=False)
        for record in selected
    ]
    for snapshot in snapshots:
        snapshot["metadata"]["claims_sha256"] = claims_digest
        snapshot["metadata"]["claims_source_revision"] = SOURCE_REVISION if claims_verified else None

    label_counts = {
        LABEL_MAP[label]: sum(record["label"] == label for record in selected)
        for label in LABEL_ORDER
    }
    manifest = {
        "dataset": "CFEVER",
        "source_repository": SOURCE_REPOSITORY,
        "source_revision": SOURCE_REVISION if claims_verified else None,
        "source_verification": {
            "claims": "pinned_digest_verified" if claims_verified else "unverified",
            "wikipedia": "unverified_local_corpus",
            "review_status": "quarantined",
        },
        "upstream_repository": UPSTREAM_REPOSITORY,
        "split": split,
        "claims_file": claims_path.name,
        "claims_sha256": claims_digest,
        "wikipedia_input_sha256": {
            path.name: _sha256(path) for path in sorted(wiki_dir.glob("wiki-*.jsonl"))
        },
        "sampling": {
            "seed": seed,
            "rule": "per-label topic round-robin; sorted IDs then seeded shuffle",
            "topic_key": "upstream domain, otherwise first evidence page, otherwise unknown",
            "selected_source_ids": [record["id"] for record in selected],
            "topic_counts": {
                name: sum(topic_group(record) == name for record in selected)
                for name in sorted({topic_group(record) for record in selected})
            },
        },
        "snapshot_count": len(snapshots),
        "label_counts": label_counts,
        "case_ids": [snapshot["case_id"] for snapshot in snapshots],
        "mapping": {
            "supports": "supported",
            "refutes": "refuted",
            "NOT ENOUGH INFO": "insufficient",
        },
        "wikipedia_pages_used": sorted(required_pages),
    }
    destination = manifest_path or output_dir.parent / f"{output_dir.name}.manifest.json"
    snapshot_paths = [output_dir / f"{snapshot['case_id']}.json" for snapshot in snapshots]
    resolved_destination = destination.resolve()
    resolved_output = output_dir.resolve()
    resolved_snapshots = {path.resolve() for path in snapshot_paths}
    if resolved_destination in resolved_snapshots or resolved_snapshots.intersection(resolved_destination.parents):
        raise ValueError("manifest path collides with a snapshot")
    if resolved_destination in {resolved_output, *resolved_output.parents}:
        raise ValueError("manifest path collides with output directory")
    if resolved_destination.is_relative_to(resolved_output):
        raise ValueError("manifest must be outside the output directory and its subdirectories")
    if destination.exists():
        raise ValueError(f"manifest path already exists: {destination}")
    for parent in destination.parents:
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"manifest parent is not a directory: {parent}")
    for snapshot, output_path in zip(snapshots, snapshot_paths, strict=True):
        validate_snapshot(snapshot, path=output_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    for snapshot, output_path in zip(snapshots, snapshot_paths, strict=True):
        output_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=Path, required=True, help="CFEVER train/dev JSONL file")
    parser.add_argument("--wiki-dir", type=Path, required=True, help="Directory containing wiki-*.jsonl")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("evals/live_replay/cfever"),
        help="Empty destination for replay snapshots",
    )
    parser.add_argument("--manifest", type=Path, help="Generated conversion manifest path")
    parser.add_argument("--per-label", type=int, default=100, help="Cases selected per CFEVER label")
    parser.add_argument("--split", default="dev", help="Split name stored in case IDs and metadata")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Reproducible sampling seed")
    parser.add_argument(
        "--allow-unverified", action="store_true",
        help="Accept unverified claims as quarantined imports without a claimed source revision",
    )
    parser.add_argument(
        "--recorded-at",
        default=DEFAULT_RECORDED_AT,
        help="Deterministic timestamp stored in generated snapshots",
    )
    args = parser.parse_args()

    manifest = convert_dataset(
        claims_path=args.claims,
        wiki_dir=args.wiki_dir,
        output_dir=args.output_dir,
        per_label=args.per_label,
        split=args.split,
        recorded_at=args.recorded_at,
        manifest_path=args.manifest,
        seed=args.seed,
        allow_unverified=args.allow_unverified,
    )
    print(
        f"converted {manifest['snapshot_count']} CFEVER cases to {args.output_dir} "
        f"({manifest['label_counts']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
