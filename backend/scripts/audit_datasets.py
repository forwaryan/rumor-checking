"""Audit replay data, source provenance and development/holdout separation offline."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.services.eval_recorder import (  # noqa: E402
    EvalSnapshot,
    is_quarantined,
    iter_snapshots,
    load_snapshot,
)

EVALUATION_SPLITS = {"development", "holdout"}


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _url_identity(url: str) -> str:
    parsed = urlsplit(url.strip())
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.query, ""))


def _validate_manifest(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not _text(payload.get("dataset")):
        raise ValueError("conversion manifest requires a dataset name")
    if {"case_id", "raw_input", "expected_claims", "retrieval_results"}.intersection(payload):
        raise ValueError("snapshot fields cannot be hidden inside a conversion manifest")
    case_ids = payload.get("case_ids")
    if not isinstance(case_ids, list) or not all(_text(case_id) for case_id in case_ids):
        raise ValueError("conversion manifest requires a case_ids array of nonempty identifiers")
    count = payload.get("snapshot_count")
    if type(count) is not int or count != len(case_ids) or len(set(case_ids)) != count:
        raise ValueError("manifest snapshot_count must match distinct case_ids")
    digest = payload.get("claims_sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
        raise ValueError("conversion manifest requires a claims_sha256 digest")
    return payload


def _summary(snapshots: list[EvalSnapshot], *, file_count: int) -> dict:
    scored = [snapshot for snapshot in snapshots if not is_quarantined(snapshot)]
    labels = Counter(claim["verdict"] for snapshot in scored for claim in snapshot.expected_claims)
    claim_count = sum(labels.values())
    majority_count = max(labels.values(), default=0)
    topics = sorted({snapshot.metadata["topic_group"] for snapshot in snapshots
                     if _text(snapshot.metadata.get("topic_group"))})
    split_counts = Counter(
        snapshot.metadata.get("evaluation_split", "unassigned")
        if isinstance(snapshot.metadata.get("evaluation_split", "unassigned"), str) else "invalid"
        for snapshot in snapshots
    )
    return {
        "total": file_count,
        "loaded": len(snapshots),
        "invalid": file_count - len(snapshots),
        "scored": len(scored),
        "scored_ids": [snapshot.case_id for snapshot in scored],
        "quarantined": [
            {"case_id": snapshot.case_id, "reason": snapshot.metadata["review_reason"]}
            for snapshot in snapshots if is_quarantined(snapshot)
        ],
        "label_counts": dict(sorted(labels.items())),
        "scored_claims": claim_count,
        "unique_topic_groups": len(topics),
        "topic_groups": topics,
        "evaluation_split_counts": dict(sorted(split_counts.items())),
        "nonempty_insufficient_claims": sum(
            claim["verdict"] == "insufficient" and bool(snapshot.retrieval_results)
            for snapshot in scored for claim in snapshot.expected_claims
        ),
        "majority_label_baseline": {
            "labels": sorted(label for label, count in labels.items() if count == majority_count),
            "accuracy": majority_count / claim_count if claim_count else None,
            "claim_count": claim_count,
        },
    }


def audit_datasets(root: Path) -> dict:
    """Labels/baselines use scored claims; topic/split counts include quarantine."""
    root = Path(root)
    groups = {}
    errors = []
    warnings = []
    excluded_metadata = []
    all_snapshots = []
    seen_ids: dict[str, str] = {}
    topic_paths: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    url_paths: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    if not root.is_dir():
        errors.append({"code": "missing_root", "message": f"Not a dataset directory: {root}"})
        directories = []
    else:
        directories = sorted({path.parent for path in root.rglob("*.json")})

    for directory in directories:
        group_name = directory.relative_to(root).as_posix()
        legacy = directory / "cases.json"
        if legacy.exists():
            excluded_metadata.append({
                "path": legacy.relative_to(root).as_posix(), "kind": "legacy_aggregate",
                "reason": "Aggregate storage is excluded to avoid duplicate counting.",
            })
            warnings.append({
                "code": "legacy_aggregate", "group": group_name,
                "message": "cases.json is excluded: aggregate storage risks duplicate counting; use individual snapshots.",
            })
        manifest_paths = set(directory.glob("*.manifest.json"))
        for manifest_path in sorted(manifest_paths):
            relative_path = manifest_path.relative_to(root).as_posix()
            try:
                manifest = _validate_manifest(manifest_path)
            except (ValueError, OSError, TypeError) as exc:
                errors.append({"code": "invalid_manifest", "path": relative_path, "message": str(exc)})
            else:
                excluded_metadata.append({
                    "path": relative_path, "kind": "conversion_manifest",
                    "reason": "Validated conversion metadata; individual snapshots are audited separately.",
                    "snapshot_count": manifest["snapshot_count"],
                })
        paths = sorted(path for path in directory.glob("*.json")
                       if path.name != "cases.json" and path not in manifest_paths)
        if not paths:
            continue
        try:
            snapshots = iter_snapshots(directory, include_quarantined=True)
            entries = list(zip(paths, snapshots, strict=True))
        except (ValueError, OSError, TypeError):
            entries = []
            for path in paths:
                try:
                    entries.append((path, load_snapshot(path)))
                except (ValueError, OSError, TypeError) as exc:
                    errors.append({"code": "invalid_snapshot", "path": path.relative_to(root).as_posix(),
                                   "message": str(exc)})
            snapshots = [snapshot for _, snapshot in entries]
        summary = _summary(snapshots, file_count=len(paths))
        groups[group_name] = summary
        all_snapshots.extend(snapshots)
        if not summary["scored"]:
            warnings.append({"code": "unscorable_group", "group": group_name,
                             "message": "No scoreable snapshots; baseline and label accuracy are unavailable."})
        elif summary["scored_claims"] < 30:
            warnings.append({"code": "small_sample", "group": group_name,
                             "message": "Fewer than 30 scored claims; this is diagnostic coverage, not a stable accuracy estimate."})
        baseline = summary["majority_label_baseline"]["accuracy"]
        if baseline is not None and baseline >= 0.75:
            warnings.append({"code": "label_imbalance", "group": group_name,
                             "message": f"Majority-label baseline is {baseline:.1%}; compare model accuracy with this baseline."})
        if summary["evaluation_split_counts"].get("unassigned"):
            warnings.append({"code": "unassigned_split", "group": group_name,
                             "message": "Unassigned snapshots are not part of the development/holdout separation check."})

        for path, snapshot in entries:
            relative_path = path.relative_to(root).as_posix()
            if snapshot.case_id in seen_ids:
                errors.append({"code": "duplicate_case_id", "path": relative_path,
                               "message": f"Duplicate case_id {snapshot.case_id!r}; first at {seen_ids[snapshot.case_id]}"})
            else:
                seen_ids[snapshot.case_id] = relative_path
            if path.stem != snapshot.case_id:
                errors.append({"code": "filename_mismatch", "path": relative_path,
                               "message": f"Filename must match case_id {snapshot.case_id!r}"})
            metadata = snapshot.metadata
            if metadata.get("provenance") == "public_dataset":
                missing = [key for key in ("source_revision", "annotation_source", "original_label", "original_claim")
                           if not _text(metadata.get(key))]
                source_id = metadata.get("source_case_id")
                if not (_text(source_id) or type(source_id) is int and source_id >= 0):
                    missing.append("source_case_id")
                if missing:
                    errors.append({"code": "missing_public_provenance", "path": relative_path,
                                   "message": f"Public dataset requires source provenance: {', '.join(missing)}"})
            if "evaluation_split" not in metadata:
                continue
            split = metadata["evaluation_split"]
            topic = metadata.get("topic_group")
            if not isinstance(split, str) or split not in EVALUATION_SPLITS:
                errors.append({"code": "invalid_evaluation_split", "path": relative_path,
                               "message": "evaluation_split must be development or holdout"})
                continue
            if not _text(topic):
                errors.append({"code": "missing_topic_group", "path": relative_path,
                               "message": "evaluation_split requires a nonempty topic_group"})
            else:
                topic_paths[topic.strip()][split].append(relative_path)
            for url in {result["url"] for result in snapshot.retrieval_results}:
                try:
                    url_paths[_url_identity(url)][split].append(relative_path)
                except ValueError as exc:
                    errors.append({"code": "invalid_evidence_url", "path": relative_path, "message": str(exc)})

    for code, identities in (("topic_split_leakage", topic_paths), ("evidence_split_leakage", url_paths)):
        for identity, splits in sorted(identities.items()):
            if EVALUATION_SPLITS.issubset(splits):
                errors.append({"code": code, "identity": identity,
                               "paths": {split: sorted(set(paths)) for split, paths in sorted(splits.items())},
                               "message": "Shared content crosses development and holdout"})
    totals = _summary(all_snapshots, file_count=sum(group["total"] for group in groups.values()))
    if not totals["total"] and not errors:
        errors.append({"code": "empty_corpus", "message": "No individual replay snapshots found"})
    status = "invalid" if errors else "passed" if totals["scored"] else "unscorable"
    return {
        "root": str(root), "status": status,
        "distribution_scope": "label_counts and baselines use scored claims; topic/split counts use all loaded snapshots",
        "url_identity_rule": "All retrieval URLs; ignore fragments and trailing slash, lowercase scheme/host, retain queries",
        "excluded_metadata_count": len(excluded_metadata), "excluded_metadata": excluded_metadata,
        "groups": groups, "totals": totals, "errors": errors, "warnings": warnings,
    }


def format_summary(report: dict) -> str:
    lines = [f"Dataset audit: {report['status'].upper()} ({report['root']})"]
    lines.append(f"Excluded metadata: {report['excluded_metadata_count']}")
    for metadata in report["excluded_metadata"]:
        lines.append(f"  {metadata['path']} ({metadata['kind']}): {metadata['reason']}")
    for name, group in report["groups"].items():
        accuracy = group["majority_label_baseline"]["accuracy"]
        baseline = "N/A" if accuracy is None else f"{accuracy:.1%}"
        lines.append(
            f"{name}: total={group['total']} scored={group['scored']} quarantined={len(group['quarantined'])} "
            f"topics={group['unique_topic_groups']} nonempty_NEI={group['nonempty_insufficient_claims']} "
            f"majority_baseline={baseline}"
        )
        lines.append(f"  labels={group['label_counts']} splits={group['evaluation_split_counts']}")
        for excluded in group["quarantined"]:
            lines.append(f"  quarantined {excluded['case_id']}: {excluded['reason']}")
    for category in ("errors", "warnings"):
        for issue in report[category]:
            location = issue.get("path", issue.get("group", issue.get("identity", "corpus")))
            lines.append(f"{category.upper()} [{issue['code']}] {location}: {issue['message']}")
    if report["status"] == "unscorable":
        lines.append("Corpus is structurally valid but has no scoreable snapshots; no accuracy claim can be made.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT / "evals" / "live_replay")
    parser.add_argument("--json", action="store_true", help="Print the complete audit as JSON")
    args = parser.parse_args(argv)
    report = audit_datasets(args.root)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else format_summary(report))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
