# CMF-01 — Canonical Method Framework

Status: architecture ready; proposed contracts below are NOT implemented APIs.
Inspection date: 2026-09-27. Baseline: `628c778ed2cc75aa45f01ee694fc80ac5cbade6f`,
`acceptance/live-desk-research-01`, ahead 35 / behind 0 against local upstream tracking.
Tracked worktree/index were clean; historical untracked artifacts are out of scope.
ARK-07 accepted ARK, not Desk E2E. PRF-08 and ARK architecture phases remain closed.

## 1. Current-state audit

Repository-relative paths below identify inspected implementation, not proposed replacements.

| Concern | Current implementation and classification | CMF consequence |
| --- | --- | --- |
| Project / method selection | `domain/project.py`, `domain/research_method.py`, `application/services/project_planning_service.py`; shared project, fixed DESK/QUANTITATIVE catalogue | Keep owner/brief lifecycle; replace new-method routing through explicit registration |
| Design | `domain/planning/research_design.py` explicitly describes Desk RQ/IN; planner payload contract and `application/research/design_validator.py`; project planning fingerprints selected methods | Generic name does not make Desk schema universal; preserve project design/approval and wrap method payloads |
| Approval / activation | `ProjectPlanningService` validates current design, freezes brief after activation, delegates atomic activation sessions; distinct Desk/Quantitative activation paths | Reuse transaction and idempotency; do not replace with independently committed adapter calls |
| Run / worker | `domain/workflow_run.py`, `application/workflow_engine.py`, `application/services/durable_workflow_service.py`, `application/services/worker_execution_service.py` | Shared execution and leases; method builds a supported workflow, not another worker |
| ARK | `application/research_kernel/{contracts,controller,ledger,dispatch,checkpoint}.py` | Already generic bounded controller; unchanged |
| Desk research adapter | `application/methods/desk/{adapter,primitives,executor,profile}.py` | Reuse actual DeskAdapter, not a second research orchestrator |
| Needs / discovery / acquisition | Desk InformationNeed and EvidenceExpectation; `application/sources/` query/acquisition primitives | Need semantics are method-owned; transport, Source persistence and bounded dispatch reusable |
| Evidence / provenance | `domain/evidence/evidence.py`, `domain/sources/source.py`, evidence/source ports and PostgreSQL repositories | Existing text-Evidence family is reusable, not a universal dataset row schema |
| Citations | `application/evidence/citation_integrity.py` checks full canonical normalized Source, checksum and Unicode spans | Mandatory platform text-support validator; methods cannot substitute a permissive validator |
| Temporal / relevance / geography / lineage | `application/evidence/temporal_scope.py`, extraction service and source content identity; qualification accepts Desk design/brief | Shared integrity principles; existing policy implementation is Desk-shaped, needs typed boundary, not relocation into ARK |
| Sufficiency | `application/research_quality/research_readiness_service.py`, aggregation, evaluator/cache/reconciliation; factory supplies Source repository | Method substance, platform operational/integrity prerequisites; ARK observes gaps |
| Analysis / Findings / Insights | `application/analysis/analysis_service.py`, analysis ports, `domain/findings/`; input directly imports Desk ResearchDesign | Reuse Desk implementation. Finding supports Evidence; Insight interprets Findings. Neither is a report paragraph |
| Quantitative authority | `domain/quantitative/analysis_execution.py`, `application/quantitative/` authority/lineage services and state persistence | Existing second analytical family, with dataset/QC/plan/result fingerprints, not text citations |
| Reports / review / revisions | `application/report/report_service.py`, `application/review/review_service.py`, report/review domain and repositories | Desk builds draft Report before reviewing it; revision identity and exact report-bound review must survive |
| PDF / PPTX | `application/deliverables/{contracts,service,presentation_jobs}.py`, `infrastructure/documents/` | Shared render/store/job infrastructure; service currently embeds method-specific source assembly |
| API / UI | `api/routers/projects.py`, `ui_projects.py`, project workspace facade/templates | Existing method-specific actions are compatibility entry points; future routing uses registry capability projections |
| Persistence / activity | `infrastructure/persistence/postgresql/`, activation transactions; `project_activity.py` | Shared durable transactions, but event catalogue/method allowlist includes Desk-specific entries |
| Telemetry / budget / version | `application/research_funnel_telemetry.py`, execution budget, kernel dispatch; Desk `_research_execution_v1` | Keep observational telemetry and pinned execution; CMF adds identity envelope, not replacement ledger |
| Auth | `api/auth.py`, authentication/authorization services; deliverables checks project owner | Shared, mandatory before method lookup/resource access; methods cannot authorize themselves |
| Historical compatibility | `VersionedDeskExecutor` falls back only when marker AND pin absent; mismatches fail | Preserve explicit legacy path and exact accepted versions; never infer latest for history |

