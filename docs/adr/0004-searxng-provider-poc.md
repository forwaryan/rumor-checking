# ADR 0004: Optional SearXNG search provider (default-off, AGPL-external)

- Status: Proposed (scaffolded PoC — not live-validated)
- Date: 2026-08-28

## Context

The retrieval sources are domestic-focused (Baidu, 头条, 搜狗微信, 联合辟谣平台).
They cover Chinese rumors well but miss English-language and overseas official
sources — sometimes the only place a cross-border claim is authoritatively
confirmed or debunked. Rec#2 of the riba2534 borrow list points at SearXNG, a
self-hosted metasearch engine, as a supplement and as a failure fallback.

## License confirmation (AGPL-3.0)

SearXNG is licensed AGPL-3.0. The AGPL's network-use clause means that *modifying
and running* SearXNG obliges you to offer its source; it does **not** reach a
separate program that merely calls a SearXNG instance over HTTP.

Decision and confirmation: we integrate SearXNG **only** as an independent,
operator-run HTTP service. We do **not** vendor, copy, import, subclass, or link
any SearXNG source into this repository. `SearxngSearchProvider` issues a plain
HTTP GET to `${SEARXNG_BASE_URL}/search?format=json` and parses the JSON. This
repository is therefore not a derivative work of SearXNG, and no AGPL source-offer
obligation attaches to it. The instance URL is operator-supplied config; nothing
about any instance is hardcoded.

## Decision

Add `backend/app/services/searxng_search_provider.py`, conforming to the existing
provider shape (`name` / `enabled` / `search`). It is enabled only when
`SEARXNG_SEARCH_ENABLED=true` AND `SEARXNG_BASE_URL` is set; otherwise `enabled`
is False and `search` returns `[]`. Every failure path (non-200, transport error,
malformed JSON) degrades to `[]` so a flaky or unreachable instance never breaks a
run. It reuses `reliable_get` for retry/backoff. Registered in
`source_registry` as a default-off supplementary capability so the operator
snapshot and UI list it with an honest availability reason.

## Consequences

- Broader coverage (overseas / English official sources) available behind one
  opt-in switch, without touching the domestic default behavior.
- No AGPL obligation on this codebase (external-service integration only).
- Metasearch results are unknown-authority, so the provider tags them the
  conservative `C` tier and lets downstream authority scoring / semantic rerank
  promote genuinely authoritative domains.

## Honest status / what is NOT done

This is **scaffolded, not live-validated**. No SearXNG instance is reachable to an
unattended agent in this environment, so the provider has not been exercised
against a real instance. The request/response handling follows SearXNG's
documented `/search?format=json` contract and is covered by tests with mocked
HTTP (disabled-paths, JSON parse, transport-error degradation, non-200). The
remaining step before recommending it for real use is a smoke test against a live
instance (stand one up, set `SEARXNG_BASE_URL`, confirm real results parse and the
C-tier defaulting behaves). Same default-off-until-proven discipline as evidence
rerank, the model ledger, and the extractor PoC.
