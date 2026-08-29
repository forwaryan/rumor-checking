# Documentation Index

## Start here

- [Project README](../README.md): capabilities, setup, runtime modes, and public usage.
- [Current code architecture](current-code-architecture-guide.md): end-to-end pipeline and implementation map.
- [Backend guide](../backend/README.md): API, configuration, and backend operations.
- [Frontend guide](../frontend/README.md): UI development and frontend commands.
- [Demo guide](../DEMO.md): repeatable demonstration flow.

## Engineering contracts

- [Public schemas](../contracts/README.md): backend/frontend contract ownership and drift checks.
- [Minimal evaluation set](../evals/minimal_v1/README.md): deterministic component fixtures.
- `evals/live_replay/seed/`: versioned end-to-end replay corpus.
- `evals/live_replay/hard/`: harder replay corpus for regressions around timeliness, subject alignment, and conflicting evidence.
- [Contributing](../CONTRIBUTING.md): development workflow and validation commands.
- [Security](../SECURITY.md): vulnerability and sensitive-data policy.

## Decisions

- [ADR index](adr/README.md): durable architectural decisions and proposal template.

When documentation conflicts with executable contracts or tests, treat `contracts/`, tests, and current code as the source of truth and update the stale document in the same change.
