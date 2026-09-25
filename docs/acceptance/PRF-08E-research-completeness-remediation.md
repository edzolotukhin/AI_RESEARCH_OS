# PRF-08E — Research completeness and extraction remediation (offline)

## Scope and baseline

This is an offline-only remediation of the three defects preserved in
`PRF-08D-live-desk-e2e-rerun.md`. Baseline: branch
`acceptance/live-desk-research-01`, HEAD
`72cfd56b92904d1f7664f2269e62f8bdccd73c00`, tracked tree/index clean,
7 ahead / 0 behind. No PRF-08B/08D run was resumed, recomputed or repaired;
no OpenAI/Tavily call or push was made. Existing untracked acceptance artifacts
were not touched.

## Root causes

1. **RQ without an IN.** The planner payload contract checked cardinality,
   unique IDs and reference validity, but not reverse RQ→IN coverage.
   `validate_research_design` similarly checked each IN but not each RQ.
   Project approval only checked design identity/fingerprint; activation only
   checked `APPROVED` and current fingerprint. Consequently the PRF-08D RQ5
   with zero INs passed every executable gate. During sufficiency aggregation,
   `all([])` made its per-RQ `ready_for_analysis=true`. The domain model also
   admitted that vacuous value. Other RQs blocked the global result in the
   historical run; that does not make the defect harmless.
2. **Temporal over-filtering.** PRF-08C correctly used the frozen Brief's
   observation cutoff, never publication time, but applied its date predicate
   to every Evidence→IN reference. Undated DfT terminology/category and
   methodology claims for IN2/IN4 were discarded solely for lacking an
   observation period. The stored 33 Evidence records were not deleted;
   only ten counted as qualifying under that historical rule.
3. **Invalid structured extraction.** The current Responses adapter requested
   JSON through prompt instructions, not an enforced provider JSON-schema
   mode. The JSON extractor tolerates harmless surrounding text/fences but
   cannot turn malformed JSON into valid structured data. Completed responses
   classified `invalid_json` on the ONS and January DfT work items; no
   application-level retry occurred, each consumed one of the eight Evidence
   logical calls, and neither produced Evidence. `invalid_json` means the
   adapter did not report an incomplete/truncated completion; exact provider
   syntax, internal SDK retries and paid input tokens remain unverified. No
   historical response text is copied into this record.

## Remediation and invariants

- Every material RQ (there is no optional-RQ status in the Desk model) must
  reference at least one valid IN. Generation contract and semantic validator
  reject an uncovered RQ. Project approval revalidates the current design and
  returns the uncovered ID as an actionable 409 UI response. Desk activation
  revalidates even an already-`APPROVED` snapshot. Valid designs still pass.
- New readiness aggregation requires a nonempty IN set per RQ and a nonempty
  RQ set globally. A new `ready_for_analysis=true` empty-IN assessment is
  rejected. Historical pre-08E snapshots with that exact shape can still be
  hydrated verbatim for read-only inspection; no historical row is rewritten
  or retrospectively reclassified.
- Temporal eligibility is evaluated per Evidence claim and IN, with four
  states: `applicable_satisfied`, `applicable_failed`,
  `applicable_unresolved`, `not_applicable`. For a dated Brief, only the first
  and last may qualify. `not_applicable` requires both a definition/method/
  classification IN and a static definitional claim, without measurement,
  observation or forecast language and without an asserted observation period.
  Source/page labels and publisher metadata cannot grant that exemption.
  Post-cutoff and unknown-date measurements remain excluded. Existing source
  grounding, data-lineage and semantic/aspect sufficiency checks are unchanged.
- Evidence extraction accepts valid structured output normally. For completed
  `invalid_json` or top-level `schema_contract_mismatch`, it makes **at most
  one** additional application-level logical LLM call with validation-category
  feedback (never a raw-response replay). That call goes through the existing
  budgeted client and counts against unchanged Evidence and total run caps;
  the retry is marked in budget telemetry. Empty/incomplete output and provider
  errors are not blindly repaired. After the bound, failure remains typed and
  no candidate is persisted. Wrong-typed item fields cannot be silently
  string/bool-coerced into Evidence; a schema-invalid item makes the whole
  response fail before persistence. Existing missing-field/relevance rejection
  diagnostics remain distinct. `structured_attempts` records 1 or 2 attempts.
  No new provider adapter, billing gateway or parallel JSON repair stack was
  added. SDK-internal retry behavior remains a separate, pre-existing cost
  limitation.

