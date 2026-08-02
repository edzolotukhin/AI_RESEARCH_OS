# ADR-020: Desk Research Report Writer and Final Artifact (DR-06)

## Status

Accepted — implementation on `feature/report-writer` pending owner acceptance.

## Context

DR-05 produces durable Findings and Insights. DR-06 closes the desk-research vertical by writing a structured report and durable final artifact without introducing new research authority.

## Decision

### Report vs Artifact

- **Report** — semantic structured deliverable (`Report`, `ReportSection`) persisted in `reports` table.
- **Artifact** — durable external deliverable (`artifact_type=research_report`, `media_type=text/markdown`) with inline `content`, `content_checksum`, `filename`, linked via `report_id`.

Flow: validated analytical inputs → `ReportEngine` candidates → application validation + citation registry → `Report` → Markdown renderer → `Artifact`.

### Writer authority boundary

The writer may organize, summarize, and format validated Findings/Insights. It may **not** invent facts, call search, create new Findings/Insights, or trust LLM provenance IDs.

### Run-scoped input

Writer reads immutable `ResearchBrief` / `ResearchDesign` snapshots plus run-scoped Findings, Insights, Evidence (citation), and Sources (attribution) only.

### Structured output

Production uses `JsonExtractor` + `JsonValidator`. LLM returns section/summary candidates; application assigns IDs, validates refs, builds citation registry, and persists.

### Citation model

Application builds `[S1]`, `[S2]`, … from referenced Sources via Evidence. Sections store `citation_ids`; full registry stored on Report.

### Bounded input

`REPORT_MAX_FINDINGS_PER_BATCH` / `REPORT_MAX_CHARS_PER_BATCH` batch findings by research question before section generation; executive summary pass uses section summaries.

### Deliverable plan

`ResearchDesign.deliverable_plan` and `ResearchBrief.deliverables` guide section titles (semantic only, not executable).

### Language

Report language comes from brief/design snapshot (`ResearchBrief.language` / `ResearchDesign.language`).

### Limitations

Report includes design limitations plus writer-emitted limitations. No completeness claims.

### Persistence & idempotency

Append-only Report and Artifact rows with dedup keys:
- Report: `(workflow_run_id, normalized title, generation_method)`
- Artifact: `(workflow_run_id, artifact_type, report_id)`

Replay/worker recovery resolves existing rows; concurrent writers map `Duplicate*Error` to existing identity.

### Partial persistence

Valid Report may remain if Artifact rendering fails; stage fails honestly. No false successful report task.

### Residual limitation

Structural provenance is enforced; natural-language entailment / hallucination prevention is not claimed at v1.

### Deferred

PDF/DOCX, review UI, blob storage platform, vector DB, email delivery, DR-07 human approval.

## Consequences

- Production executor matrix: planner/search/evidence/analysis/**report** implemented.
- Successful E2E desk research may reach `WorkflowStatus.COMPLETED` when all stages including artifact generation succeed.
- API: `/projects/{id}/reports`, `/reports/{id}`, `/artifacts/{id}`, `/artifacts/{id}/content`; run summaries expose `report_count`, `artifact_count`.
