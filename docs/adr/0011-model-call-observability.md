# 0011 — Observe model attempts within the existing run trace

- Status: Accepted
- Date: 2026-09-30

## Context

Agent spans and the model ledger did not cover all HTTP attempts. Streaming network failures could bypass the ledger, structured/web-search calls discarded usage, and cumulative agent counters could be counted repeatedly. Existing Phoenix spans represented tools rather than individual model calls.

The claude-tap request viewer demonstrates useful per-request, context-change, and usage diagnostics. Its local proxy sessions and raw-body storage do not directly match our run identity, existing diagnostics API, or desensitized ledger.

## Decision

Extend the existing runtime with a request observer around each Chat Completions send. Use ContextVars and copied worker contexts to associate each attempt with its run and parent span. Keep a single exporter across fixed/agent/fallback paths and finalize once at the outer request boundary.

Record reported usage, timing, status, response counts and whitelisted request structure. Request comparisons use run-local keyed hashes in memory; neither raw content nor fingerprints are exported. Missing usage remains explicitly unknown. Preserve count-only synthesis context estimates separately from actual provider usage.

Emit LLM spans to Phoenix using the existing exporter. Add details to the existing span tree without changing the public Report contract. Retain default-off trace and ledger collection. Request streamed usage by default with a compatibility switch for gateways that reject stream_options.

## Alternatives considered

- A mandatory reverse proxy adds another failure/deployment point and does not provide business parent identity automatically.
- Persisting raw requests in the regular trace changes the existing privacy boundary and is unnecessary for count/change diagnostics.
- Replacing the agent runtime or observability backend duplicates established functionality.

## Consequences

Each actual send, including retries and failures, has an independent call ID and can be correlated across local traces and the ledger. Cache usage is not double-counted and hook totals use increments rather than cumulative snapshots.

These diagnostics do not provide complete prompt diffs or infer unknown usage. A successful HTTP/content observation does not establish valid model output or evidence quality. Historical checkpoint attempts are not merged into a new execution trace. Live gateway and Phoenix interoperability still require environment-specific validation.

## References

- [claude-tap reviewed revision](https://github.com/liaohch3/claude-tap/tree/4cc867d2e9689a7e5ca8623c67cabcb3fb7a456f)
- [Model-call observability guide](../model-call-observability.md)
