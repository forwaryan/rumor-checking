# 0001 — Retain the custom agent runtime

- Status: Accepted
- Date: 2026-08-23
- Owners: project maintainers

## Context

The backend already implements planning, tool execution, retry limits, token and wall-clock budgets, cancellation, permission checks, checkpoint resume, trace recording, and multi-agent orchestration. Mature external frameworks such as OpenAI Agents SDK, LangGraph, PydanticAI, and Google ADK provide overlapping runtime capabilities.

A wholesale migration would replace tested domain-specific behavior without directly addressing the project's larger gaps: evaluation provenance, contract validation, guardrails, standardized telemetry, and external tool interoperability.

## Decision

Keep the current runtime and adopt external patterns incrementally. Prefer compatibility layers and narrow integrations—MCP tools, OpenTelemetry semantic attributes, guardrail boundaries, and optional AG-UI events—over framework replacement.

## Consequences

- Existing tests and domain behavior remain stable.
- Runtime improvements must be maintained locally.
- External interoperability is added explicitly rather than inherited from one framework.
- New dependencies require a concrete capability gap and an ADR.

## Alternatives considered

- Migrate to LangGraph for durable graphs and checkpoints.
- Migrate to OpenAI Agents SDK for handoffs, guardrails, and tracing.
- Migrate to PydanticAI or Google ADK for typed agent/tool abstractions.

These options currently duplicate more functionality than they add.

## Revisit when

Re-evaluate when runs must survive process restarts across multiple instances, remain active for minutes or hours, wait for human approval, coordinate independently deployed agents, or support multiple interchangeable runtime backends.
