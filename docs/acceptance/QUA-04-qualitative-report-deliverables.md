# QUA-04 — Qualitative Report deliverables acceptance

## Baseline and implementation

- Baseline: `acceptance/live-desk-research-01` at `5d5a33fda4c58020e73ae9c15c96e2e5b6432385`, ahead/behind `0/0`, clean tracked/index state.
- Initial Alembic head: `021_qua03_findings_review`.
- QUA-04 adds append-only qualitative Report revisions, Product UI, common PDF/PPTX catalog/generation/download, Project Outputs, and bounded Activity events.
- No OpenAI, Tavily, AssemblyAI, ARK, web, or live research call was used.

## Authority and known-answer evidence

- Sole Report authority: exact QUA-03 Approved Revision.
- Known-answer fixture: three pseudonymous participants, two accepted Findings, one multi-Finding Insight, accepted thematic authority, supporting excerpts, and one contradictory/deviant case.
- Draft edit creates a successor; finalization creates an immutable final record. Final source version is the qualitative state checksum.
- Report contains executive summary, methodology, Findings, Insights, excerpts, deviant evidence, limitations, and conclusion.
- Excerpts retain application/transcript/segment/span provenance. Prepared transcript timestamps remain absent; unknown speaker labels are not exposed as real names.
- Source binding remains the stored Approved Revision and Report checksum rather than “latest”.

## Product and document lifecycle

- Qual workspace exposes Report creation, inspection/edit, finalization, and navigation to Project Outputs.
- Project Outputs exposes Qualitative Report, PDF generation/download, asynchronous PPTX generation/download, status, Report revision, and source version without storage paths.
- The shared Desk/Quant `ProjectDeliverablesService`, ReportLab renderer, presentation jobs, PptxGenJS renderer, binary store, and authorized download routes are reused.
- PDF/PPTX generation is idempotent for the exact Report checksum. Stored checksum and byte size are verified on every download; repeat downloads are byte-identical.
- Foreign project/source and unknown IDs fail closed through the common ownership/source checks.

## Schema, persistence, and Activity

- Migration: `022_qua04_report_deliverables`, based on `021`; it extends only Activity event/source-kind constraints.
- Isolated migration smoke performed upgrade → downgrade to base → upgrade successfully.
- Existing qualitative PostgreSQL restart acceptance and shared durable PDF/PPTX repository/job tests are the persistence foundation; final focused results are recorded below.
- Activity milestones: Report draft, Report finalized, deliverable ready, Qual PDF generated, Qual PPTX generated.

## Verification evidence

- New QUA-04 UI/authority/download tests: `11 passed`.
- Combined QUA-03/04 plus Desk/Quant shared deliverable regression: `42 passed, 4 skipped`, plus `6 subtests passed`.
- Isolated PostgreSQL migration + Qual E2E portion: `9 passed` before four environment-configured shared tests were rerun separately; the first run's four failures were missing `DATABASE_URL`, not product assertions.
- Shared PDF/PPTX PostgreSQL rerun: `5 passed`; two PDF endpoint assertions were blocked on the Windows host because the production renderer intentionally requires the Linux DejaVu font path. The same current-source production image rendered the Qualitative PDF offline successfully (`25,539` bytes).
- Network-disabled production-image shared/UI smoke: `39 passed, 3 skipped`; production PPTX qualification: `9 passed` within the renderer group. The three skips were PDF extraction tests gated on `PDF_FONT_PATH`; with the path enabled, rendering passed and the two extraction tests could not import test-only `pypdf`, which is not a production dependency.
- Canonical full suite: `3192 passed, 164 skipped, 0 failures, 0 errors`.
- A separately invoked crypto architecture test reported 18 pre-existing application imports; no QUA-04 file introduced one and the canonical repository suite remained green.

## Cleanup and limitations

- Disposable `ai-research-os-qua04-postgres` was removed. The historical `ai_research_os_postgres` container remained running and untouched.
- No new Qual-specific binary table was introduced. PostgreSQL qualitative state, shared PDF store, presentation jobs, and restart-safe paths remain the canonical persistence boundaries.
- Automated product proof used deterministic providers/renderers; no graphical human inspection was required for this local code gate.
