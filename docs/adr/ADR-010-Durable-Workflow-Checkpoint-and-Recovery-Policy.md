# ADR-010: Durable Workflow Checkpoint and Recovery Policy

## Status

Accepted (PF-04)

## Context

PF-03 introduced repository ports and PostgreSQL adapters, but the production
runtime path (`Agency.start_research`) executed workflows entirely in memory.
PF-04 connects `WorkflowTemplateRepository`, `WorkflowRunRepository`, and
`ExecutionLogStore` to the runtime without introducing queues, worker leases,
or event sourcing.

## Decision

### Checkpoint ownership

- **WorkflowEngine** remains the orchestration owner.
- **WorkflowRuntimeCheckpoint** port is invoked by `WorkflowEngine` and
  `TaskExecutor` at confirmed transition boundaries.
- **WorkflowRuntimePersister** implements the port and delegates aggregate
  persistence to `WorkflowService`.
- **WorkflowCompletionPolicy** remains the terminal outcome owner.

### Source of truth

- **WorkflowRun aggregate snapshot** in `WorkflowRunRepository` is authoritative
  for recovery.
- **ExecutionLogStore** is append-only audit; not used to rebuild state.

### Checkpoint states

Checkpoints occur after:

1. WorkflowRun creation via `repository.create()` (version 0); `workflow_created`
   audit follows immediately. **Create is the durable checkpoint** for the initial
   CREATED aggregate.
2. WorkflowRun → RUNNING (`on_workflow_started`)
3. Scheduler transitions with `SchedulingResult.has_changes` (READY, WAITING, SKIPPED)
4. Task → RUNNING (`on_task_running`)
5. Task completion or failure (`on_task_finished`)
6. Workflow terminal finalization (`on_workflow_finalized`)

Redundant saves are skipped when the durable recovery fingerprint is unchanged.

### Durable recovery fingerprint

The fingerprint is canonical JSON (`sort_keys=True`, Unicode preserved) over:

- workflow status;
- task IDs and statuses in dependency-graph topological order;
- stable dependency-graph representation (`nodes` + `edges`);
- complete `task_results` content (keys and values).

Excluded: persistence version, execution logs, transient `WorkflowContext`
fields, and volatile timestamps unless they are part of durable aggregate state.

### Task result persistence

- Durable task results are JSON-serializable snapshots stored in
  `WorkflowRunRepository.task_results`.
- `capture_task_result()` persists cumulative `shared_state` per completed task.
- Full `WorkflowContext` blobs are not persisted.
- Transient fields (`current_task`, `services`, in-session artifacts) are excluded.
- **Mid-task `shared_state` changes remain non-durable** until task completion.

### Restore ordering

- `restore_runtime_state()` applies cumulative snapshots in dependency-graph
  topological order.
- Only **COMPLETED** tasks with persisted `task_results` participate.
- When snapshots contain the same `shared_state` key, the later topological
  snapshot wins (deterministic tie-break follows `TaskDependencyGraph` insertion
  order for independent tasks).

### Recovery semantics

- `DurableWorkflowService.resume_research(run_id)` reloads aggregate + task results.
- Terminal runs return without executing tasks.
- Non-terminal runs restore `shared_state` and continue via `WorkflowEngine.run`.
- **PAUSED** resume is explicitly out of PF-04 scope.

### Interrupted RUNNING task policy

Single-process recovery without leases:

- RUNNING tasks discovered on resume are marked **FAILED** with a documented
  recovery reason.
- They are **not** automatically re-executed.
- Dependents follow normal scheduler skip/fail cascade.

### Exception precedence

1. **CheckpointPersistenceError** (aggregate save failure) — critical; may wrap
   executor error as `__cause__`.
2. **Executor/runtime error** — re-raised after successful failure checkpoint
   (AUD-016 preserved).
3. Execution log append — best-effort; failures are swallowed **after** a
   successful checkpoint. Audit events are never emitted for unpersisted state.

### Audit ordering

For runtime checkpoints: **aggregate save first**, best-effort audit append
second (`workflow_started`, `task_started`, scheduling skips, task outcomes,
workflow terminal events, recovery failures).

### Idempotency

- Duplicate `run_id` create → `DuplicateEntityError`.
- Stale `expected_version` → `ConcurrentModificationError`.
- Terminal resume → no-op execution.
- Duplicate log `event_id` → idempotent no-op (port contract).
- `workflow_resumed` uses stable identity `{run_id}:workflow_resumed:{resume_version}`
  where `resume_version` is the persisted aggregate version at resume entry.
  Timestamp is event data only.

### Transaction boundaries

- One WorkflowRun checkpoint = one repository transaction.
- Execution log append uses a separate transaction (best-effort).
- Template snapshot + run create are sequential without cross-repository UnitOfWork;
  orphaned template snapshots are acceptable immutable history.

### Backend policy

- Durable execution enabled for `memory` and `postgresql` backends.
- `file` backend keeps ephemeral in-memory workflow runtime (no false durability claim).

## Alternatives rejected

- **Step-by-step engine control in service** — duplicates orchestration logic.
- **Opaque WorkflowContext blob persistence** — breaks ADR-009 decomposition.
- **Automatic RUNNING task retry on resume** — unsafe without idempotency/leases.
- **Generic UnitOfWork** — scope limited to single aggregate checkpoints in PF-04.

## Deferred

- Background workers, task leases, distributed locking, queues (Redis/Celery).
- PAUSED workflow operator resume.
- Cross-repository atomic template+run creation.
