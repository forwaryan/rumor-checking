# Curated COVID-19 health-rumor replay subset

This directory contains eight Simplified Chinese records selected from the
`health_rumors.csv` file published with the ICWSM 2022 paper *Know it to
Defeat it: Exploring Health Rumor Characteristics and Debunking Efforts on
Chinese Social Media during COVID-19 Crisis*.

- Dataset: <https://github.com/Kelaxon/COVID19-Health-Rumor>
- Source revision: `f07382aa9ab38353c80b6c87eb665d7f6733bed2`
- Source file: `data/health_rumors.csv`
- Source SHA-256: `9f1abac0a4de9e74e9ed06a83ea67bcba4dc67550734edc44dcb10254e23587b`
- Repository license: MIT
- Original record IDs: `80401`, `80406`, `80533`, `80723`, `80840`, `80908`,
  `81017`, and `81124`

The subset is intentionally small and manually reviewable. Selection requires
a non-empty claim title, a usable fact-check excerpt, a public HTTP(S) source
URL, and Simplified Chinese text. Seven claims have explicit refuting evidence;
record `80840` is labelled `insufficient` because its source says the asserted
transmission route still required confirmation at the recorded date.

`rumor_type` is an emotional category: `wish` and `dread` mean hope and fear,
**not factual truth and falsehood**. All factual verdicts in this subset are
project-reviewed annotations (`annotation_source=project_review`). Metadata
retains the complete original CSV row, claim, source line/hash, review date,
per-record annotation rationale, and claim/evidence transformation notes.
Confidence is also project-derived; `evaluation.score_confidence=false` prevents
it from being scored as upstream gold. Host domains are recorded separately from
the publisher attributed by the CSV; evidence tier remains B.

| ID | CSV physical line | Original rumor_type | Evidence/annotation note |
| --- | --- | --- | --- |
| 80401 | 39 | wish | Complete publisher excerpt and an explicit bacterial-disinfection claim scope; temporal limitation below. |
| 80406 | 41 | dread | Upstream excerpt is truncated after a complete direct-refutation sentence; truncation remains explicit. |
| 80533 | 55 | wish | Verbatim CSV excerpt provides an infant infection counterexample. |
| 80723 | 71 | wish | Verbatim CSV excerpt contradicts the categorical claim of no reinfection. |
| 80840 | 81 | dread | Summary retains “still requires confirmation”; the source URL is required evidence for `insufficient`. |
| 80908 | 92 | dread | Summary preserves successful delivery as a counterexample to mandatory abortion. |
| 81017 | 98 | wish | Summary retains the environmental conditions and reported five-day surface survival. |
| 81124 | 111 | wish | Adds an explicit 2020-02-05 claim cutoff; summary preserves the fifth-edition guideline's historical statement. |

All eight cases share `topic_group=COVID-19健康谣言` and project
`evaluation_split=development`; related pandemic claims are not divided across
development and holdout. Seven of eight labels are refutations, so the 87.5%
always-refuted baseline must accompany interpretation of aggregate accuracy.
This subset diagnoses interpretation of given historical evidence; it does not
measure representative health-rumor accuracy or end-to-end retrieval performance.

The snapshots preserve declared historical publication dates. Most are excerpts
in the pinned CSV, not independently captured historical publisher-page archives.
They evaluate early-2020 evidence and must not be treated as current medical guidance.

For `80401`, the original CSV stops at “对于细菌...”. A reviewed live publisher
page supplies its complete first key point: 95% alcohol may coagulate surface
proteins while bacteria inside remain viable. The reviewed claim now explicitly
starts with “对细菌消毒时”, matching this direct concentration comparison; the
original unqualified article title is preserved in metadata. Neither the claim
nor the snippet establishes the optimal concentration for every virus.

- Publisher: 腾讯医典, hosted at `vp.fact.qq.com`.
- Declared publication date: `2020-01-28`; page update: `2020-02-03T20:47:27Z`.
- Current capture: `2026-09-13T07:32:32.353269+00:00`.
- Response SHA-256: `7156e31dcc84321b8b5c96fc6dd31fe5ea32df6f15f6746d3f638be0c84a7d56`.
- Extraction: `props.pageProps.initialState.abstract[0].content` (complete first key point).
- `recorded_at` and project `as_of`: `2020-02-04T00:00:00Z`, after the declared update.
- `snapshot_kind=live_page_with_declared_historical_dates` explicitly distinguishes
  the live content from an immutable 2020-01-28 archive. The evidence cutoff uses
  declared historical dates; it does not prove the exact text existed then.

The original CSV snippet and publication date remain in metadata. Review approval
covers traceable source content and the stated scope, not an independent archive
verification. Record `80406` also keeps its upstream truncation marker instead of
inventing missing text; its historical interpretation must not be generalized to
later cold-chain or transmission findings.

The source repository applies MIT to the distributed dataset. The linked
fact-check pages and short attributed evidence excerpts remain subject to their
respective publishers' terms; this subset records those links and does not
claim that third-party content is MIT-licensed.
