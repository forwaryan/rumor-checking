# 0016 — Optional JoyCode model transport

- Status: Accepted
- Date: 2026-10-26

## Context

The project already offers DeepSeek models behind its standard Bearer-authenticated
OpenAI-compatible gateway. Magpie's active JoyCode provider offers
`DeepSeek-V4.1-Flash`, but the same model ID sent to the existing gateway returned
HTTP 400. Its installed adapter uses OpenAI chat-completion bodies with a signed
JoyCode route, a locally stored login ticket, and authenticated account identity.

## Decision

Keep the existing model picker, retry policy, evidence requirements and default
model. Route only explicitly listed `JOYCODE_MODELS` through a small JoyCode
transport. Read the existing Magpie login file at request time, fetch account
identity, sign each request, and send the same completion body with the required
identity fields. Both streamed agent calls and non-streamed judgment/extraction
use this transport. No ticket, signing configuration, gateway address or account
identity is committed to the repository or returned by the model-list endpoint.
The local environment selects models and supplies the route and signing
configuration; without it the existing gateway path is unchanged.

## Consequences

- The new model can be selected without changing the public JSON contract or
  moving default analysis to JoyCode.
- JoyCode login expiry, gateway changes or a missing local configuration cause
  a model failure and use the existing failover or conservative fallback path.
- Tests cover signing, identity, missing login, model routing and offline
  regressions. A short live completion verified both streamed and non-streamed
  responses; this does not measure end-to-end fact-checking accuracy.
