# QNT-06D — Quantitative full product workflow

## Baseline and scope

- Branch: `acceptance/live-desk-research-01`.
- Starting HEAD: `e1e505ddc244808fa2821f9c7e88716e8c06de93`.
- Starting divergence: `0 ahead / 0 behind`.
- QNT-01 through QNT-06C remain authoritative. QNT-06D adds only the final
  product handoff and lifecycle projection; it does not redesign quantitative
  calculation, review, revision, report composition, or document rendering.
- No OpenAI, Tavily, ARK, or live-research call was made.

## Product journey

The supported product path is now exercised as one workflow:

`Project -> Quantitative method -> canonical run -> dataset upload -> QC ->
Analysis Design -> design approval -> deterministic execution -> Statistical
Results -> Findings -> Insights -> Review -> Approved Revision -> persisted
Report -> PDF/PPTX -> Project Outputs -> repeated download`.

The Results page identifies the approved revision as ready for documents and
links directly to Project Outputs. Project Outputs continues to use the shared
QNT-05/PRF-06 deliverable service and presents the exact Approved Revision
fingerprint, PDF/PPTX availability, persisted byte size, creation time, and
download actions. There is no second Quant document subsystem and no binary is
generated in the browser.

## Authority and provenance

- The QNT-04 Approved Revision is the only narrative authority used by the
  existing QNT-05 quantitative report projection.
- The Approved Revision remains bound to the exact project, run,
  `QUANTITATIVE/1` method, dataset version/checksum, approved design,
  Statistical Results, Findings, Insights, and Review.
- The end-to-end fixture verifies known-answer persisted Statistical Results and
  asserts that report result references are a subset of the exact persisted
  result authority. Findings, Insights, Review, Report, PDF, and PPTX retain the
  same source chain; no `latest` lookup is substituted.
- Existing QNT-05 fail-closed validators remain responsible for rejected,
  stale, foreign-project/run/dataset/method, incomplete, legacy, and mismatched
  source chains. Focused QNT-05 and QNT-06D regressions remained green.

## Report, PDF, and PPTX handoff

- The persisted Quant Report is available from Project Outputs and from the
  Results-to-Outputs handoff. Report content is not recomputed by the UI.
- PDF uses the shared ReportLab renderer and private immutable deliverable
  store. PPTX uses the shared durable presentation job/worker path and pinned
  PptxGenJS renderer.
- Repeating either product action returns the existing source-bound artifact.
  Repeated downloads are byte-for-byte identical and match the persisted
  checksum. Restart verification uses a fresh PostgreSQL engine/session and
  confirms the same stored bytes without rendering or provider calls.
- Cross-project, foreign source, unknown artifact, CSRF, and source mismatch
  requests fail closed through existing server-side authorization and binding
  checks.

## Project Outputs and Activity

Project Outputs distinguishes the exact Approved Revision, persisted Report,
and absent/available PDF and PPTX states. Existing pending/failed presentation
states remain canonical; QNT-06D does not add a frontend-only lifecycle.

Two meaningful, idempotent canonical Activity transitions were added:

- `QUANT_PDF_GENERATED` — `PDF кількісного звіту готовий`;
- `QUANT_PPTX_GENERATED` — `Презентація кількісного звіту готова`.

They are written only after a newly inserted immutable Quant deliverable, in
the same PostgreSQL transaction. An idempotent conflict does not create a
duplicate event. Activity read validation checks the actual deliverable's
project, run, method, and format, so an orphaned or mismatched event is not
shown. Desk behavior and historical Activity remain unchanged.

## Migration

Migration `018_qnt06d_deliverable_activity` narrowly extends the existing
Activity check constraints with the two Quant deliverable event types and the
`deliverable` source kind. It does not rewrite or backfill historical rows.
Downgrade refuses to discard already-recorded new event semantics. The
repository has one head, `018_qnt06d_deliverable_activity`.

Repository-standard migration smoke passed the complete isolated cycle:
upgrade to head, downgrade to base, then upgrade to head.

## Acceptance evidence

- Focused QNT-06D UI/deliverable/Activity/readiness group: **31 passed, 1
  skipped, 6 subtests passed**.
- Shared production renderer plus Desk/shared/legacy deliverable regression:
  **48 passed, 4 skipped, 6 subtests passed**.
- Previously failing real-renderer checks were diagnosed as host-environment
  prerequisites (`reportlab` and `PDF_FONT_PATH`), not a product failure. After
  using the declared `reportlab==4.4.9` and an available Unicode-capable system
  font, both checks passed individually.
- Real PostgreSQL PDF/PPTX/worker/restart/Quant post-analysis group: **8 passed**.
- PPTX synthetic qualification: four qualified decks (Desk, Desk draft, Desk
  approved, Quant), resource-limit self-test passed, and **3/3** OOXML
  qualification tests passed.
- Offline, network-disabled, read-only production-image PDF/PPTX/QNT-06D smoke:
  **28 passed**.
- Final canonical repository suite (single post-fix run): **3156 total, 2997
  passed, 159 skipped, 0 failures, 0 errors**.

The full QNT-06D E2E uses supported product HTTP actions for project creation,
brief/design/activation, SAV upload, QC, analysis design approval, execution,
semantic authorization, Results, Review/Approved Revision, Outputs, PDF action,
PPTX scheduling and worker processing, and both downloads. Direct database
writes are not used to advance workflow state; persistence inspection is only
used to assert resulting authority and immutable bytes.

## Production document qualification

The production-compatible image was built from the current worktree. Its
offline smoke ran with no network, a read-only root filesystem, bounded memory
and process count, and temporary `/tmp`. The real ReportLab and PptxGenJS paths
passed alongside Desk regressions. PDF/PPTX generation and download do not call
external providers.

## Docker and preservation

Only `qnt06d-postgres-final` was created for PostgreSQL acceptance, with
`restart=no`, loopback-only port publication, and dedicated disposable
databases. No historical container, network, PostgreSQL volume, protected-data
volume, or acceptance artifact was modified. The disposable QNT-06D container
is removed after verification.

## Known limitations

- Quant Report generation remains the accepted deterministic QNT-05 projection
  of an Approved Revision rather than a separate asynchronous job. The product
  therefore exposes the persisted Report as available when the canonical
  Approved Revision projection exists.
- Existing presentation pending/failure behavior is reused; PDF generation is
  synchronous and retains its existing safe generic failure presentation.
- Visual human review of arbitrary future customer datasets is outside this
  deterministic acceptance. Structural, source-binding, renderer, and
  production-image qualification are covered here.
