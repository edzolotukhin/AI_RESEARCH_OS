# QNT-06A — Canonical Quant Product Workflow Gap Audit

## Audit scope and baseline

This is a static, product-facing audit of the repository at commit
`54c6ef20a226e9e567faa3da2c04574bfae699e9` on
`acceptance/live-desk-research-01`. It does not change product behavior,
persisted data, migrations, or historical Quant runs. No runtime stack or
provider was used.

The accepted QNT-01 through QNT-05 backend chain is treated as authoritative:

`Dataset → Analysis → Statistical Results → Findings → Insights → Review → Approved Revision → Report → PDF/PPTX`.

The audit asks a narrower question: can an ordinary authorized user reach that
chain using current product UI or public API only? The answer is **no**. Existing
screens cover project/method setup, legacy dataset preparation, read-only
result projections, and shared deliverables well, but they do not expose the
complete canonical design-aware authority workflow.

## 1. Current end-to-end journey map

| Transition | Product entry point | Current accessibility | Finding |
|---|---|---|---|
| Create/select Project | `GET/POST /ui/projects`, `GET /ui/projects/{project_id}` | Fully user-accessible | Project creation, ownership, brief, design, and method cards already exist. |
| Select Quantitative method | Project create form and `POST /ui/projects/{project_id}/methods` | Fully user-accessible | Quant can be selected initially or added later. |
| Activate/create Quant run | `POST /ui/projects/{project_id}/methods/QUANTITATIVE/activate`; older `GET/POST /ui/projects/{project_id}/quantitative[/new]`; standalone `GET /ui/quantitative/new` | Partially user-accessible | A study/run is created, but canonical CMF selection depends on deployment flag `CMF_QUANT_ENABLED`; its default is false. The product does not identify the execution contract to the user. |
| Upload SAV/XLSX | `POST /ui/quantitative/studies/{study_id}/dataset` | Fully user-accessible for the historical setup flow | Format and size are bounded; the service persists immutable dataset/codebook records. Replacement requires an explicit request and is blocked once execution state makes replacement unsafe. The polished data template currently omits the hidden `replace_existing=true` control used by the older detail template. |
| Inspect import/schema | Quant `data` screen | Fully user-accessible as a read projection | Filename, format, dimensions, variables, missing rules, PII-safe metadata, warnings, and QC count are projected without respondent rows. Version/fingerprint and exact bound authority are not shown. |
| Run and approve QC | POST `qc`, POST `qc-approval` | Backend operation has UI routes; product access is incomplete | The older `quantitative/detail.html` contains controls, but the routed five-screen product shell uses `data.html`, which does not render them. Thus normal navigation can display QC but cannot reliably advance it. |
| Clean/recode data | POST `cleaning` | Legacy UI only / partially user-accessible | The old detail screen accepts a variable plus raw JSON replacements. This is not a production-grade canonical dataset-version UX and is absent from the routed data screen. |
| Configure/approve weighting | POST `target-margins`, POST `weight-approval` | Legacy UI only / partially user-accessible | Operations exist, but the only forms are raw JSON and are in the unrouted legacy detail template. Current data/analysis pages show weighting state but provide no usable configuration/approval workflow. |
| Create and approve QNT-01 research design/questionnaire/reconciliation/analysis plan | No user route found | Backend/internal-service and test-only | Services implement exact versioned authorities and approval, but no current UI/public mutation API lets a user create, review, revise, or approve QZ/RA/RB/RC. Tests construct or seed this chain through services/fixtures. |
| Start canonical design-aware analysis | POST `resume`; internal `activate_design_aware_workflow` | Partially user-accessible, but blocked without internal authority setup | The analysis page can show “Продовжити аналіз”. Canonical execution correctly refuses without the current approved plan and exact authority bindings, which the user cannot create in product. |
| Observe running/failed state | five Quant screens plus `status.json` | Partially user-accessible | Status projection exists, but polling/recovery guidance is limited. Rearm exists only on the old detail template and only for the bounded failed pre-provider case. |
| Inspect Statistical Results | Quant `analysis` screen and `result.json` | Partially user-accessible | Persisted results are rendered; the UI does not compute them. It shows statistic/value/base/population/weighting, but not all canonical procedure, group/comparison, p-value, limitation, dataset version, plan, and provenance fields required for auditability. |
| Inspect Findings and Insights | Quant `results` screen and `result.json` | Partially user-accessible | Separate persisted collections are shown, with support counts and selected semantic context. Rejected/controlled outcomes and complete authority lineage are not presented. |
| Inspect Review and request revision | Generic read-only review APIs; no Quant Review UI/action | Backend/API read-only plus internal workflow | QNT-04 deterministic Review runs in the workflow and persists `approve` or `revise`. There is no Quant product screen for Review issues/verdict, no user revision action, and no clear recovery journey after `revise`. |
| Inspect Approved Revision | No dedicated Quant route; indirectly in result JSON and Project Outputs source catalog | Backend/read projection only | Approved Revision is created only after approving Review, but the Quant UI does not make its identity, status, source bindings, or distinction from completion explicit. |
| Inspect Report | Quant `report` screen; shared source view | Partially user-accessible | The screen renders accepted report sections or controlled absence, but does not expose Review/Approved Revision status and still says export is unavailable even though QNT-05 exports are available through Project Outputs. |
| Generate/download PDF | Project Outputs POST/GET report PDF routes | Fully user-accessible once an eligible approved source exists | Existing CSRF/origin, ownership, immutable source, private download, and repeat-download behavior should be reused. |
| Generate/download PPTX | Project Outputs POST/GET PPTX routes | Fully user-accessible once an eligible approved source exists and worker support is configured | Existing durable job and shared action component should be reused. |
| Project Outputs/activity | `GET /ui/projects/{project_id}/outputs` | Fully user-accessible for available records | QNT-05 recognizes canonical Approved Revisions and legacy Quant separately. Activity is shared, project-scoped, and already shows persisted events where historical coverage is known. |

