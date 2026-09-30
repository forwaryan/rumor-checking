# 0010 — Unified public fetch and execution boundaries

- Status: Accepted
- Date: 2026-09-13

## Context

Supplementary evidence used pinned public connections while ordinary page fetches
still trusted automatic redirects and a separate DNS precheck. Rechecks could
reuse old material, legacy endpoints bypassed durable budgets, and thread-pool
timeouts waited silently for running workers before becoming visible.

## Decision

Share one public-only, IP-pinned, TLS-verified and byte-bounded HTTP GET transport.
Revalidate every redirect, ignore environment proxies and credentials, and reject
encoded bodies instead of claiming that post-decompression checks bound memory.
Keep rendered fetching optional and fail closed behind bounded public HTTP
bridging and a separately supervised browser process.

Make freshness a request-scoped policy for rechecks, including failure paths.
Version verdict-cache identities by request strategy and relevant configuration;
do not silently reuse a fast report for a deep or differently sourced request.

Publish control-plane timeout/cancellation immediately, but retain execution
locks and capacity until all shared-state workers drain. Do not abandon mutable
threads or pretend in-flight remote calls can be retracted. Legacy JSON/NDJSON
entrypoints adapt the existing durable manager instead of owning another runtime.

Bound request bytes before JSON parsing and input characters in the shared model.
Preserve the input rather than silently shortening it. Update public schemas,
frontend types and input checks together.

## Alternatives considered

- Preflight DNS checks without pinned connections leave a time-of-check gap.
- Returning immediately from abandoned worker threads permits late mutations.
- Independent limits in legacy endpoints drift from the durable run lifecycle.
- Increasing replay tolerances would hide changed execution behavior rather than
  testing the intended cache/fetch semantics.

## Consequences

Some compressed, redirected rendered or authenticated pages are intentionally
unavailable. Browser controls are not a replacement for host network isolation.
An execution can be visibly stopped while its existing calls drain under the
retained lock. No additional dependencies or Agent framework are introduced.

See [execution safety](../execution-safety.md) for limits and compatibility.
