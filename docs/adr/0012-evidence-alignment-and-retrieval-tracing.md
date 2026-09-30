# 0012 — Align quantitative evidence and trace retrieval decisions

- Status: Accepted
- Date: 2026-09-30

## Context

The numeric verdict rule compared quantities across unrelated attributes, so a salary or employee total could overturn a correctly stated hiring count. The LLM judge could not represent the existing `conflicting` verdict. Retrieval deduplication lowercased complete URLs, merged missing URLs, and allowed ambiguous provider IDs to collapse unrelated reports. Existing LLM spans did not explain cache hits, filtering, supplementary provider failures, or retrieval result changes.

## Decision

Keep the current runtime and implement three bounded improvements:

1. Compare quantitative evidence conservatively using measurement units and local claim attributes/scope. Normalize equivalent numeric scales. Keep real corrections and unresolved source disagreement distinct. The LLM prompt and parser support all four factual verdicts and require aligned subject, attribute, time, scope and units.
2. Use a dedicated URL comparison identity while preserving original fetch/display/citation URLs. Normalize scheme/host/default ports, remove known marketing parameters and ordinary anchors, preserve path case, business query order and hash routes. Resolve explicit duplicate references only when unambiguous. Title similarity alone cannot erase distinct content; repeated merging preserves known provenance.
3. Record retrieval rounds, queries, cache operations, selection, supplementary sources and official-source searches under existing trace contexts. Use OpenInference `CHAIN` and `RETRIEVER` kinds. Export only bounded metadata and counts; no added prompt, search query, document body, URL or exception-message capture. Frontend details explain counts, unknown fields and partial failures.

## References

Reviewed pinned GitHub sources; implementation uses existing dependencies and independently written code:

- [DEFAME](https://github.com/multimodal-ai-lab/DEFAME/tree/0d5c2eb5e07cfa8a673351e765c9c576070cdd6c), Apache-2.0: distinct insufficient/refuted/conflicting meanings and subject-specific evidence questions.
- [w3lib](https://github.com/scrapy/w3lib/tree/537c5d46455ae8b2c67b53fc03b36ef1da8c4837), BSD-3-Clause: normalize URL components separately and preserve case-sensitive paths.
- [OpenInference](https://github.com/Arize-ai/openinference/tree/732eec1b0d7e5c753f22ea9ac328132003372dd1), Apache-2.0: retrieval span semantics and hierarchy.
- [Haystack](https://github.com/deepset-ai/haystack/tree/f4e004c34cbc724b3ffb026debdf7a0541e4a21f), Apache-2.0: document identity and ranked-list fusion. RRF is deferred: this project currently sorts provider results chronologically, so the retained order is not a valid search rank. Adding fusion requires preserved ranks and a labeled retrieval evaluation.

## Consequences

Conservative deduplication may retain more near-duplicate reports, but preserves conflicting evidence. Source independence remains a separate signal, not a claim that different URLs necessarily corroborate independently. Quantitative matching remains a deterministic heuristic, not general semantic understanding. The tests must retain true numeric contradictions and avoid allowing unaligned quantities to become lexical support.

Selection spans describe individual stages; their counts must not be summed across parents and children. The round reports final bundle counts. `partial` means a child operation failed, even if stale-cache fallback recovered useful results. Observability failures must not change retrieval output or cancellation behavior.

No public Report contract or agent framework changes. Validation must combine new adversarial regressions, existing replay corpora and complete local gates; supplied-evidence replay does not establish live search recall or overall real-world accuracy.
