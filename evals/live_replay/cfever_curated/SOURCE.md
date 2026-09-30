# Curated CFEVER replay subset

This directory contains 24 records selected from the CFEVER development split:
eight `supports`, eight `refutes`, and eight `NOT ENOUGH INFO` cases across eight
topics. Each topic has one original record of each label. Labels remain unchanged.

The project's development and holdout groups each contain 12 records from four
disjoint topics. `metadata.split` remains the upstream `dev` split;
`metadata.evaluation_split` records the project grouping. **The project holdout
is not CFEVER's official test split.** Selection is a deliberately small,
topic-balanced diagnostic sample, not a random estimate of corpus performance.
The added topics were selected without model scores. Do not tune on the holdout
and then continue to describe its results as independent acceptance evidence.

| Project split | Topic | Supports ID | Refutes ID | NEI ID | Original Wikipedia page / sentence IDs |
| --- | --- | --- | --- | --- | --- |
| development | 芝加哥 | 453 | 13346 | 463 | `芝加哥`: 0 for 453, 9 for 13346 |
| development | 罗纳德·里根 | 787 | 788 | 793 | `羅納德·里根`: 0 |
| development | 爬行动物 | 892 | 893 | 898 | `爬行動物`: 24 |
| development | 威廉·萨默塞特·毛姆 | 934 | 937 | 936 | `威廉·薩默塞特·毛姆`: 5 |
| holdout | 日本海 | 733 | 737 | 732 | `日本海`: 1 |
| holdout | MacOS | 1120 | 1119 | 1121 | `MacOS`: 58 |
| holdout | 锡克教 | 1702 | 1707 | 1704 | `錫克教`: 2 |
| holdout | 抄袭 | 2165 | 2166 | 2167 | `抄襲`: 0 and 10 jointly for 2165; 0 for 2166 |

NEI records retain upstream null evidence pointers and receive no invented gold
evidence. They share their topic's group and project split even without a page
reference. Evidence pointers for all records, including annotation IDs and nulls,
are preserved verbatim as `metadata.original_evidence`; normalized groups are in
`metadata.original_evidence_sets`. `source_record_line` is the one-based physical
line in `dev.jsonl`, while `sentence_id` is the original Wikipedia sentence ID.
These are distinct coordinate systems.

- Dataset: <https://github.com/IKMLab/CFEVER-data>
- Pinned Hugging Face revision: `1f8fa4bd290832d7ad3109f49e347eb5dc77b7ad`
- Development JSONL SHA-256: `c4bdeaebc90e8a21768919d212ff4a25cd8bf0edef00f64f0197066e7b034ddc`
- New-topic evidence file: `wiki-001.jsonl`; physical page-record lines are 6913
  (`抄襲`), 7885 (`錫克教`), 9726 (`日本海`), and 9729 (`MacOS`).
- Pinned Hugging Face LFS declaration for `wiki-001.jsonl`:
  `7f5e58930aab686ed596005baabdea27103c9994f635eabdfbb07ca95ad62d2a`.
  Required records and sentences were read at the pinned revision; the full
  Wikipedia file was not downloaded and rehashed. Metadata distinguishes this
  declared digest from a locally verified full-file digest.
- CFEVER repository license: Apache-2.0
- Evidence source: processed Chinese Wikipedia text, subject to the CC BY-SA
  version applicable to the source dump

The snapshots retain Wikipedia page URLs for attribution. They are an
aggregate test-data component and do not change the license of the application
source code. Review the upstream terms before redistributing this subset in a
different product or context.

All human-readable evaluation text is converted from the original Traditional
Chinese to Simplified Chinese with OpenCC `t2s`. The original CFEVER IDs,
revision, and Wikipedia URL slugs remain unchanged for traceability.

Each approved record has `annotation_source=upstream_label`, original claim text,
review time, review scope, and source line/hash metadata. The existing 12 claims,
snippets, and labels remain unchanged. New records use the same converter after
source review. Every alternative evidence group is retained: all URLs within
one group are required and any complete group is sufficient. Retrieval contains
the union of required pages and sentences. URL-level matching alone does not
prove that every necessary sentence was used; original pointers allow inspection.

Confidence values are derived by the adapter, not supplied as CFEVER gold.
`expected_claims[].evaluation.score_confidence=false` excludes them from the
confidence metric. This remains a given-evidence verdict diagnostic, not an
end-to-end search or claim-extraction benchmark. All eight upstream NEI records
have empty retrieval; synthetic guard cases separately cover nonempty but
insufficient evidence.
