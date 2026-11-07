# Desk Research — current implementation and production-readiness map

Status: documentation review of `origin/main` at `45567411773c63830278a52ea626e8de748c4339`.
This document is the current cross-cutting index for Desk Research. Historical
acceptance records remain historical evidence and are not rewritten here.

## D1-A — documentation inventory

| Area | Current authority | Status | Action |
|---|---|---|---|
| Architecture and decisions | `docs/architecture.md`, `docs/adr/ADR-015` through `ADR-021` | Mixed: ADRs are authoritative for decisions, but several deferred sections are historical | Use this page for current runtime status; retain ADR history |
| Evidence and provenance | `docs/adr/ADR-017`, `ADR-018`, `docs/acceptance/P1-09.1-*` | Implemented and tested; live provider verification is separate | Keep source/run/design lineage claims tied to code/tests |
| Findings and Insights | `docs/adr/ADR-019` | Implemented in current code; older deferred text is stale if read as current status | Treat the ADR's historical deferred list as superseded by current implementation |
| Report and review | `docs/adr/ADR-020`, `ADR-021` | Implemented production path; human review UI is not implied | Link runtime contracts to this page |
| Deliverables | `docs/PRF-06E-project-deliverables.md`, `docs/PRF-06F-project-presentations.md` | Useful contracts; migration references are historical | Use current migration head and deployment runbook below |
| Acceptance evidence | `docs/acceptance/PRF-08A`–`PRF-08X` | Historical, mixed, and environment-specific | Do not infer production readiness from a single record |
| Operations | `docs/operations/production-deployment.md`, `pilot-recovery-runbook.md` | Deployment entrypoint is current; recovery migration pin is stale | Update operational migration pin to the verified head |

## D1-B — code-to-documentation traceability

| Capability | Implementation | Tests/evidence | Status | Remaining gap |
|---|---|---|---|---|
| Research design and required Information Needs | `application/research/`, `application/factories/research_design_factory.py`, `domain/planning/research_design.py`; orchestration in `application/workflow_engine.py` | `tests/integration/postgresql/test_production_stage_executor_honesty.py` | IMPLEMENTED / TESTED | Production live verification is historical and environment-specific |
| Source acquisition and provenance | `application/sources/source_acquisition_service.py` (`SourceAcquisitionService.acquire_for_context`), `application/services/source_service.py`, `application/sources/provenance_merge.py` | `docs/acceptance/P1-07.*`, Desk PostgreSQL tests | IMPLEMENTED / TESTED | Provider-dependent live acceptance must remain separately qualified |
| Evidence extraction | `application/evidence/evidence_extraction_service.py` (`EvidenceExtractionService.extract_for_context`), `infrastructure/evidence/llm_evidence_extractor.py` | Evidence contract and PostgreSQL integration tests | IMPLEMENTED / TESTED | Zero grounded evidence is a technical failure, not successful completion |
| Readiness | `application/research_quality/research_readiness_service.py` | readiness/outcome unit and PostgreSQL tests | IMPLEMENTED / TESTED | `blocking_information_need_ids` is readiness state, not the full outcome unresolved set |
| Findings and validation | `application/analysis/analysis_service.py`, `application/research_quality/authoritative_outcome.py` | `tests/application/query/test_p8d3_outcome_integrity.py`, analysis tests | IMPLEMENTED / TESTED | Historical records without explicit validation markers remain fail-closed |
| Insights | `application/analysis/`, `domain/insight.py` | analysis/query tests and Desk E2E fixtures | IMPLEMENTED / TESTED | No claim that an Insight replaces Finding/Evidence authority |
| Authoritative outcome | `application/research_quality/authoritative_outcome.py`, `readiness_result_codec.py` | outcome-integrity and PostgreSQL reload tests | IMPLEMENTED / TESTED | Production live verification is not implied by deterministic tests |
| Research analysis | `application/analysis/analysis_service.py` (`AnalysisService.analyze_for_context`), `application/executors/analysis_executor.py`, `application/research_quality/authoritative_outcome.py` | `tests/application/query/test_p8d3_outcome_integrity.py`, analysis tests | IMPLEMENTED / TESTED | Historical records without explicit validation markers remain fail-closed |
| Report composition | `application/report/report_service.py`, `application/report/editorial_composer.py`, `application/executors/report_executor.py` (`ReportExecutor.run`) | DR-05/Desk PostgreSQL tests | IMPLEMENTED / TESTED | Technical report failure remains `FAILED`; sections cannot create analytical success |
| Review and approval | `application/review/review_service.py` (`ReviewService.review_for_context`), `application/services/review_query_service.py` (`ReviewQueryService`) | report/review integration tests | IMPLEMENTED / TESTED | Human Review UI is not part of this backend contract |
| PDF delivery | `application/deliverables/service.py` (`ProjectDeliverablesService.generate`, `download`), `infrastructure/documents/reportlab_pdf_renderer.py` (`ReportLabPdfRenderer`) | PRF-06E and renderer tests | IMPLEMENTED / TESTED | Load and operational capacity require deployment evidence |
| PPTX delivery | `application/deliverables/service.py` (`schedule_presentation`, `process_next_presentation`, `download_presentation`), `infrastructure/documents/pptx_renderer.py` (`PptxRenderer`), `infrastructure/documents/pptx_runtime/` | PRF-06F and renderer tests | IMPLEMENTED / TESTED | Office-client fidelity is not guaranteed; production run still needs environment qualification |
| Durable task/outcome persistence | `application/runtime/workflow_runtime_persister.py` (`WorkflowRuntimePersister.persist_named_result`), PostgreSQL repositories; query projection in `application/query/research_run_result_query_service.py` (`ResearchRunResultQueryService.get_for_run`) | PostgreSQL reload tests | IMPLEMENTED / TESTED | Backup/restore and live operations remain deployment gates |
| API result projection | `application/query/research_run_result_query_service.py`, API routes | P1-18/P1-19 and query tests | IMPLEMENTED / TESTED | Endpoint deployment/auth/TLS are operational concerns |

