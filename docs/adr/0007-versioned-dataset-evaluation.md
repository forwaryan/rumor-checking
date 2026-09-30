# 0007 — Version dataset provenance, evidence-group scoring and partitions

- Status: Accepted
- Date: 2026-09-13

## Context

Replay previously treated any overlapping evidence URL as sufficient and silently
skipped malformed snapshots. Selected public examples had incomplete annotation
provenance, while confidence values derived locally could be mistaken for upstream
gold. A small topic-correlated set could not represent general product accuracy.

## Decision

Keep the existing evaluator and explicitly version its given-claim, supplied-
evidence protocol. Require every URL in one valid evidence group; preserve
alternative groups and original sentence pointers. Retain legacy metric field
names but state that URL-level scoring is not the official sentence-level FEVER.

Validate all input records before excluding explicitly quarantined examples.
Report exclusion reasons and refuse an entirely unscorable run. Treat automatically
recorded model output as unreviewed data, not ground truth. Store transformation,
source and review information separately from factual verdicts.

Use topic-separated project development/holdout metadata without relabeling
upstream splits. Audit shared topics and evidence URLs across partitions, report
label baselines, and prevent direct comparisons across different corpora/protocols.

## Alternatives considered

- Keep URL-overlap scoring: incomplete proofs would continue to pass.
- Rewrite labels to match current rules: this would erase the intended error
  signal and weaken evidence requirements.
- Implement official sentence-level FEVER immediately: the public report schema
  has URL citations but does not carry complete sentence-level attribution.

## Consequences

- Data/annotation corrections and runtime accuracy changes remain distinguishable.
- Existing malformed datasets now fail explicitly and require repair.
- No date or source-authority values are invented to improve scores.
- Generated imports without verifiable sources remain outside scored gold until
  reviewed; curated source checks record their actual verification scope.
- Independent accuracy claims require larger representative samples and a
  separate end-to-end retrieval/claim-extraction evaluation.

See [dataset quality](../dataset-quality.md) for repaired cases and commands.