Existing `registry/registry.py` registers agents/tools/human/API executors. It is NOT
a method registry. `ExecutorCatalog` likewise describes executors, not methodologies.

## 2. Architectural problem

The platform already shares execution, persistence and documents, but method selection,
activation, source cataloguing and UI contain a two-method switch. In particular,
`ProjectDeliverablesService.catalog` treats a non-Quantitative workflow template as Desk;
project planning also infers Desk from absence of Quantitative state. This must not
become the default classification of a third method. AnalysisInput and ResearchDesign
are Desk-shaped despite generic names. Activity permits only two method IDs.

Decision: add a small typed application-level method facade and explicit registry;
delegate existing behaviors first. No general plugin loader, new execution service,
replacement persistence, or research-strategy redesign. One-time routing refactors
are necessary before adding methods becomes mostly package + registration + tests.

## 3. Canonical method contract (proposed)

Use immutable typed records/Protocols under a future `application/methods/contracts.py`.
Names here specify responsibilities; implementation placement remains incremental.

| Contract | Inputs / outputs and invariant |
| --- | --- |
| MethodDescriptor | Stable method ID (preserve DESK/QUANTITATIVE), semantic method version, display name, contract version, compatible adapter/execution versions, capabilities |
| DesignPolicy | Validate typed method design against project brief and selected objectives; return structured issues, never silently rewrite design |
| NeedBuilder | Approved design snapshot -> ordered immutable ResearchNeed specifications with stable need/objective refs, requiredness, constraints and policy version |
| ResearchBinding | For adaptive mode construct the existing ARK MethodAdapter using scoped platform dependencies; for persisted-data mode return the dataset readiness binding, not a fake ARK run |
| EvidencePolicy | Extra admissibility rules over platform-validated support; may reject more, cannot rehabilitate invalid/unresolved support |
| SufficiencyPolicy | Validated persisted input snapshot -> ready / insufficient / operationally blocked, per-need gaps and fingerprint; paid semantic work must be explicitly dispatched, never hidden in observe |
| AnalysisPolicy | Immutable accepted input snapshot -> typed candidate Findings/Insights/result refs; platform validates scope, integrity, provenance and persists a new revision |
| ReviewPolicy | Method quality criteria and permitted reviewer decisions over exact result/report revision; platform controls actor, revision identity and atomic acceptance |
| ReportSourceAdapter | Authorized saved result/report revision -> existing PdfSourceDocument, including support refs, limitations and status; no fresh analysis in rendering |

Shared envelope fields: project/run IDs, owner scope, method/version, schema version,
approved design ID/hash, input reference hashes and policy versions. Do not put
credentials or unbounded provider text in identity, telemetry or fingerprints.
ResearchNeed is a CMF specification, NOT a change to ARK Gap: need ID, objective refs,
description, requiredness/priority, typed requirement kind, constraint payload/schema
version, approved design ref. Desk maps InformationNeed/EvidenceExpectation losslessly.
Need IDs and requirements cannot change mid-run; new design means a new revision and
separately authorized activation, not an expanded running budget.

Project-wide design remains the approval container. A method-design binding references
its exact approved portion plus whole-design/brief hashes. Shared lifecycle:
draft -> validated -> approved -> activated snapshot. Invalidated design cannot activate;
approved inputs are immutable. Activation persists the workflow, version selection,
queue state and activity using the existing atomic boundary. Do not introduce a new
approval bypass or promise new multi-run UX in the first migration.

## 4. Ownership matrix and integrity floor

