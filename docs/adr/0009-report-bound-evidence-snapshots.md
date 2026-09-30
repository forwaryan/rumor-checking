# 0009 — Report-bound evidence snapshots and citation anchors

- Status: Accepted
- Date: 2026-09-13

## Context

Historical reports already retain snippets and quotes, but neither identifies the
exact source text behind a quote. A changed summary can also look like a changed
source. Existing fetch caches and passage offsets are useful inputs, not immutable
source identities.

## Decision

Capture bounded original retrieval snippets and extracted page text at evidence
I/O boundaries. A request-local, thread-safe collector follows the existing
execution context. Attach only cited-source snapshots to the final report and
reuse existing report persistence, access boundaries and lifecycle.

Bind quotes only by exact substring matching against captured text. Preserve the
distinction between search snippets, fetched text, cache reads and restored text.
Use Unicode codepoint offsets, content hashes and extractor-versioned identities.
Hash/identity validation and frontend range checking protect the binding; neither
claims to prove factual truth or authorship.

Compare retained page text only for matching URLs and extractors within selected
claims. Retain the existing report-field comparison separately. Restore final
snapshot metadata from completed checkpoints; label reconstructed old text
explicitly instead of inventing historical fetch metadata.

Extend structured evidence goals for bounded explicit date, quantity and scope
patterns. Existing negative evidence can cover an attribute; a different number
must not erase a legitimate refutation. Unrecognized phrasing retains its current
path, and no coverage rule upgrades a verdict.

## Alternatives considered

- A global permanent snapshot service would need a separate access and retention
  model before it could be exposed safely.
- Treating generated report snippets as original pages manufactures provenance.
- Re-fetching when opening an old report loses the historical source version.
- Fuzzy quote matching can hide paraphrases and accidental alterations.

## Consequences

Reports become larger but have fixed per-source and per-report text budgets.
Snapshots represent retained extracted text, not complete archived HTML or
cryptographically authenticated publisher records. No new dependencies, framework,
scheduler or cross-case memory are introduced.

See [evidence snapshots](../evidence-snapshots.md) and [evidence goals](../evidence-goals.md).
