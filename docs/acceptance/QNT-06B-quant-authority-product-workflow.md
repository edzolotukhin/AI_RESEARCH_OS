# QNT-06B — Canonical Quant Authority Product Workflow

## Baseline and activation decision

Implementation started on `acceptance/live-desk-research-01` at
`d3215c16958a5cd40108da019484a646c5f66572`, one local commit ahead of the
remote baseline. Ordinary standalone and Project-workspace Quant creation now
explicitly requests the canonical `QUANTITATIVE/1` CMF workflow, independent of
`CMF_QUANT_ENABLED`. The exact method, post-analysis and review pins are stored
when the run is created. Existing legacy records and the explicit internal
legacy creation path remain readable and unchanged.

## Product journey

The existing five-screen Quant workspace now exposes the bounded QNT-06B
journey: create/select Quantitative work, upload SAV/XLSX, inspect the active
dataset version and safe identity, run and approve QC, optionally construct and
approve existing target-margin weights, configure a supported V1 analysis,
review its exact dataset binding, and approve the immutable plan. Canonical
runs stop at the approved design state; the legacy resume action is not offered
for this slice, so QNT-06C execution is not started.

The product reuses QZ, RA, RB and RC authority services. It creates an approved
research design and questionnaire, performs deterministic/reviewed measurement
reconciliation, and leaves the analysis plan `IN_REVIEW` until the owner posts
the exact plan fingerprint. Approval binds the exact run, method pin, dataset
version/fingerprint, Codebook, variable mappings, filters, procedure,
comparison parameters and weighting authority.

## Dataset, QC and weighting

- Formats remain SAV and XLSX; CSV was not added.
- Accepted limits remain 20 MiB, 10,000 rows, 200 variables and 100,000 cells.
- The UI shows filename, format, row/variable counts, dataset version, shortened
  safe identities, QC state, weighting state and the version bound to a plan.
- Replacement before design binding creates a new dataset version. Replacement
  after an RC plan exists fails closed; no latest-dataset substitution occurs.
- XLSX `unknown` measurement level is accepted only through an explicit reviewed
  RB mapping; known incompatible levels remain blocked.
- Weighted plans require the existing current UI approval and derive the exact
  canonical `WeightSetApproval`; unweighted plans carry no implicit weight.

## Supported design surface and integrity checks

The product exposes only accepted V1 operations: one-way/profiling, numeric
summary, cross-tabulation, unweighted two-sided two-proportion z-test and
unweighted Welch t-test. Unsupported procedures, invalid categories, weighted
significance tests, missing/stale WeightSet authority, foreign plans,
cross-project records and post-binding dataset replacement fail closed.
Questionnaire generation preserves numeric, categorical and ordinal semantics;
review decisions preserve category, scale and missing-value meaning.

Focused product tests use actual HTTP forms, including hidden approval tokens,
and cover the complete known-answer XLSX journey plus tracked SAV fixtures for
cross-tab, proportion, Welch and weighted-plan binding. They also cover ordinary
canonical creation with the feature flag disabled, explicit historical
compatibility, unsupported configuration, exact approval and foreign-plan
rejection.

## Verification evidence

- Expanded QNT-06B/CMF/legacy/RA/RB/RC/design-activation group:
  **109 passed, 38 subtests passed**.
- QNT-06B product-action module after weighted and all-procedure coverage:
  **8 passed, 3 subtests passed**.
- Disposable PostgreSQL project-bound Quant, Quant UI persistence and atomic
  creation/restart group: **4 passed**.
- Compilation and `git diff --check`: passed.
- The one canonical full offline suite was run once, as required. Historical
  result: **3151 total / 2987 passed / 159 skipped / 3 failures / 2 errors**.
  All five non-green cases were one expected compatibility delta: two atomic
  UI tests still expected the ordinary product entry to publish the legacy
  template, while three durable-worker tests used that same ordinary entry to
  exercise the historical pipeline. The tests were corrected to assert the
  canonical product template and to use the explicit internal historical path.
  The complete affected pair of modules then passed **12/12**. Per the task's
  single-full-suite rule, the full suite was not repeated after this narrow
  correction.

No OpenAI, Tavily, ARK or external research call was made. Desk/CMF contracts,
historical Quant readers and existing Project behavior were included in focused
regression and remained green.

## Persistence, migration and resources

No migration was introduced; the repository remains on migration head
`017_qnt04_review_activity`. PostgreSQL verification used one loopback-only
container named `ai_research_os_qnt06b_postgres` with `restart=no`; it was
removed after the tests. No QNT-06B container or disposable volume remains.
Historical containers, databases, volumes and acceptance artifacts were not
modified.

## Known limitations

QNT-06B intentionally stops at an approved/ready design. Analysis execution,
Results, Findings, Insights, Review, Approved Revision and document handoff are
reserved for QNT-06C/D. The final aggregate full-suite run is preserved as the
historical non-green run above; its five compatibility cases have fresh targeted
green evidence but were not reaggregated by a prohibited second full-suite run.
