# 0013 — Preserve time and attribute constraints after model judgment

- Status: Accepted
- Date: 2026-09-30

## Context

The primary LLM judge received evidence titles and snippets without source dates.
It could replace a cautious rule result with a definite current-state claim even
when no dated evidence existed. Separately, the price coverage check rejected
valid transit fares expressed as a starting price or maximum fare.

## Decision

Pass the selected evidence's source and publication date to the judge, marking
missing or invalid dates as unknown. Supply the evaluation date separately so it
cannot be mistaken for a source date. The judge can accept an explicit reference
date; normal calls use the current local evaluation date. Existing replay does
not automatically treat snapshot recording time as a historical evaluation date.
The separate scripted offline Agent replay compatibility adjustment remains in
the development workspace and is not included in this commit.

After model judgment, corrections and evidence goals, apply a narrow date gap
check to explicitly current operating, policy and service states. When none of
the cited evidence has a verifiable publication date or explicit calendar date
in its content, preserve the citations but return insufficient/low and clear
incompatible correction and probability fields. Expose the additive EvidenceGap
contract on ClaimResult. This is a missing-time check, not proof that every dated
page is fresh
or applicable; semantic relevance and effective periods still require judgment.
Do not apply it to timeless definitions merely because they lack a date.

Transit fare coverage recognizes starting fares, ceilings and free travel in
the matching transport context. Ancillary charges and other transport modes do
not fill the gap. Coverage never chooses supported or refuted by itself.

The judge compares semantic propositions, including mutually exclusive values
and numeric bounds, without requiring explicit debunking words. Compound claims
require support for all necessary assertions; one directly refuted assertion can
refute a conjunction. Missing assertions and nonexclusive aliases remain unknown.
Paraphrases do not require literal text matches, but cannot broaden evidence.

## Consequences

- Deterministic checks retain evidence requirements even if an LLM ignores them.
- Model prompts become longer; request budgets and timeouts remain unchanged.
- Date and fare recognition are deliberately bounded and need negative controls.
- Known snapshots, including previously inspected holdouts, are regression data.
  Re-running them after changes is not independent accuracy validation. Keep gold
  labels, corpus hashes and intermediate results, and report new regressions.

## Commit scope and validation boundary

This commit includes the judge prompt/date metadata, the final current-service
date guard, price coverage and the minimal additive gap contract. It does not
include report rechecks, supplemental-source orchestration, run-control budgets,
evidence snapshots, other attribute-goal dimensions, or the new Agent replay tool.
The 54/56 live result belongs to the complete development workspace and its
additional evaluation corpora; it is not a measured accuracy score for this
isolated commit, nor an end-to-end retrieval accuracy estimate.
