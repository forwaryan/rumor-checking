# ADR 0003: LLM-facing body extractor (PoC, default-off)

- Status: Proposed (PoC — not enabled)
- Date: 2026-08-27

## Context

Evidence body text is fetched by `page_fetcher`, which strips tags with regex and
then picks the "top" paragraphs by a scorer that rewards digits, Chinese runs,
and length (`_extract_key_paragraphs`). That heuristic has no notion of page
*structure*: a long navigation column or footer full of digit-laden links can
outscore the real article lede, so the text handed to the LLM verdict/synthesis
step is contaminated with boilerplate.

Rec#3 in the riba2534 borrow list points at Crawl4AI's "fit markdown" idea. We do
NOT want its heavy dependency surface (headless browser, optional model). The one
transferable idea that needs nothing beyond the standard library is **link-density
pruning**: rank candidate blocks by the ratio of anchor-text to total text and
drop the link-heavy ones as navigation.

## Decision

Add `backend/app/services/llm_facing_extractor.py` — a pluggable, default-off,
stdlib-only (`html.parser`) extractor:

- `extract_main_text(html)` walks the DOM, drops boilerplate subtrees
  (`script/style/nav/header/footer/aside/form`), accumulates text per block while
  tracking link density, and keeps only substantial, low-link-density blocks in
  document order.
- `compare_extractors(...)` scores it against the current baseline on the same
  HTML for the three PoC metrics — effective-body-rate, citation-locatability,
  and (added) boilerplate-free-rate — plus extraction latency.

It does **not** replace `page_fetcher`. Nothing in the live path calls it; it is
wired only into tests and the comparison harness. No new dependency, no torch, no
network.

## Consequences

Measured on the fixture corpus (nav-heavy article + clean article):

| extractor | eff_body | citation | boilerplate-free | latency |
|-----------|----------|----------|------------------|---------|
| baseline  | 0.50     | 1.00     | 0.50             | ~0.05ms |
| candidate | 0.00     | 1.00     | 1.00             | ~0.09ms |

Reading:

- **Clear win — cleanliness.** The candidate leaks zero boilerplate (1.00 vs
  0.50): nav/footer never reaches the body. Both locate claim key terms (citation
  1.00), but the candidate does so without the surrounding noise.
- **Tradeoff — brevity vs the metric.** The candidate's effective-body-rate is
  0.00 here because on the short clean article it returns just the one crisp
  sentence, which falls under the 60-char "effective" bar. That is a *metric*
  limitation (the bar penalizes legitimately short bodies), not an extractor
  failure — the extracted sentence is correct and complete.
- **Latency.** ~2× slower but still sub-millisecond; irrelevant next to network
  fetch time.

**Recommendation: promising, not yet a drop-in.** The structural extractor gives
materially cleaner LLM-facing text at negligible cost. Before enabling it in the
live path we want (a) a larger, real-URL sample corpus, and (b) an effective-body
threshold that does not punish short valid articles. Until then it stays a
default-off PoC with a reproducible comparison, consistent with how evidence
rerank and the model ledger were introduced.
