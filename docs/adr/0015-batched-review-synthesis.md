# 0015 — Bounded review synthesis

- Status: Accepted
- Date: 2026-10-24

## Context

Report rechecks can select up to fifty parent claims, but synthesis accepted at
most six. Larger selections returned directly to the rule path before any LLM
judgment, even when suitable evidence and a model were available.

## Decision

Split selected recheck claims into sequential batches of at most six, with at
most nine batches for the API's fifty-claim limit. Each batch keeps the complete
original input as background, its selected claim texts and types as the exact
scope, and the shared evidence IDs and fetched bodies. Supplemental evidence is
merged once before batching. Every batch passes through the existing grounding,
critic and refinement checks. Run the existing correction annotation once over
successful batches, followed by the existing scope and evidence-gap checks. This
keeps optional correction calls from multiplying with the number of batches.

Concatenate batch results in parent selection order. Missing or failed results
remain insufficient with their original claim type; results outside the batch
scope cannot fill another batch. Preserve successful batches when another fails.
If every batch fails, retain the existing whole-request rule fallback. Generate
the event enrichment, timeline and possibilities once for the combined results.

Keep the existing LLM retry, context, call/token budgets and cancellation
boundaries. Batching does not raise these limits or convert a stopped run into a
successful partial report. There is no public contract change.

## Consequences

- Large rechecks can use model judgment, but require more calls than one batch.
- A failed batch is explicitly logged and conservatively represented; it cannot
  discard successful judgments or create decisive claims without evidence.
- Scripted model tests cover six, seven, thirteen and fifty selected claims,
  batch failures, scope/type preservation, grounding and cooperative stops.
- Offline regression checks do not measure live latency or online accuracy.