## Functional workflow

The supported Desk path is:

`Research brief/design → source acquisition → grounded Evidence → readiness → validated Findings → Insights → Report → Review → approved delivery → PDF/PPTX → owner-scoped download`.

The workflow is durable and task-oriented. `ResearchReadinessService` computes
coverage and terminal readiness. `derive_authoritative_outcome()` uses validated
Findings backed by qualifying Evidence and lineage; it does not infer success
from report text, sections, artifacts, or workflow completion. The supported
research outcome values are `COMPLETED`, `PARTIAL`, `INSUFFICIENT`, and `FAILED`.

`FAILED` is reserved for confirmed technical failure. `INSUFFICIENT` means the
validated analytical coverage is not enough. `PARTIAL` means at least one
required Information Need is defensibly resolved while another remains
unresolved. A technically completed workflow may therefore have a non-completed
research product outcome.

## Quality and provenance invariants

- Evidence is grounded in an immutable Source snapshot and carries project, run,
  design, question and Information Need lineage.
- Findings must carry explicit successful validation metadata and qualifying
  Evidence references. Foreign project/run/design records are excluded.
- Report claims reference saved Findings/Insights and their evidence; generated
  text is not analytical authority.
- Review approval is separate from the research product outcome.
- Draft status and client approval do not change the authoritative analytical
  outcome.
- Durable task snapshots are reloaded through PostgreSQL repositories and the
  query service; no in-memory object is treated as persistence proof.

## Technical architecture and persistence

The application composition root wires PostgreSQL repositories, the workflow
engine, task scheduler, runtime persister, query services, ReportLab and the
local Node/PptxGenJS renderer. `ResearchRunResultQueryService.get_for_run()`
projects the latest report/review plus the extracted durable product outcome.
Report failure snapshots retain bounded diagnostics and `FAILED` outcome data.

The current migration contract is verified by
`tests/infrastructure/persistence/test_postgresql_readiness.py` as
`029_presentation_draft_lifecycle`. Migration `029` must be part of the release
before deploying the presentation-draft lifecycle. Historical PRF-06E/06F
documents cite earlier migration heads and should be read as milestone records,
not as the current deployment recipe.

PDF and PPTX bytes are persisted atomically in the private deliverable store.
Download rechecks owner, project/run/study/source identity, size and SHA-256;
download does not regenerate content. Presentation jobs are durable, claimed by
workers, bounded by retry/lease rules, and expose no public filesystem path.

## Operations and production gates

The supported deployment entrypoint is
`python -m tools.pilot_deploy --release-sha <40-character-accepted-git-sha>`
from a clean checkout. Do not replace it with an unpinned Compose mutation.
Before release, operators must verify the current migration head, PostgreSQL
backup/restore procedure, protected storage, API/worker health, TLS/reverse
proxy, credentials, provider budgets, logging/monitoring, and a production Desk
smoke test. The repository contains deployment and recovery procedures, but a
documented procedure is not evidence that a production restore drill or live
Desk run has passed.

Required acceptance evidence for a production deployment is a fresh, disposable
or explicitly approved environment run recording project/run/report/review and
deliverable IDs, outcome, task states, source/review provenance, and stored vs
downloaded checksums. Historical PRF-08 records must retain their original
verdicts and dates.

## D1-C — documentation changes

This page is the current cross-cutting index. `docs/README.md` links to it.
`docs/operations/pilot-recovery-runbook.md` now uses the verified migration
head. Existing PRF and ADR records remain available as historical decisions and
milestone evidence; no acceptance result was rewritten.

## D1-D — production readiness gaps

| Severity | Gap | Evidence | Minimum action |
|---|---|---|---|
| P0 | No evidence in this review of a production backup/restore drill with current head | Recovery runbook is procedural; no current drill is asserted here | Run and retain an isolated restore drill before production release |
| P1 | Live Desk provider run and operational budget/latency evidence are environment-specific | PRF-08 acceptance records explicitly distinguish live verification from deterministic tests | Execute one approved production-like smoke run with cost and failure evidence |
| P1 | TLS, reverse proxy, secret custody and external provider configuration are deployment facts, not repository facts | `tools/pilot_deploy.py` validates parts of the pilot contract | Verify them in the target environment and record the result |
| P1 | Human Review UI is not established by backend review/approval tests | ADR-021 and current routes distinguish backend review from UI | Decide whether backend approval is sufficient for release or qualify the UI separately |
| P2 | Renderer load and Office-client fidelity are bounded but not load-tested | PRF-06F qualification states synthetic bounded evidence | Run capacity and recipient-client smoke tests |
| P2 | Historical documents contain superseded migration pins and deferred wording | PRF-06E/06F and older ADRs | Keep them historical; link current operators to this page |

## D1-E — verdict

**PARTIAL — REMAINING GAPS.**

The repository contains an implemented and testable Desk backend path with
durable provenance, outcome derivation, review, PDF/PPTX persistence and query
projection. It does not, from source and historical acceptance records alone,
prove target-environment production readiness, backup/restore, operational
capacity, TLS/secret configuration, or Human Review UI acceptance.

The next controlled action is an environment-specific production-readiness
review using this matrix, without changing application code or rewriting
historical acceptance evidence.
