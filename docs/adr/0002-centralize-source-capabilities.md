# ADR 0002: Centralize retrieval source capabilities

- Status: Accepted
- Date: 2026-08-27

## Context

Retrieval providers are created in the retrieval service, while `/search-sources`
previously duplicated a subset of their names and availability rules. This made
the frontend list incomplete and collapsed three different states—configured,
locally available, and enabled—into one boolean.

## Decision

Maintain a dependency-free `SourceCapabilityRegistry` in
`backend/app/services/source_registry.py`. It describes every primary,
supplementary, and derived retrieval capability with explicit configuration and
availability states.

`GET /api/v1/search-sources` remains backward compatible and returns selectable
sources. `GET /api/v1/source-capabilities` exposes the complete operator-facing
snapshot. Registry checks must be local and cheap; they must not call remote
services or expose credentials, cookies, gateway hosts, or internal endpoints.

`backend/scripts/source_doctor.py` presents the same snapshot for local and CI
diagnostics. Its default exit code requires an active primary provider, while
strict mode also rejects unavailable optional sources.

The registry is descriptive in this first increment. It does not construct
providers or change retrieval routing.

## Consequences

- UI metadata and operator diagnostics share one source of truth.
- Missing local prerequisites such as `xhs-cli` can be distinguished from a
  deliberately disabled source.
- Future SearXNG or Crawl4AI experiments gain a consistent capability contract.
- Runtime provider construction remains separate until a later, independently
  tested migration.
