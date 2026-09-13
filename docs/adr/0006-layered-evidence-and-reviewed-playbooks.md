# 0006 — Budget layered evidence and reuse reviewed checking procedures

- Status: Accepted
- Date: 2026-09-13

## Context

Evidence summaries were budgeted separately from fetched page bodies and fixed user content. Appending body prefixes could exceed the estimated context limit and miss a relevant correction near the end of a page. The model ledger measured usage but did not describe the composition of the synthesis context.

## Decision

Build a source index, snippet excerpts, and selected original page passages under one complete prompt budget. Preserve source IDs and offsets and make omissions visible as counts. Keep source text untrusted and preserve existing grounding and conservative verdict rules.

Attach immutable per-request heuristic counts to the synthesis prompt and allow only numeric fields in ledger diagnostics. Recheck the total budget when a completion attempt uses another model.

Load bounded, approved procedure files by relevance to the current question. Store only draft outcome counters after completed runs; do not automatically promote observations or historical verdicts into instructions or evidence.

## Alternatives considered

- Appending all retrieved text increases cost and can exceed model limits.
- Using only a generated summary loses the distinction between navigation and original evidence.
- Importing a memory framework or reusing prior verdicts adds complexity and risks reinforcing stale or incorrect facts.

## Consequences

- Long sources can contribute relevant or contrary passages beyond their opening paragraphs.
- Model context size and token estimates remain configuration and heuristic assumptions, not tokenizer guarantees.
- Reviewed methods can accumulate without automatically learning factual conclusions.
- Accuracy and cost improvements must be established through separate replay comparisons; implementation tests do not establish those improvements.

## References

- [OpenViking layered context](https://github.com/volcengine/OpenViking)
- [Hermes procedural memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)
- [Context diagnostics and playbook guide](../evidence-context.md)