### Present-day completion verdict

A user cannot complete one new canonical CMF Quant project end to end without
internal services or fixtures. The first hard break is construction and approval
of the exact design-aware authority chain; the default-off CMF flag can make the
run legacy before that point. The downstream backend is complete and Project
Outputs can consume a valid Approved Revision, but the product cannot currently
produce that revision through user actions alone.

## 2. Canonical versus legacy boundary

### Canonical CMF Quant (QNT-01 through QNT-05)

- Uses `CMF_QUANTITATIVE_WORKFLOW_ID`, exact `QUANTITATIVE/1` method pin, protected
  post-analysis and Review pins, and design-aware execution.
- Requires current approved QZ research design, RA questionnaire, RB measurement
  reconciliation, RC analysis plan, immutable dataset/codebook, approved QC, and
  exact weighting authority where applicable.
- Persists Statistical Results, deterministic Findings, validated Insights,
  deterministic Review, and an immutable Approved Revision.
- QNT-05 deliverables resolve the Approved Revision as the public source identity
  and verify its entire immutable provenance chain.

### Historical/legacy Quant

- Uses `QUANTITATIVE_WORKFLOW_ID` and supports dataset-only exploratory execution.
- Existing upload/QC/cleaning/weighting/resume routes and much of the original UI
  were built for this flow.
- Legacy report composition remains readable and deliverable-compatible for
  historical records. It must not be rewritten or silently upgraded.

### Shared infrastructure

- Project workspace, owner authorization, workflow/worker persistence, immutable
  Quant state storage, Project Activity, report catalog, private binary storage,
  PDF, PPTX jobs, CSRF/origin protection, and downloads are method-neutral and
  reusable.
- Generic workflow-run and Review query APIs expose status, counts, and durable
  records, but do not provide the missing canonical Quant commands.

### Desk-specific behavior

- Desk design/research, ARK, Evidence, web acquisition, source citations, and Desk
  report revision flows are not Quant substitutes.
- Shared Project pages and deliverable components may be reused; Desk research
  screens, Evidence concepts, and ARK orchestration must not be copied into Quant.

### Collision risk

`ApplicationConfig.cmf_quant_enabled` defaults to false. Both standalone Quant
creation and project-bound activation select their workflow template from that
configuration. Therefore a visually identical “new Quant” action can create a
legacy or canonical run depending on deployment configuration. This is the main
canonical/legacy collision risk. QNT-06 must make new-run eligibility explicit,
pin it once, and never switch an existing or historical run in place.

## 3. Reusable UI/API inventory

