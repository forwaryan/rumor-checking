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
- `evals/live_replay/seed/`: versioned supplied-evidence verdict regressions.
- `evals/live_replay/hard/`: harder replay corpus for regressions around timeliness, subject alignment, and conflicting evidence.
- `evals/live_replay/cfever_curated/`: 24 traceable public cases, eight per label, with disjoint development/holdout topics.
- `evals/live_replay/covid19_health_rumor_curated/`: eight traceable Simplified Chinese historical health-rumor cases.
- `evals/live_replay/context_challenge/`: eight synthetic coverage cases including nonempty but insufficient evidence.
- [Dataset quality](dataset-quality.md): source review, strict URL-group scoring, audit and partition rules.
- [Evidence goals](evidence-goals.md): structured gaps, scoped supplementation and conservative stopping.
- [Evidence snapshots](evidence-snapshots.md): captured source text, exact citation anchors and scoped source-text changes.
- [Model-call observability](model-call-observability.md): per-attempt usage, context changes, parent spans and Phoenix.
- [Execution safety](execution-safety.md): public fetch boundaries, fresh rechecks, unified budgets and input limits.
- [Deep Agent replay](../evals/agent_replay/README.md): deterministic orchestration with recorded external responses.
- [CFEVER adapter](../evals/external/cfever/README.md): generate a balanced Chinese fact-verification replay corpus locally.
- [Contributing](../CONTRIBUTING.md): development workflow and validation commands.
- [Security](../SECURITY.md): vulnerability and sensitive-data policy.

## Decisions

- [ADR index](adr/README.md): durable architectural decisions and proposal template.

When documentation conflicts with executable contracts or tests, treat `contracts/`, tests, and current code as the source of truth and update the stale document in the same change.

- [GitHub 参考与准确性、检索、观测改进](github-improvements-2026-09.md)
