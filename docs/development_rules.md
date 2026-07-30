# AI Research OS Development Rules

## General

- Prefer minimal, focused changes aligned with existing layer boundaries.
- Do not add new architectural abstractions without an ADR when the decision is significant.
- One sprint = one completed, reviewable unit of work.
- After behavioral changes, run the test suite (`python run_tests.py`).

## Architecture Boundaries

- **Domain** (`domain/`) — entities, value objects, state machines; no LLM imports.
- **Application** (`application/`) — workflow engine, planner service, executor resolution.
- **Agency** (`agency/`) — application facade; orchestrates planning and workflow start.
- **Agents** (`agents/`) — concrete executors registered by `executor_id`.
- **Infrastructure** (`infrastructure/`) — LLM, persistence, external adapters.

Dependency direction: Business → Workflow → Execution → Infrastructure.

## Planner and Executors

- Planner tasks use **`executor_id`** only (see [ADR-008](adr/ADR-008-Executor-Catalog-Contract.md)).
- Do not reintroduce `suggested_agent` or `assign_agent` in contracts.
- **ExecutorResolver** is the only place that resolves `executor_id` to an executor at runtime.
- New agent executors must be registered in the executor registry with a stable ID.

## Workflow Runtime

- **WorkflowTemplate** / **TaskDefinition** — immutable definitions.
- **WorkflowRun** / **Task** — mutable runtime instances.
- **WorkflowEngine** owns `WorkflowRun.status`.
- **TaskScheduler** selects ready tasks; **TaskExecutor** runs them — do not merge these roles.

## Prompts

- Prompt templates live under `application/prompts/` and `prompts/`.
- Prompt names may be referenced from `constants/prompts.py`.

## Domain

- Entities live in `domain/`.
- Value objects live in `domain/value_objects/`.
- Runtime state machines live in `domain/runtime/`.

## Tests

- Application and domain behavior should have tests under `tests/`.
- Do not change tests when performing documentation-only tasks.

## Documentation

- Keep `architecture/` and `docs/architecture.md` aligned with production code.
- Record significant architectural decisions in `docs/adr/`.