| Surface/module | Current purpose | Canonical CMF Quant support | Required action |
|---|---|---|---|
| `api/routers/ui_projects.py`, project templates | Project create/list/detail, brief/design, method selection/activation | Project scope and Quant method are supported | Reuse; make canonical activation explicit and remove/redirect duplicate creation journeys. |
| `api/templates/projects/detail.html` | Method card, status/output summary, link to Outputs | Reads Quant output counts | Extend status/action projection; no new project dashboard. |
| `api/routers/ui_quantitative.py` | Five Quant screens and setup commands | Reads either workflow; commands mostly reflect legacy setup | Extend command boundary for canonical authorities; keep routes owner-scoped. |
| `api/templates/quantitative/{overview,data,analysis,results,report}.html` | Product navigation and read projections | Can render many canonical records | Reuse and extend. Do not revive `detail.html` as a second product shell. |
| `api/templates/quantitative/detail.html` | Older all-in-one operational form | Legacy setup controls only | Treat as reference/debt; migrate needed actions into the five-screen shell, then retire or redirect. |
| `QuantitativeStudyQueryService` and view models | Read-only aggregation of design, plan, results, Findings, Insights, Report | Already reads canonical records | Extend with exact dataset/plan/review/revision projections; never compute statistics here. |
| `QuantitativeUiService`/facade | Owner-scoped create/upload/QC/weight/resume/result | Creates CMF only behind flag; canonical activation validates authorities | Reuse orchestration and guards; add narrow canonical commands rather than bypassing services. |
| QNT-01/QNT-02 design, questionnaire, reconciliation, planning services | Versioned authority lifecycle | Canonical backend complete | Expose through an application command facade and UI/API DTOs. |
| QNT-03/QNT-04 post-analysis and Review services | Findings, Insights, Report, Review, Approved Revision | Canonical backend complete | Project their statuses/issues; add only supported revision/resume action. |
| `api/routers/reviews.py` | Owner-authorized read-only Review listing/detail | Can expose durable shared reviews | Reuse read model where compatible; Quant screen still needs source-bound presentation. |
| `api/templates/projects/outputs.html` and report routes | Report catalog, source view, PDF/PPTX generation/download | QNT-05 fully supported | Reuse unchanged except navigation/status clarity. |
| Project Activity | Canonical project event timeline | QNT-04 approval/revision events already emitted | Reuse; do not build a parallel Quant history. |

No public, schema-documented Quant command API was found for dataset authority,
QZ/RA/RB/RC lifecycle, analysis activation, or Review revision handling. The
current mutation routes are HTML form routes marked `include_in_schema=False`.
The JSON endpoints are status/result reads, not a complete automation API.

## 4. Lifecycle gap matrix

| Stage | Canonical state/authority | UI today | Public API today | Gap severity |
|---|---|---|---|---|
| Project/method | Project + approved project design | Complete | Partial/shared | Low |
| New Quant run | exact workflow/method/version pin | Ambiguous behind feature flag | No explicit canonical command contract | Critical |
| Dataset import | immutable DatasetVersion + CodebookVersion | Upload/read mostly complete | No documented command API | Medium |
| QC/cleaning | current QC and approval; replacement lineage | Routes exist but controls stranded in legacy template | No documented command API | High |
| Weighting | exact WeightSet + approval or explicit unweighted authority | Raw-JSON legacy forms only | No documented command API | High |
| QZ design | approved QuantitativeResearchDesignVersion | Read-only if seeded | Internal/test only | Critical |
| RA questionnaire | approved QuantitativeQuestionnaireVersion | No user surface | Internal/test only | Critical |
| RB reconciliation | accepted mappings/availability | No user surface | Internal/test only | Critical |
| RC plan | approved QuantitativeAnalysisPlanVersion and coverage | Read-only if seeded | Internal/test only | Critical |
| Analysis activation | immutable execution projection | Resume button, but prerequisites cannot be produced | Internal activation available | Critical consequence |
| Statistical Results | persisted deterministic records | Useful partial read view | Result JSON | Medium |
| Findings/Insights | separate persisted generations | Useful partial read view | Result JSON | Medium |
| Review | deterministic verdict/issues | Not shown as distinct gate | Generic read-only Review API | High |
| Approved Revision | immutable approved source | Indirect only | Result JSON/internal records | High |
| Report | accepted/controlled-absence composition | Read-only report screen | Indirect | Medium |
| PDF/PPTX | immutable deliverables from approved source | Complete in Project Outputs | UI form/download routes | Low |

