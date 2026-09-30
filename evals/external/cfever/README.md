# CFEVER replay adapter

This directory contains the full-corpus adapter and provenance metadata.
CFEVER claims, the processed Chinese Wikipedia corpus, and locally generated
large replay sets are intentionally not committed. A manually reviewed 24-case
subset is versioned in `evals/live_replay/cfever_curated/`.

## Why this dataset

CFEVER provides Chinese claims with `supports`, `refutes`, and
`NOT ENOUGH INFO` labels. The converter maps them to `supported`, `refuted`, and
`insufficient`. Evidence pointers are resolved against the processed Wikipedia
corpus before a replay snapshot is written; malformed evidence pointers, missing
pages, or missing line numbers fail the conversion instead of producing incomplete
evidence. A non-NEI pointer requires a nonblank page ID and a nonnegative integer
line number (booleans are rejected). The upstream NEI null-pointer sentinel is
accepted. Duplicate IDs, blank claims, and unsafe split names are rejected before
any snapshots are written. `recorded_at` must be a valid ISO timestamp. Every
final snapshot passes the replay loader's strict validation before the output
directory is created. Manifest paths must be outside the snapshot directory and
its subdirectories, preventing metadata JSON from being mistaken for a case.
Human-readable claim,
title, snippet, evidence-title, and domain fields are converted to Simplified
Chinese with OpenCC `t2s`; original claims and page/sentence locations remain in
metadata and original page IDs remain in URLs for attribution.

Alternative evidence groups are preserved in `expected_claims[].evidence_sets`:
every URL in one group is required, while satisfying any complete group suffices.
The compatible `evidence` field contains one deterministic canonical group.
Retrieval includes the union of all groups' pages and sentences. Page-level replay
scoring does not establish sentence-level entailment; the original sentence
pointers support later review. Confidence is converter-derived, not an upstream
annotation, so each expected claim sets `evaluation.score_confidence` to `false`.

## Download

Install the Hugging Face CLI separately, then download the pinned dataset
revision into the ignored local data directory:

```bash
hf download IKMLab-team/cfever \
  --repo-type dataset \
  --revision 1f8fa4bd290832d7ad3109f49e347eb5dc77b7ad \
  --include 'dev.jsonl' 'wiki-*.jsonl' \
  --local-dir data/external/cfever
```

The 24 Wikipedia files contain roughly 1 GB of uncompressed JSONL. Verify the
claim file before conversion (the converter also enforces this digest by default):

```bash
shasum -a 256 data/external/cfever/dev.jsonl
```

The expected digest is recorded in `manifest.json`.

## Convert

Generate the recommended balanced subset of 300 snapshots:

```bash
python backend/scripts/convert_cfever.py \
  --claims data/external/cfever/dev.jsonl \
  --wiki-dir data/external/cfever \
  --output-dir evals/live_replay/cfever \
  --per-label 100 \
  --seed 20260913 \
  --split dev
```

The output directory is ignored by Git. The converter also writes
`evals/live_replay/cfever.manifest.json`, containing the selected case IDs,
claim source revision when verified, actual claims and local Wikipedia file
digests, seed, selected upstream IDs, label counts, topic counts, and Wikipedia
page list. Selection balances the three labels and samples in rounds across
upstream domains (falling back to an evidence page or `unknown`). Sorting IDs
before seeded shuffling makes selection independent of input file order. This
reduces first-N topic bias; it is not a substitute for a topic-isolated holdout.

The offline dataset auditor recognizes `*.manifest.json` conversion metadata
after checking its dataset name, distinct case IDs/count, and input digest shape.
It reports these files under `excluded_metadata` and `excluded_metadata_count`
instead of counting them as snapshots. A malformed manifest still fails the
audit, and ordinary malformed JSON files are never skipped by this rule.

By default, the claims file must match the pinned `dev` digest and `--split dev`.
For a different split or custom fixture, pass `--allow-unverified`. Such input is
recorded as `unverified_import`, with no asserted source revision. Its actual
input digest is still retained. The flag does not bypass evidence validation.

The CLI cannot prove local Wikipedia files match the upstream revision solely
from their names. It therefore puts **all generated snapshots in quarantine**,
including when the claims digest is verified. The manifest distinguishes verified
claims from unverified local evidence and records local evidence digests. Review
the Wikipedia inputs against pinned upstream LFS digests and record approval
before using these outputs as an acceptance benchmark. The low-level
`build_snapshot(..., source_verified=True)` interface is reserved for callers
that have already reviewed both claims and evidence; it does not perform that
review itself. The committed, manually reviewed 24-case subset is unchanged by
the CLI's default quarantine policy.

After source review, approve snapshots with a review reason and assign project
`evaluation_split` (`development` or `holdout`) by topic. Preserve the upstream
`split` field; do not relabel upstream `dev` as a project holdout. Replay with:

```bash
python backend/scripts/replay_eval.py --dir evals/live_replay/cfever
```

## Licensing notes

- The CFEVER repository declares Apache-2.0.
- Evidence text is derived from Chinese Wikipedia and retains its applicable
  Creative Commons attribution/share-alike requirements.
- Do not vendor the full Wikipedia corpus into this repository.
- Before redistributing generated snapshots, review the source dump's exact
  license and preserve page URLs as attribution.