The temporal static-claim distinction is deliberately conservative lexical
recognition, not a claim that every possible definition or stable institutional
fact will be recognized. Mixed Evidence from one page is handled per claim;
an inseparable excerpt containing a statistic remains time-sensitive. A
definition's admission is not a finding of relevance, independence or
sufficiency. The PRF-08D IN5/IN6 retrieval gaps are not repaired by this task.

## Offline verification

Synthetic regressions cover: uncovered and valid designs; zero-IN RQ and
global vacuous-truth refusal; legacy snapshot hydration; in-period,
post-cutoff and unknown measurements; undated definition/methodology;
mixed-source and misleading-label behavior; valid/invalid/schema-invalid
extraction; valid second attempt; two-invalid typed failure and maximum two
calls. The integrated PRF-08D-pattern test combines an uncovered RQ,
undated definition, post-cutoff count, shared underlying lineage, invalid
extraction and conservative `insufficient_research` outcome. Existing PRF-08C
query isolation, legitimate ROI vocabulary, unknown/shared lineage,
observation cutoff and downstream refusal regressions remain in the canonical
suite.

Validation ledger:

- Focused planning/UI/extraction suite: **67 passed** before the final
  strict-item-schema addition; follow-up extraction module: **44 passed**.
- Disposable, separate PostgreSQL `prf08e_test` on loopback 15433: **51
  repository/activation/integrity tests passed**; later two Evidence JSONB
  roundtrip tests passed, including the new undated-definition case. Schema
  reaches migration `016_prf06f_pptx`; PRF-08E adds no migration.
- PostgreSQL worker/API/document selection: **8 passed, 1 failed, 1 error**
  on the Windows host. The two PDF-generation cases failed because host
  `reportlab` is absent, not because of a PRF-08E document change. The
  production-compatible, network-disabled image passed **10** offline
  PDF/PPTX regression cases and rendered a nonempty synthetic PDF
  (`PDF_RENDER_SMOKE_OK`, 29,615 bytes). The exact two host-limited
  PostgreSQL PDF/PPTX integration cases were then run against **only the
  disposable PRF-08E test database** from the production-compatible image:
  **2 passed**. The Windows-host run is not claimed green; the production
  dependency stack's document smoke/integration is PASS. PRF-08E made no
  PDF/PPTX product-code change; the reused image contains the accepted
  pre-PRF-08E document implementation.
- Full canonical `python run_tests.py`: **2,849 tests, 145 skipped,
  0 failures/errors** after the final product-code correction. The prior
  complete run exposed one obsolete missing-field diagnostic interaction;
  that exact test and 44 extraction/PRF-08E tests passed after the correction
  before the final complete run.

## Historical preservation (read-only)

Canonical checksum method: `md5(string_agg(row_to_json(e)::text, chr(10)
ORDER BY e.id))` over each isolated database's `evidence` table. PRF-08B:
13 Evidence, all `in1`, checksum
`076646d8ec25f2a7d682ec420896af95`, exactly its prior accepted value.
PRF-08D: 33 Evidence, checksum
`84ce68280d94941b19414a46893f2868` established in this phase; entire
workflow-row fingerprint `01e242df696ac51050788442c6249471`. Read-only
task-result fields still show both runs `completed` with
`insufficient_research` and `ready_for_analysis=false`. PRF-08D's RQ5
remains historically `ready_for_analysis=true` with zero IN assessments:
it was *not* recomputed. Both runs have zero Findings, Insights, Reports,
Reviews, PDFs, presentation jobs and artifacts (seven table counts each).
No historical DB was used for tests.

## Acceptance boundary

This phase proves offline remediation, not live research success. In
particular, a qualifying shared-data pair being collapsed and an actually
persisted post-cutoff observation were **NOT VERIFIED live** in PRF-08D;
their offline regressions do not convert them to live PASS. A new controlled
live run and spend require separate owner authorization. No second run was
started here.