## 5. Missing user actions

The minimum missing command set is:

1. Create a **new canonical** Quant run with an immutable execution/method version
   shown to the user; reject or explicitly isolate legacy-only deployments.
2. Upload or explicitly replace SAV/XLSX with previewed consequences. Replacement
   must create a new dataset authority and invalidate/supersede dependent draft
   authorities; it must never retarget an executed plan or Approved Revision.
3. Run QC, inspect reasons, approve/reject QC, and apply only supported recodes from
   the routed data screen.
4. Choose explicit weighted/unweighted mode; configure supported target margins,
   inspect diagnostics, and approve/reject the exact WeightSet.
5. Create/revise/review/approve QZ, RA, RB, and RC using their existing versioned
   services. The UI must show coverage and stale bindings before approval.
6. Activate the exact approved plan and observe queued/running/failed/completed
   worker state, with only existing bounded retry/rearm semantics.
7. Inspect Review verdict and issues. For `revise`, create a supported new draft
   authority/revision path and rerun only the canonical bounded stage; never mutate
   approved inputs or fabricate approval.
8. Open the exact Approved Revision and move to shared Project Outputs for PDF/PPTX.

Every mutation requires authenticated project ownership. Cross-project IDs,
foreign versions, stale fingerprints, and unknown resources must fail closed.

## 6. Required state presentation

The UI should project persisted canonical state rather than introduce a second
state machine. A single product projection can map existing records/tasks to:

| User-visible state | Canonical evidence | Primary action |
|---|---|---|
| No dataset | no current DatasetVersion | Upload SAV/XLSX |
| Uploading/validating | import task running | Wait; no duplicate submit |
| Dataset invalid | blocked validation/import failure with safe reason | Replace with explicit confirmation |
| Dataset ready | current dataset/codebook valid | Run/inspect QC |
| QC requires decision | current QC run | Approve, reject, or supported cleaning |
| Weighting incomplete | weighted intent without approved WeightSet | Configure/approve weighting |
| Analysis design incomplete | missing/draft/stale QZ/RA/RB/RC | Complete next authority |
| Analysis ready | current approved chain and execution projection | Start analysis |
| Analysis running | durable workflow/task running | Refresh/poll status |
| Analysis failed | persisted safe failure category | Show reason and only allowed retry/rearm |
| Results available | persisted Statistical Results | Inspect exact result provenance |
| Findings available | accepted/rejected Finding generation | Inspect Findings |
| Insights available/controlled absence | Insight result | Inspect Insights and limitations |
| Review required/in progress | Review task/record state | Wait or inspect verdict |
| Revision requested | Review verdict `revise` plus issues; no Approved Revision | Start supported revision path |
| Approved | approving Review + immutable Approved Revision | Open report/source |
| Deliverables not generated | approved source, no artifact | Create PDF/PPTX |
| Deliverables generated | immutable artifact records/jobs | Download exact artifact |

“Workflow completed” must not be displayed as “approved”. Controlled absence of
Insights/Report and a `revise` verdict are valid terminal/product states, not
generic errors.

## 7. Dataset UX requirements

- Keep SAV/XLSX only and display declared upload limits before submission.
- Show selected filename, immutable dataset version, safe fingerprint short form,
  dimensions, format, validation state, and exact invalid-file reason.
- Preserve the current safe variable dictionary: label, type, role, measurement
  level, and declared missing values; never render respondent rows.
- Show current QC identity/status, issue severity, cleaning lineage, and whether
  the dataset remains current.
- Show explicit weighted/unweighted intent, WeightSet version, diagnostics,
  approval state, and exact dataset binding.
- Before replacement, show which draft plan/weight/QC authorities become stale.
  If analysis or an Approved Revision already binds the dataset, create a new
  versioned path; never silently replace or relabel historical authority.
- Make duplicate upload/idempotency behavior visible and protect submission from
  refresh/retry duplication.

## 8. Analysis-design UX requirements

The minimum V1 design UI should edit and review existing canonical objects, not
invent a new free-form analysis engine:

