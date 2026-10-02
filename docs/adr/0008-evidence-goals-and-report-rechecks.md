# 0008 — Evidence goals, scoped report revisions and bounded execution

- Status: Accepted
- Date: 2026-09-13

## Context

Related pages can omit the attribute a claim asserts. Internal Critic retries
already exist, but users could not add sources to a completed report or compare
successive investigations. Durable runs also needed an explicit stopping path.

## Decision

Add conservative structured price, route, time, quantity and scope coverage
gaps to claim results and use their query suggestions in bounded per-claim
retrieval. A gap annotates the claim and drives another retrieval round even if
the current verdict is decisive; it never rewrites the verdict in either
direction. The detectors are bounded keyword/regex probes over a few domains,
so a pattern miss is evidence about the patterns, not about the claim, and
adjudication stays with the rule and LLM judges. Keep unrecognized domains on
the existing path.

Create immutable child runs for user-selected claims, preserving parent types,
original requests and private case lineage. Apply the selection at claim
extraction; the verdict engine accepts an explicit subset for focused rechecks
and rejects out-of-scope claims instead of silently replacing caller inputs.
Synthesis is capped at six claims; when a review selects more, fall back to
judging the complete selection with rules, without per-claim or correction LLM
calls that would exhaust the durable run budget. Match synthesized
results by claim text and inherited type, consuming each result at most once;
missing or misclassified parent facts remain insufficient, never promoted.
Compare only rechecked claims and their cited sources. Use transactional
revision allocation and idempotency keys, and retain ancestors while their
case is active.

Fetch supplementary public URLs through pinned validated addresses with original
Host/TLS identity and no environment proxy. Keep user notes outside evidence.
Do not blend synthetic retrieval fixtures into a live supplement bundle.

Use a shared cooperative RunControl and database-backed pre-call reservations.
Cancellation bypasses ordinary analysis-error fallbacks and cannot become a
late completed report. No claim is made that an in-flight external call can be
retracted or that estimated reservations equal billed token usage.

Add a dedicated offline scripted deep-Agent replay using actual orchestration
and deterministic external responses, separate from supplied-evidence verdict
benchmarks. Record fingerprints and call/step evidence without prompt text.

## Alternatives considered

- Adding another generic critic duplicates an existing mechanism without making
  missing attributes or follow-up actions explicit.
- Mutating the original report loses the evidence and reasoning behind changes.
- Replacing the Agent framework introduces overlapping runtime behavior without
  resolving these domain-specific boundaries.

## Consequences

- Query-time evidence requirements and post-report review now share claim scope.
- Coverage detection is a retrieval and disclosure signal only; a domain-specific
  pattern can never silently turn a judged claim into `insufficient`, so growing
  the pattern list cannot quietly move replay scores. It can still increase
  bounded retrieval work for a decisive claim with an unresolved gap.
- Focused search inherits the original request's source and cache restrictions,
  rotates unsearched claims under its query cap, and keeps pre-existing result
  IDs only for the same URL while retaining a stronger canonical source at a
  different URL. Subset re-judgment preserves unaffected evidence and an
  unchanged claim's probability when the new judge provides no estimate.
- A private version link grants access to its case history; separate account
  permissions remain a deployment concern.
- Coverage spans price, route, time, quantity and scope attributes. The offline
  deep replay exercises one Agent path; scheduled watching, semantic case memory
  and multi-agent replay remain later work.

See [run/review API](../durable-analysis.md) and [evidence goals](../evidence-goals.md).
