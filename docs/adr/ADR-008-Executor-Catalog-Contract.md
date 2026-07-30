# ADR-008: Executor Catalog Contract

Status: Active  
Date: 2026-07-30

## Context

Historically, the Planner returned a free-form string field `suggested_agent` for each
planned task. Examples included role labels such as `ResearchLead`, `Senior Researcher`,
or other display names invented by the LLM.

The Planner payload could be syntactically valid and pass basic schema parsing while
still referencing executors that did not exist in the Runtime registry. The failure
appeared only during workflow execution, when `ExecutorResolver` attempted to resolve
the task and raised `ExecutorNotFoundError`.

This produced formally correct but non-executable workflows: planning succeeded,
`WorkflowRun` was created, and the first task failed at runtime.

The Planning Layer and the Runtime Layer used different semantics for the same concept.
Planner output used `suggested_agent`; Runtime execution used `executor_id`.

## Decision

The platform adopts a strict contract between Planning and Runtime based on a
registered executor catalog.

1. **Canonical field:** `executor_id` is the only runtime identifier for task execution.
   It is used consistently across the Planner payload, domain planning model,
   `WorkflowTemplate`, `TaskDefinition`, and `Task`.

2. **ExecutorCatalog:** `ExecutorCatalog` is the only allowed source of executor IDs
   for the Planner. It is built from `AGENT_EXECUTOR_CAPABILITIES` in
   `application/planner/executor_definitions.py` and injected into the Planner prompt
   and payload validation. The catalog is immutable and lists `executor_id`, executor
   type, and a short capability description.

3. **Planner constraints:** The Planner must select `executor_id` values only from the
   supplied catalog. It must not invent new executor IDs, job titles, or display labels.
   Fields `suggested_agent` and `assign_agent` are removed from the production contract.

4. **Pre-runtime validation:** Unknown or empty `executor_id` values are contract
   violations detected by `PlannerPayloadContract` before `WorkflowRun` creation.
   Invalid Planner output triggers the existing `StructuredOutputGenerator` correction
   retry (strict parser unchanged; no local JSON repair for this case).

5. **Runtime validation:** Runtime does not trust Planner output unconditionally.
   `ExecutorResolver` remains the sole component that resolves `executor_id` to a
   registered executor instance. Unknown IDs raise `ExecutorNotFoundError` with no
   fallback.

6. **Registry alignment:** The composition root registers agent executors and verifies
   that `ExecutorCatalog` IDs match the agent registry keys via
   `_ensure_executor_catalog_matches_registry()`.

### Data flow (implemented)

```
ExecutorCatalog
  → Planner prompt (allowed IDs)
  → LLM JSON payload (executor_id per task)
  → PlannerPayloadContract (semantic validation)
  → ResearchPlan / WorkflowTemplate (executor_id)
  → TaskDefinition / Task (executor_id unchanged)
  → ExecutorResolver → AgentRegistry
```

## Architectural principles

- `executor_id` is the single runtime identifier end to end.
- `suggested_agent` is forbidden in the production contract.
- `assign_agent` is forbidden; use `assign_executor()` on the planning domain model.
- The Planner does not know executor implementations; it knows only catalog capabilities.
- The Planner does not import the infrastructure registry directly.
- Runtime re-validates `executor_id` at resolution time.
- `ExecutorResolver` is the only resolver from `executor_id` to executor instance.

## Consequences

### Positive

- The Planner cannot produce a workflow whose tasks reference unregistered executors
  without failing contract validation first.
- Runtime receives only canonical `executor_id` references aligned with the registry.
- Planning and Runtime can evolve independently behind the catalog contract.
- Failures from invalid executor references are detected before `WorkflowRun` creation
  in the normal Planner path.

### Negative

- `ExecutorCatalog` and `AGENT_EXECUTOR_CAPABILITIES` must be maintained when adding
  or removing executors.
- New executors require centralized registration in the composition root and a
  matching catalog entry; they cannot be introduced implicitly by Planner output.

## Rejected alternatives

The following approaches are explicitly rejected:

- **`suggested_agent`** — free-form LLM agent names decoupled from registry IDs.
- **Free role labels** — job titles or display names (e.g. `ResearchLead`) used for
  resolution.
- **Automatic executor registration** — registering an executor because the Planner
  returned a new string.
- **Fuzzy matching** — mapping unknown labels to nearest registry ID.
- **Fallback executor** — silently substituting a default executor when resolution fails.
- **Dynamic executor creation** — instantiating agents or executors from Planner output.

## Related ADRs

- ADR-003: Task Architecture (Planned) — task model and execution references.
- ADR-007: Agent Architecture (Planned) — agent and executor registration model.

## Notes

Implementation references (current codebase):

- Catalog: `application/planner/executor_catalog.py`,
  `application/planner/executor_definitions.py`
- Validation: `application/planner/payload_contract.py`
- Prompt injection: `application/prompts/builders/planner_prompt_builder.py`
- Registry sync: `application/composition_root.py`
- Runtime resolution: `application/executor_resolver.py`

Commit: `feat(planner): constrain tasks to registered executors`