- QZ: research questions, analytical requirements, target population/geography,
  methodology intent, weighting intent, assumptions, and limitations.
- RA: expected variables/measurements and questionnaire authority already defined
  by the accepted model.
- RB: deterministic mapping between expected and imported variables, data
  availability, explicit unmapped/ambiguous items, and approval of reviewed
  equivalence only where the existing contract allows it.
- RC: only accepted V1 procedures and comparisons; variable/group/category,
  population/filter/base, weighted/unweighted binding, supported significance
  semantics, and requirement coverage.
- Review/approve each immutable version with fingerprint and stale-state feedback.

Out of scope are standard deviation, correlation, regression, new tests, and any
free-form statistic. The server remains the validation and computational
authority; the browser submits intent and renders persisted projections.

## 9. Results UX requirements

Extend the current `analysis` screen around persisted `StatisticalResult` records.
For each result show, when present in the accepted contract:

- planned procedure/statistic family and exact analysis specification;
- outcome, grouping variable and categories;
- value with percentage/mean-appropriate formatting;
- numerator, denominator/base/N and filters;
- supported p-value/comparison semantics;
- weighting mode and WeightSet authority;
- dataset/codebook, plan, and execution-manifest identity;
- limitations and validation status.

The query/view layer must format only. It must not derive a new statistic, infer
significance, choose categories, or become a second authority.

## 10. Findings, Insights, Review, and Approved Revision UX

- Keep Findings and Insights as separate sections and records. Findings should
  expose exact Statistical Result support; Insights should expose exact Finding
  support and accepted limitations.
- Show accepted, rejected, and controlled-absence outcomes without presenting
  rejected material as product output.
- Add a distinct Review panel: verdict (`approve` or `revise`), issues, source
  report, reviewed dataset/result/Finding/Insight fingerprints, and timestamp.
- `revise` must produce no Approved Revision. The user must see why and be routed
  to the supported upstream revision action rather than an “approve anyway” path.
- `approve` permits display of the immutable Approved Revision identity and its
  exact source chain. Completion alone must never unlock deliverables.
- The generic Review API can supply shared metadata, while a Quant-specific view
  projection should present QNT-04 integrity details without exposing internals.

## 11. Deliverables and Project Outputs requirements

QNT-05 already supplies the correct product destination. Reuse:

- `/ui/projects/{project_id}/outputs` report catalog;
- source view under `/reports/QUANTITATIVE/{approved_revision_id}`;
- CSRF/origin-protected PDF generation and immutable download;
- durable asynchronous PPTX job, status action, and immutable download;
- owner-scoped authorization, private storage, checksums, and repeat downloads.

Required product changes are limited to navigation and truthfulness:

- link an approved Quant run/report screen to its Project Outputs entry;
- show “deliverables unavailable until Approved Revision” before approval;
- remove the stale blanket “export unavailable” message when an Approved Revision
  is actually in the QNT-05 catalog;
- show artifact pending/failed/ready status using the existing shared components.

Do not create a Quant document center or regenerate Report content during export.

## 12. Authorization and integrity requirements

- Require authenticated owner access for every project, study, authority version,
  Review, revision, report source, job, and artifact operation.
- Scope every lookup by project and run; do not authorize by an opaque ID alone.
- Preserve immutable exact-version bindings and reject stale/cross-run/cross-
  dataset/cross-project references.
- Pin canonical versus legacy execution at run creation and across worker restart.
- Protect state-changing form/API operations against cross-site submission and
  duplicate requests; retain idempotency keys where already supported.
- Treat dataset replacement as destructive to *future* authority only. Existing
  results, Reviews, Approved Revisions, and artifacts remain immutable/readable.
- Never accept client-computed QC, weighting, statistics, Findings, Review verdict,
  or fingerprints as authority.
- Keep respondent rows and private storage paths out of UI/errors/logs.
- Fail closed if an exact canonical dependency cannot be resolved.

## 13. Explicitly out of scope

- New statistical procedures, CSV ingestion, chart authority, or recomputation in
  the browser.
- ARK, Tavily/web Evidence, Desk research behavior, or cross-method synthesis.
- Rewriting, migrating in place, or resuming historical legacy Quant as CMF Quant.
- New PDF/PPTX renderers, a separate document center, DOCX, or slide preview.
- New authentication model, global authorization bypass, direct database tools,
  fixture-only product actions, or manual persisted-state repair.
