# 0005 — Persist analysis runs independently of browser connections

- Status: Accepted
- Date: 2026-09-13

## Context

The Agent runtime already saves and resumes checkpoints. The browser used a request-scoped stream and created a new analysis after refresh, so users could not reattach to that progress or retrieve the completed report.

## Decision

Add a local SQLite run store with detached execution, monotonically numbered events, stored reports, and explicit recovery of interrupted requests. Keep existing synchronous and streaming APIs compatible. Reuse the existing Pipeline and checkpoint implementation with the same server-generated run ID.

All HTTP creation endpoints override a client-supplied `request_context.run_id`; legacy endpoints cannot target the checkpoint namespace of an existing durable run. Resume reads the stored original request through the dedicated run API.

Use atomic database transactions, capacity limits, and renewable ownership leases to coordinate workers sharing one local database. Additionally hold a per-run OS execution lock throughout the complete Pipeline lifecycle (`flock` on POSIX, `msvcrt.locking` on Windows). Acquire that lock while holding the database transaction before reserving a new owner. A completed execution is independent of whether a claim is supported, refuted, conflicting, or insufficient.

## Alternatives considered

- Browser-only persistence cannot reconnect to backend progress or survive a backend restart.
- A new durable Agent framework or distributed queue introduces dependencies and replaces behavior already present in the custom runtime.

## Consequences

- Refresh and network reconnection can reuse one analysis without duplicate creation.
- Required request and result data remain in ignored local storage with bounded retention; random run links must be treated as private.
- Interrupted requests require explicit resume. Checkpoint availability determines whether completed steps are skipped.
- A lease can expire while the old process is paused or still waiting for an external call. Lease fencing alone protects database writes but cannot fence the existing checkpoint store. The execution lock prevents a replacement Pipeline from starting until the previous Pipeline exits, so their checkpoint writes cannot overlap. Resume returns retryable `409 run_still_executing` while that lock is held; process death releases it automatically.
- Expired but still executing runs keep their records, lock files, and capacity reservation. Cleanup checks and lock-file deletion are serialized by the same database transaction used to acquire execution locks. Shared local storage must support OS file locks; this is not a multi-host coordination mechanism.
- Private run responses retain the full original `raw_input` separately from the display preview so refreshing cannot truncate a later investigation request. The input does not become part of the task URL.
- Already-issued external calls cannot be rolled back. This is not a distributed exactly-once execution guarantee.

## References

- [12-factor-agents: execution state and pause/resume](https://github.com/humanlayer/12-factor-agents)
- [Multica: run completion and issue completion](https://multica.ai/docs/tasks#run-completion-and-issue-completion)
- [User and deployment guide](../durable-analysis.md)