| Platform owns | Method owns | Non-negotiable boundary |
| --- | --- | --- |
| Project/auth/activation/run/leases/transactions | Design schema, objective mapping, workflow recipe | Method cannot assign owners or commit partial activation |
| ARK scheduling, ledger, fencing, dispatch | Eligible actions, ranking hints, gap meaning | No provider access outside authorized action/reservation for ARK research |
| Source/support resolution, checksum/scope checks | Relevant entities, metrics, geography and substantive applicability | Integrity PASS AND method eligibility, never OR |
| Provenance/reference validation | Sufficiency thresholds and analysis algorithms | Missing infrastructure != missing research evidence |
| Revision/history/persistence | Findings and Insight content, method review criteria | No overwrite of accepted Evidence/results |
| Activity, telemetry, shared workers | Safe method event detail/content projections | Events transactional; telemetry cannot change decisions |
| Immutable storage/render/jobs/download authorization | Report section/content mapping | Presentation is representation, never analytical authority |

Universal requirements: immutable resolvable support identity, project/run scope,
canonical source/data checksum, stable lineage, explicit time applicability, accurate
geography/relevance relationship, fail-closed unresolved references. For text, use the
existing full normalized Source and Unicode `[start,end)` validator; publication date
cannot stand in for observation time. Unknown temporal applicability cannot certify a
dated claim. Undated definitions retain existing explicit policy semantics.

For structured data, canonical support is the persisted dataset version and approved
authority chain with variable/filter/base/weight/result fingerprints. It is NOT a
fabricated Source excerpt. A closed tagged SupportRef family (text citation / dataset
authority) resolves through platform-controlled validators. Preserve physical existing
tables initially; CMF evidence views wrap those records, not duplicate them. A method
cannot invent a third support kind without a separately reviewed integrity extension.
This is a future facade over two existing families, not a claim that current Evidence
already models both. Missing required Source/data repository blocks operation.

## 5. Explicit method registry

Proposed `MethodRegistry.resolve(method_id, exact_method_version)` returns a typed
MethodDefinition bundle containing all policies above and compatible version set.
Composition root explicitly registers Desk and later Quantitative factories with scoped
repositories/services. Reject duplicate keys, incomplete bundles, unsupported evidence
kinds, invalid capability combinations and incompatible execution versions at startup.
Unknown versions fail closed; UI may list enabled versions for NEW designs, never
select latest when loading a run. Registry is immutable after composition.

No package scanning, imports from user input, entry-point discovery or plugin market.
The registry holds factories, not run state or raw privileged database/provider clients.
Legacy routes delegate to the same resolved binding; no scattered new method switches.
Existing executor registry remains separate. New methods need one explicit registration;
core need not be edited unless a genuinely new support/execution family is introduced.

## 6. Narrow ARK boundary — unchanged accepted kernel

Use actual `MethodAdapter.observe/propose/execute/validate` and existing
`Observation`, `Gap`, `Action`, `Outcome`, `KernelState`, `Stop` contracts.
CMF needs map to Gap IDs; ARK does not parse the method design. The adapter resolves
persisted qualified input and supplies substantive gaps, ranked feasible actions,
resource costs and safe reference IDs. Controller owns reserve -> checkpoint ->
dispatch -> outcome -> reassess. Method success is target gain, not arbitrary output.
Useful cross-need evidence remains valid without pretending to repair the target.

Keep DeskAdapter and VersionedDeskExecutor. CMF wraps their construction; do not move
Desk sufficiency rules into the controller or run a competing inner research loop.
Platform injects Source repositories and approved integrity policy into readiness,
extraction AND analysis. Contract tests prevent bypass through permissive overrides.
Paid assessment is an explicit action; observation must not hide provider calls.

Dispatch must retain durable attempt ordinal/reservation/outcome, CAS/lease fence,
one-shot authorization and ambiguous-call reconciliation. No fresh budget on retry
or restart; no exactly-once provider claim. Keep existing limits, including Desk 6+2=8
where configured/pinned; CMF does not grant capacity. Telemetry remains observational.
Non-ARK data methods use existing workflow execution, not an alternative adaptive
controller. They cannot use that mode to run unaccounted external research.

## 7. Analysis boundary

Before analysis, platform resolves an immutable AnalysisSnapshot: approved design hash,
method/analysis versions, readiness decision+input fingerprint, exact qualifying support
IDs/hashes, source locators or dataset authority refs, limitations and effective policy.
All inputs come from canonical persisted records, never hidden provider memory.
Revalidate scope and fingerprint at dispatch; stale snapshot blocks, not auto-refreshes.

Desk facade delegates `AnalysisService` / `AnalysisEngine` with existing bounded batches,
provenance validation, entailment checks and dedup. Canonical Finding is a supported
analytical conclusion; Insight is interpretation/implication supported by Findings.
Typed method payloads may add statistical metadata, never break that dependency chain.
Returned candidates are not authoritative until platform validation/persistence succeeds.
Partial failures remain explicit; they cannot certify complete coverage.