- Resolving the documented recoverable Review-to-Revision transaction window
  unless a later implementation acceptance test proves it blocks this journey.

## 14. Proposed QNT-06 implementation slices

### QNT-06B — Canonical run, dataset, and analysis authority workflow

Make new eligible project Quant activation explicitly canonical; integrate upload,
QC, cleaning, weighting, QZ/RA/RB/RC creation/review/approval, and safe dataset
replacement into the existing five-screen shell. Add a narrow application command
facade and optional documented API DTOs over existing services. This is coherent
because it closes every prerequisite up to an immutable “analysis ready” state
without changing computation.

### QNT-06C — Execution, Results, and decision-gate workflow

Expose canonical activation/status/recovery and expand persisted Results,
Findings, Insights, Review, `revise`, and Approved Revision projections. This is
coherent because it covers the worker-driven state transition from one exact RC
plan to an approved or safely refused outcome, while keeping QNT-02/03/04 as the
only authorities.

### QNT-06D — Deliverable handoff and full product acceptance

Connect approved Quant navigation to the existing QNT-05 Project Outputs flow,
correct report/export states, verify PDF/PPTX job/download UX, Activity, security,
and execute the complete browser/API acceptance journey. This is coherent because
it contains mostly shared-surface integration and acceptance, not new Quant domain
logic.

These are three substantial slices rather than micro-phases. QNT-06B is the
critical path; QNT-06C cannot be accepted through UI without it, and QNT-06D
should not duplicate already accepted deliverable infrastructure.

## 15. Real end-to-end acceptance strategy

Use an isolated disposable PostgreSQL/API/worker environment built from the exact
candidate commit, with canonical Quant explicitly enabled for new runs. No live
AI or web provider is required for deterministic Quant acceptance.

1. Authenticate as an owner; create/select a Project, approve its applicable
   project design, add Quant, and activate exactly one new canonical run.
2. Assert exact CMF workflow/method/version pins and prove no legacy template was
   selected. Restart the worker once and recheck the pin.
3. Upload a tracked known-answer SAV and repeat with the supported XLSX fixture in
   a separate deterministic scenario. Verify safe metadata, limits, versioning,
   and foreign-user denial.
4. Run QC; exercise valid, invalid, rejected, and supported-cleaning outcomes.
   Verify explicit replacement cannot retarget an executed/approved source.
5. Configure weighted and explicitly unweighted fixtures through product actions;
   verify diagnostics and exact dataset/approval bindings.
6. Create/review/approve QZ, RA, RB, and RC using only supported V1 procedures.
   Exercise incomplete coverage, ambiguous mapping, stale version, and cross-run
   rejection.
7. Start analysis from UI/API, let the separate worker execute, and inspect every
   persisted known-answer Statistical Result and provenance field.
8. Verify deterministic Findings, separate Insights, controlled absence, and
   rejection of unsupported numeric/significance/causal claims.
9. Verify Review `revise` creates no Approved Revision; then use the supported
   revision path and verify `approve` creates exactly one immutable revision.
10. Open the accepted report, Project Outputs, generate PDF, schedule PPTX, observe
    job state, and download each immutable artifact twice with identical bytes and
    checksum.
11. Verify Project Activity, unknown IDs, cross-owner/project access, stale sources,
    restart/replay/idempotency, and no private paths or respondent rows disclosed.
12. Prove the entire journey used browser/public product commands only: no direct
    database manipulation, internal service calls, test-only seeding after project
    creation, legacy Quant substitution, ARK, or web Evidence.

Acceptance should retain focused route/view tests, application command-contract
tests, PostgreSQL API/worker restart tests, and one graphical/manual browser pass.
The final gate is not merely HTTP 200: the owner must be able to understand the
current authority, available action, failure reason, and exact approved source at
every stage.

## Conclusion

No new backend computation architecture is required. The canonical QNT-01 through
QNT-05 services and QNT-05 deliverables are reusable. The blocker is product
orchestration and projection: canonical run selection, user-accessible versioned
design/plan authorities, coherent data/QC/weight controls, and visible
Review/Approved Revision semantics. Closing those gaps in the three slices above
is the minimum route to a real canonical Quant product workflow.
