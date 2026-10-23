# 0014 — Parallel supplementary retrieval

- Status: Accepted
- Date: 2026-10-24

## Context

The default retrieval path waited for four independent supplementary searches in
sequence. Their selection steps are order-dependent: a later source must not
reintroduce an independence key already accepted from an earlier source.

## Decision

Fetch enabled Xiaohongshu, Toutiao, Sogou Weixin and Piyao sources concurrently
using the existing thread-pool and copied-context patterns, with at most four
workers. Avoid a thread pool when zero or one source is enabled. Select and merge
in the original source order, preserving bundle metadata and independence checks.
The primary retrieval and cache path still runs first; official-source boosting
runs after the merged results are available. A supplementary search failure
retains the other sources. Cancellation and run-budget stops propagate.

Each worker receives its own copied Context so progress events, retrieval stage,
trace parent and run control follow the calling request. The primary bundle is
only replaced while merging completed searches in the calling thread.

## Consequences

- Supplementary network latency can overlap without changing source precedence.
- Existing provider enablement, source filters, enrichment and failure behavior
  remain in use; there is no new dependency or public contract change.
- Barrier-based offline tests verify concurrency, reverse completion order,
  metadata, failure isolation and control propagation without speed thresholds.
- Live latency and retrieval-quality gains remain unmeasured.
