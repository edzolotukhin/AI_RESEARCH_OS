# ADR-019: Desk Research Analysis, Findings and Insights

## Status

Accepted — DR-05 implemented (pending owner review)

## Context

DR-04 delivers durable, run-scoped, grounded **Evidence** bound to Source
snapshots. DR-05 introduces the first analytical layer: **Findings** and
**Insights**, without report writing (DR-06).

## Decision

### Semantic boundary

| Entity | Role | Example |
|--------|------|---------|
| **Evidence** | Grounded factual material from a Source | "Company X reported 23% revenue growth in 2025." |
| **Finding** | Analytical conclusion supported by Evidence | "Company X is growing materially faster than the category benchmark." |
| **Insight** | Interpretation/implication of Findings in research context | "Company X may be gaining competitive momentum, making it a priority competitor to monitor." |

The LLM must not treat these as interchangeable. Findings cite **Evidence IDs**
only (never Source IDs as primary support). Insights cite **Finding IDs** only.

Provenance chain: `Insight → Finding → Evidence → Source`.

### Run-scoped analysis input

Analysis operates only on Evidence for the current `(project_id, workflow_run_id,
research_design_id)`. Authoritative inputs:

- `research_brief_snapshot` and `research_design_snapshot` from WorkflowTemplate
- run-scoped Evidence from `EvidenceRepository`
- `analysis_plan` as semantic guidance (not executable code)

Project-wide Evidence aggregates are never authoritative.

### Bounded LLM input

Evidence is grouped by `research_question_refs[0]` and batched with explicit
limits:

- `ANALYSIS_MAX_EVIDENCE_PER_BATCH` (default 20)
- `ANALYSIS_MAX_CHARS_PER_BATCH` (default 12000)

Per-batch finding synthesis runs first; insight synthesis runs once over persisted
Findings. No vector DB / RAG in DR-05.

### Structured output

Production uses `JsonExtractor` + `JsonValidator`. LLM returns candidates;
application attaches project/run/design IDs, validates refs, computes dedup keys,
and persists.

### Provenance validation

Findings require non-empty `evidence_refs` resolving to run-scoped Evidence.
Insights require non-empty `finding_refs` resolving to run-scoped Findings.
Cross-project/run/design refs are rejected. LLM-provided IDs are never trusted.

### Contradiction policy (v1)

Conflicting Evidence may appear in the same Finding (`finding_type=contradiction`,
`metadata.conflict_signal=true`). All Evidence refs are preserved; no fabricated
resolution. If Evidence does not justify a conclusion, no Finding is emitted for
that batch.

### Confidence semantics

Optional `confidence` is an analyzer/LLM assessment (0–1), not objective truth.
Confidence alone never discards contradictory Evidence.

### Deduplication / idempotency

Finding dedup key: `(workflow_run_id, normalized statement, sorted evidence_refs)`.
Insight dedup key: `(workflow_run_id, normalized statement, sorted finding_refs)`.
Unique constraint `(workflow_run_id, deduplication_key)` per table. Concurrent
creates resolve via `DuplicateFindingError` / `DuplicateInsightError` retry.

Research submission idempotency (PF-07) excludes Findings/Insights.

### Persistence

Append-only `findings` and `insights` tables (migration `008_dr05_analysis_findings`).
In-memory and PostgreSQL repositories.

### Production executor matrix

| Stage | Executor |
|-------|----------|
| planner | implemented |
| search | implemented |
| evidence | implemented |
| analysis | **implemented (DR-05)** |
| report | `CapabilityNotImplementedError` |

Successful DR-05 workflow: collect → extract → analyze **COMPLETED**; write report
**FAILED**; workflow **FAILED** until DR-06.

### Failure policy

- Evidence batch LLM failure: continue other batches
- Zero valid Findings: analysis stage **FAILS**
- Zero valid Insights: analysis stage **FAILS** (Insights required in DR-05 contract)
- Invalid candidate refs: reject candidate, continue others
- Cross-run provenance violation: never persist
- Valid partial results may remain for audit if stage ultimately fails

### Deterministic test analyzer

`ANALYSIS_ENGINE=deterministic` for tests/smoke. Production default `llm`.
No silent fallback when LLM config absent.

### Deferred

DR-06 report writer, Artifact generation, citations/rendered reports, vector DB,
RAG platform, PDF parser, SourceVersion, human review, UI, OAuth/RBAC, executable
planner-generated analysis code.

## Consequences

- API exposes `/projects/{id}/findings`, `/findings/{id}`, `/projects/{id}/insights`,
  `/insights/{id}` with run-scoped filters
- Workflow run responses include `findings_available`, `finding_count`,
  `insights_available`, `insight_count`
- Authorization extends `require_finding()` / `require_insight()` (404 for foreign)