Record engine/model/config identifiers, input hashes, output hashes and limitations.
Deterministic analysis should reproduce under pinned inputs; LLM prose is not promised
bitwise reproducible. Rerun is a separately authorized new analysis revision linked to
its predecessor, not Evidence mutation or hidden retry. Use existing stage budgets and
durable workflow boundaries; do not claim all downstream stages use the ARK research ledger.

## 8. Review and deliverables

Conceptual accepted chain is Analysis -> Findings -> Insights -> Review -> Approved
Revision -> Report representation -> PDF/PPTX. Actual Desk operational order remains
Analysis -> draft Report revision -> Review of THAT report -> approved/revise/reject.
CMF models the reviewed artifact kind explicitly rather than reversing existing order.
Quantitative uses its accepted composition/support validation, not a fabricated Desk review.

Platform binds review to project/run/design/result/report IDs, reviewer authority,
criteria version, verdict and exact revision; method supplies criteria. Revision creates
new content/history, invalidates no old bytes, and requires its own status assessment.
Conflicting/unproven review is not approved. Existing draft export availability is
preserved and clearly labelled; an exportable draft is NOT an accepted deliverable.

ReportSourceAdapter reuses PdfSourceDocument despite its PDF-oriented name for both
formats. Keep source_version/status snapshot, checksum, renderer/template version,
immutable private store, durable presentation jobs and reauthorized repeat downloads.
Never regenerate old artifacts merely because policy/template changed. Unsupported
chart/table associations remain unavailable; renderer must not synthesize analysis.

## 9. Small capability model

Descriptor declares `research_mode` = adaptive_external / persisted_dataset;
supported support kinds; has_findings/has_insights; formats subset PDF/PPTX;
approval gates (design, data/QC, result as applicable); accepted execution versions.
These are closed typed values, not arbitrary feature flags or user-controlled JSON.
adaptive_external requires an ARK binding and bounded provider capabilities;
persisted_dataset requires authority/QC resolver. Format support requires a report
adapter and deployed renderer. Capability does not grant authorization or imply readiness.
Runtime absence is explicitly unavailable, never silently replaced by another mode.

## 10. Desk migration mapping

| Contract | Existing implementation | Adapter/refactor | No-change commitment |
| --- | --- | --- | --- |
| Identity/design | DESK, ResearchDesign, planner contract, design_validator | Register exact Desk bundle; envelope existing schema | Frozen brief/RQ-IN completeness/approval |
| Needs/research | InformationNeed, DeskAdapter, DeskPrimitives | Lossless need facade; composition factory | Controller, queries, limits, scheduling policy |
| Integrity/readiness | citation_integrity, temporal_scope, ResearchReadinessService | Explicit required Source dependency; typed policy binding | ARK-04/06 qualification and refusal semantics |
| Analysis | AnalysisService, provenance/entailment validation | Wrap existing AnalysisInput, do not generalize it destructively | Findings/Insights correctness and budgets |
| Review | ReviewService, exact report review, revision linkage | Method review policy facade | Actual report-before-review lifecycle |
| Documents | ProjectDeliverablesService._desk | Extract source assembly into registered adapter | Renderers, immutable jobs/storage/downloads |
| Routing | ProjectPlanningService, project API/UI/query facades | Registry dispatch for new methods; compatibility routes | Atomic activation/idempotency and auth |
| History | profile.py / VersionedDeskExecutor | Add new-run CMF identity pin, retain legacy resolver | No retroactive requalification or re-execution |

Activity catalogue and method allowlists need a controlled shared routing/catalogue
refactor, not arbitrary adapter-defined events. Preserve old event names and coverage
notices; do not backfill unprovable historical activity.

## 11. Second-method architectural proof — design-aware quantitative survey analysis

Choose the existing product's quantitative family as a future CMF onboarding, NOT a
claim that Quantitative is absent today. No new methodology is implemented here.
Identity QUANTITATIVE, proposed CMF method version 1; preserve existing rd-1 execution
and qk-1 report versions independently. Research mode persisted_dataset, ARK not required
for an already supplied dataset. This is a meaningful test that CMF is not renamed Desk.

