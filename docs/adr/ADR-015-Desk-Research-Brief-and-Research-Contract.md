# ADR-015: Desk Research Brief and Research Contract

**Status:** Active (DR-01)  
**Date:** 2026-07-29  
**Deciders:** Platform / Desk Research vertical  

## Context

PF-01 through PF-08 established durable workflow execution, HTTP API, worker orchestration, idempotent external submission, and API-key ownership. The first Desk Research product stage requires a canonical research input contract without duplicating Project, Planner, WorkflowTemplate, or TaskDefinition aggregates.

Previously, research submissions used an ad hoc `ProjectBrief` shape (legacy fields such as `client`, `project_title`, `business_problem`) stored on `Project.brief` and passed to the planner as four free-form prompt variables.

## Decision

### 1. Canonical model: `ResearchBrief`

Introduce `ResearchBrief` as a **frozen domain value object** owned by `Project.research_brief`.

Fields (all have Desk Research purpose):

| Field | Semantics |
|---|---|
| `title` | Human-readable research title |
| `business_question` | Decision/problem the research supports |
| `objectives` | What the research must determine |
| `geography` | Markets/territories in scope |
| `market` | Category/industry/product domain |
| `target_entities` | Companies, brands, audiences, technologies, etc. |
| `timeframe` | Historical/current/future period |
| `constraints` | Known research constraints |
| `deliverables` | Expected outputs |
| `language` | Primary report language (default `en`) |
| `context` | Client/business background |
| `known_information` | Client-supplied facts not to re-discover |
| `exclusions` | Explicitly out-of-scope subjects |

`domain/project_brief.py` remains as a **legacy import alias** (`ProjectBrief = ResearchBrief`) for transitional code paths only. See **Legacy compatibility removal** below.

### 2. Project relationship

- **Project** is the business container (identity, owner, artifacts/knowledge references).
- **ResearchBrief** is research intent/specification on the project.
- No second project aggregate or separate `research_briefs` table.

### 3. Research submission and current brief semantics

`POST /projects/{id}/research` is the authoritative moment for setting the project's **current** research brief:

1. Request body is normalized and validated into a canonical `ResearchBrief`.
2. The validated brief is assigned to **`Project.research_brief`** (replacing any prior current brief on that project).
3. The project is persisted with the updated current brief before planning proceeds.
4. The planner consumes `Project.research_brief` to produce a `WorkflowTemplate`.
5. That template stores an immutable **`research_brief_snapshot`** copied from the brief at planning time.

**Current vs snapshot:**

| Location | Mutability | Meaning |
|---|---|---|
| `Project.research_brief` | Mutable on each new research submission | Latest client intent for the project |
| `WorkflowTemplate.research_brief_snapshot` | Immutable once the run is created | Exact brief that produced that run |

Editing `Project.research_brief` on a later submission does **not** change the meaning of an already-created `WorkflowRun`; audit and replay use the template snapshot.

### 4. Persistence

- PostgreSQL: continue JSONB column `projects.brief`; mapper reads/writes canonical `ResearchBrief` JSON and maps legacy shapes on load via `ResearchBrief.from_dict()`.
- Memory backend: full DR-01 support.
- File backend: structured `research_brief` round-trip in `project.json` (legacy `brief` key accepted on read).

No new Alembic migration required (schema unchanged).

### 5. API contract

- Structured `ResearchBriefRequest` on `POST /projects/{id}/research` only (option B).
- `POST /projects` accepts project identity/metadata only.
- Responses include `research_brief` on start/run payloads when a snapshot exists.
- Legacy brief JSON accepted temporarily via request coercion to canonical fields (deprecated; not a second long-term format).

### 6. Validation

Application-layer `validate_research_brief()`:

- `title` non-empty
- `business_question` non-empty
- at least one objective
- `language` required (defaulted to `en` by normalizer)

Normalization trims strings, deduplicates list values, defaults language. Errors map to HTTP **422** via `ValidationError` handler.

### 7. Planner integration

`PlannerPromptBuilder` derives prompt variables from all structured brief fields. No planner behavior redesign in DR-01.

### 8. ResearchQuestion boundary (DR-02 — not implemented in DR-01)

DR-01 establishes the **input** contract only (`ResearchBrief`). DR-02 will introduce a **ResearchQuestion** semantic planning layer between brief and task definitions.

Planned minimal shape (DR-02, not present in codebase until that stage):

- `id`
- `question`
- `objective_ref` (optional link to a brief objective)
- `priority`
- `rationale` (optional)

DR-01 does **not** define or persist `ResearchQuestion`. The planner continues to output `TaskDefinition` entities via `ResearchPlan`. DR-02 will map planner/design output to `ResearchQuestion` without forcing a second planning system in DR-01.

### 9. Idempotency (PF-07)

`compute_research_request_fingerprint()` hashes normalized `ResearchBrief.to_fingerprint_dict()` plus `project_id`. Correlation/source/timestamps excluded.

### 10. Authorization (PF-08)

Unchanged: only project owner may submit research or read runs. No duplicated auth logic.

### 11. Legacy compatibility removal

The `ProjectBrief` import alias and API request coercion from legacy field names (`project_title`, `business_problem`, etc.) are **temporary**.

**Remove when all of the following are true:**

1. All in-repo clients use canonical `ResearchBrief` field names (`title`, `business_question`, `objectives`, …).
2. All `examples/n8n/` workflows send canonical brief JSON.
3. No external integrator documentation references legacy field names.

After removal: delete `domain/project_brief.py`, drop legacy coercion in `ResearchBriefRequest`, and remove `ResearchBrief.from_dict()` legacy mapping once stored JSON is migrated or deemed acceptable to reject.

## Consequences

**Positive**

- Single canonical Desk Research input contract
- Run audit trail via immutable template snapshot
- Structured planner input without WorkflowEngine redesign
- No speculative domain types in DR-01

**Negative / limits**

- Legacy `ProjectBrief` field names deprecated at API boundary until removal condition met
- File backend still does not round-trip all Project nested aggregates (only `research_brief` added in DR-01)
- Web search, evidence extraction, analysis/writer/reviewer remain out of scope

## References

- ADR-013 (idempotency fingerprint semantics)
- ADR-014 (ownership)
- DR-02 (ResearchQuestion / Research Design — planned)