Design binds research-design/questionnaire authorities and AnalysisPlan; requirements
bind variables, population, filters, weights, QC approval and analytical requirement IDs.
Use `application/quantitative/research_design_authority.py`, `analysis_planning.py`,
`analysis_execution.py` and `authority_chain.py`. Dataset fingerprint / codebook / schema /
QC / plan versions feed the AnalysisSnapshot. Missing or stale authority blocks execution;
data inadequacy is separate from unsupported/failed computation.

Analysis delegates existing stage services and QuantitativeAnalysisExecutionManifest,
including outcome statuses, coverage manifest and result references. Findings/Insights
retain `finding_lineage.py` / `insight_lineage.py` validations and statistical support.
Review/result acceptance retains supported QuantitativeReportCompositionResult and
validation fingerprints. Source adapter delegates current `_quantitative` assembly into
PdfSourceDocument; shared PDF/PPTX/worker/auth/storage remain unchanged.

Current obstacles requiring ONE-TIME core facade work: fixed method tuple, binary
activation/template inference, Desk AnalysisInput type, split result querying, fixed
activity catalogue and embedded deliverable source builders. No ARK internals need
modification. The dataset support resolver is a shared integrity facade over existing
authority services; it must be implemented/tested before claiming quantitative CMF ready.
Later same-family methods primarily add typed policy/package/tests/registration. A new
data modality may require reviewed shared support validation, not a permissive plugin.

## 12. Versioning and historical compatibility

For new opted-in runs atomically pin: CMF contract version, method/version, design schema
and snapshot hash, adapter version, ARK execution version (explicit not-applicable for
dataset-only), integrity/sufficiency/analysis/review policy versions and budget profile.
Keep report source ID/revision and render/template version on each deliverable separately.
Persist the envelope through existing workflow metadata/checkpoint codecs where round-trip
and transaction tests prove support; no schema migration is presumed necessary. If codecs
cannot preserve it, a separately reviewed additive migration is required before rollout.

Missing CMF pin on historical runs routes through existing explicit legacy resolver;
never populate it with today's defaults. Desk ARK marker/pin mismatch remains operational
failure. Restart resolves EXACT pinned bundle; unavailable version blocks with a readable
error. Retirement can disable new activation without preventing old reads/downloads.
No backfill, reinterpretation, requalification or automatic resume of historical outcomes.

## 13. Failure semantics

| Category | Meaning / action |
| --- | --- |
| infrastructure_unavailable | Source/data repository, worker, database unavailable; operational block, never research insufficiency |
| provider_failed / reconciliation_required | Explicit provider failure vs ambiguous completion; existing bounded retry/fencing only |
| research_insufficient | Healthy evaluation of validated data leaves required gaps after permitted opportunities; safe refusal |
| integrity_failed | Corrupt/unresolvable support, scope mismatch or provenance violation; cannot qualify; block affected output, retain evidence |
| method_design_invalid | Validation issues or stale/unapproved design; do not activate |
| method_analysis_failed | Failed computation/unsupported input/invalid provenance; no accepted revision |
| review_rejected / revision_required | Substantive quality decision, distinct from transport failure; preserve report/review history |
| deliverable_failed | Renderer/storage/job failure; approved analytical source remains intact; bounded existing job policy |
| version_unsupported | Missing/incompatible pinned implementation; never fall back to latest |

Keep existing ARK Stop values; CMF maps them with retained reason and method assessment,
not a blanket conversion of TECHNICAL/RECONCILIATION/SAFETY into insufficient research.
Do not treat a healthy empty result as provider failure or unknown support as independent.

## 14. Reusable acceptance model

1. Shared regression: inherit ARK-07 live acceptance and ARK-02/04/06 offline contracts,
   ledger/recovery/citation/Source wiring, auth and document tests. No repeated deep live
   kernel campaign merely for a new method using unchanged primitives.
2. Method contract acceptance offline: registry rejection/compatibility; approved-design
   round trip; stable needs; valid-empty/cross-target outcomes; monotone integrity filter;
   Source/data dependency failure; readiness fingerprint equality; analysis provenance;
   exact review/revision; snapshot/export binding; unauthorized access; restart/version
   pinning; no undispatched calls; unchanged telemetry on/off results. Use deterministic
   fixtures and shared test harness; method cannot waive shared invariants.
3. Method live acceptance, separately authorized: normally one bounded representative
   success-capable case and, only if necessary, a bounded limitation case. Count/cost
   approved before execution; offline tests cover adversarial cases. No automatic paid
   retry for insufficiency; retain honest NOT VERIFIED if a natural case is absent.

Escalate depth when changing kernel/provider dispatch, integrity/support kind, transactional
boundary, new execution family, renderer inputs, auth, or pinned compatibility. First
dataset-family CMF onboarding needs its authority integration gates; subsequent equivalent
methods inherit those results. A changed shared primitive reruns its affected regression
and deployment gates, not an indefinite PRF-08-style live optimization campaign.
Architecture conformance tests must reject kernel imports of method packages and method
provider calls outside approved dispatch, as well as method-specific switches in new routing.

Existing anchors: `tests/application/test_ark02_kernel.py`, `test_ark02_retry.py`,
`test_ark02_checkpoint.py`, `test_ark02_desk.py`, `test_ark02_desk_integrity.py`,
`test_ark04_citation_integrity.py`, `test_ark06_readiness_sources.py`;
`tests/integration/postgresql/test_ark02_ledger.py`, `test_ark02_desk_worker.py`,
`test_prf_05a_activation_transactions.py`; project deliverable API/UI tests.
These are reuse targets, not suites executed by CMF-01.

## 15. Incremental implementation plan (not authorization)

1. Add typed facade contracts and immutable registry, registration validation and offline
   contract harness. No active routing change; preserve existing execution IDs.
2. Wrap Desk design/needs/analysis/review/source providers. Differential tests against
   existing behavior; accepted ARK controller and research policies untouched.
3. Add new-run CMF pin at atomic activation; test codec round-trip, stale approval,
   concurrency, restart, legacy fallback and unknown versions before routing rollout.
4. Route new opted-in Desk runs through registry; compatibility API delegates; generic
   capability UI/catalogue rejects unknown methods instead of guessing Desk.
5. Extract report-source routing and controlled activity catalogue; retain old source keys,
   draft labels, review semantics and all historical document download identities.
6. Bind analysis snapshots/review validation with provenance and exact revision checks;
   no retroactive rewrite. Run affected PG/worker/API/auth/document regression gates.
7. Add a non-running quantitative registry proof and dataset-support resolver contract
   tests, then separately authorize actual quantitative onboarding if desired.
8. Close offline Desk parity and historical-read compatibility; live acceptance only on
   separate owner authorization and only where changed boundaries justify it.

Each step has an opt-in new-run boundary and rollback by disabling new activation, NOT
switching versions of in-flight runs. Keep old handlers until their runs are read-only or
supported to completion. Avoid big-bang schema unification and data backfills.

## 16. Risks

Largest risk is calling Desk-shaped schemas universal and weakening dataset integrity to
fit them. Others: registry becoming a service locator; capability flags bypassing auth;
default-latest changing history; review-order changes; provider calls hidden in policies;
semantic insufficiency masking missing Source access; treating shared telemetry as control;
claiming unified persistence before codecs/transactions are proven. Controls are the typed
closed bundles, mandatory platform validation, parity tests and pinned opt-in rollout above.

## 17. Explicit decisions / acceptance trace

1. ARK is shared, unchanged and method-agnostic (sections 5–6).
2. Integrity is a platform floor, with method-only strengthening (sections 4, 7).
3. Design/needs/sufficiency/analysis/review content belongs to methods (sections 3–4).
4. Desk migration is wrappers/routing, not a rewrite (section 10).
5. Quantitative fits the same lifecycle and documents without fake text Evidence (11).
6. New-run version pinning, exact resolution and legacy reads preserve history (12).
7. Shared evidence is inherited through three-layer acceptance, not repeated live research (14).
8. New same-family methods do not normally modify kernel/platform internals after the
   one-time facade migration; new support families require explicit platform review (11,15).

Non-goals: ARK redesign, UK EV optimization, another method implementation, third-party
plugins, persistence replacement, historical changes, migrations, provider calls or live runs.

## 18. Open questions and CMF-01 verification

No unresolved architectural decision blocks this record. Implementation must verify exact
metadata codec capacity/atomic persistence before selecting migration-free storage; that is
a bounded technical gate, not permission to silently add a schema. Product choice of which
method to onboard next and its substantive thresholds needs separate authorization.

CMF-01 performed read-only source inspection and lightweight static document/path/diff
checks only. No product implementation, test suite, Docker/database changes or provider
calls. Historical records were neither mutated nor recomputed; no fresh database audit is
claimed. Original untracked artifacts, including INFRA-01 record, remain preserved.
