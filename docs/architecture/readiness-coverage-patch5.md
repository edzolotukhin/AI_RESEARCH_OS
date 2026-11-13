# Classified Readiness and post-analysis coverage — Patch 5

Parent commit: `18f9d7d841a606de77e70f10069c7bb254e0124b`.
No migration or Workflow Engine, acquisition/navigation, Evidence extractor,
arithmetic executor, H3 validator or UI changes.

## Contract

Only explicitly classified Designs (containing DERIVED or OUTPUT) use the new
projection. Historical Designs remain ACQUIRED; no inference from names, snapshot
updates, fingerprint changes or historical outcome rewriting occurs.

The existing sufficiency evaluator, including production hybrid semantic/quality
policy, evaluates the ACQUIRED projection of the immutable Design. The projection
is ephemeral, never persisted as a replacement Design. ACQUIRED still requires
qualifying citation/temporal Evidence and existing source-quality/aspect gates.
Explicit coverage additionally checks period, metric, geography, source diversity
and observation keys; unknown or conflicting dimensions cannot pass silently.
Structured Evidence from Patch 3 is recognized as quantitative only with its v2
semantic assignment, finite numeric value and matching workbook locator.

DERIVED readiness does not require its own Evidence or an existing Finding.
Dependencies must be current and sufficient; the declared executable contract
must have bounded, compatible input observations. Deterministic operations reuse
Patch 4's observation validator (including workbook/cell/revision semantics),
complete declared periods and percentage denominator checks. No interpolation,
unit conversion or arithmetic-chain support is added. Semantic operations retain
their explicit method and dependency requirements. OUTPUT is deferred, not an
Analysis target and not an acquisition gap. Acquisition remediation can target
only ACQUIRED gaps.

Readiness gates and terminal reconciliation use the same classified projection.
`analysis_ready` retains the existing partial-eligibility semantics: it can be
true when some ACQUIRED operations are eligible but a required DERIVED operation
is not. `ready_for_analysis`/`complete_design_ready` still describe readiness of
all analytical prerequisites. This does not grant H3 eligibility.

## Durable diagnostics

`InformationNeedAssessment` adds optional kind, qualification basis and prerequisite
diagnostics; legacy serialization omits them. Typed aggregate payloads use
`classification_version=analysis-kind-readiness-v1` and contain kind mapping,
analysis-required IDs, derived prerequisites and output obligations. Existing
workflow task-result JSON persists these without a schema change.

Examples of deterministic refusal reasons:

- `missing_qualifying_evidence`;
- `unavailable_required_observations`;
- `metric_unresolved_or_conflicting`, `geography_unresolved_or_conflicting`;
- `dependencies_not_ready` with exact `missing_dependencies` IDs;
- `unit_mismatch`, `geography_mismatch`, `zero_denominator`;
- `assessment_not_current`.

DERIVED status sufficient with zero own Evidence explicitly means prerequisites
ready, not an already established research conclusion. OUTPUT status sufficient
with zero Evidence means deferred; its obligation remains `satisfied=false`.

## Coverage and authoritative outcome

Coverage v2 excludes OUTPUT and requires persisted, validated ACQUIRED Findings.
DERIVED coverage verifies exact contract, validated dependency Findings, all
qualified Evidence references, scope and source revision lineage. Numeric proof
is checked with the existing deterministic validator. All declared arithmetic
period pairs must have validated outputs; retaining just one YoY result is not
full coverage. Semantic proof must have passed the existing entailment path.
Malformed, stale, unvalidated or incomplete proof fails closed.

The existing authoritative resolver understands typed dependency Findings and
excludes deferred OUTPUT targets. It remains the only outcome resolver; technical
failures retain FAILED priority. Coverage missing IDs override resolved claims.
The existing unmodified Workflow Engine skips Report and downstream tasks when
coverage is incomplete, including missing ACQUIRED or DERIVED Findings. Tests
exercise that actual gate with actual coverage and outcome services.

## Report limitation (explicitly deferred)

Claim-first Report receives `report_output_obligations` in shared state and stores
the same requirements in Report metadata, with verification state
`pending_finalization`. OUTPUT INs are excluded from H3's analytic IN list. No
OUTPUT claim, synthetic Finding or unsupported numeric authority is introduced.

This transfer does **not** implement automatic table/chart/PDF/PPTX requirement
verification. Existing H3 still requires its Research Questions; an OUTPUT-only
RQ does not become answered merely because its presentation obligation is
deferred. Product-level artifact compliance and any unsupported OUTPUT-only RQ
must be addressed by the later reporting contract, without weakening H3.

## Qualification

External LLM boundaries use deterministic fixtures; all internal application
services, validators and PostgreSQL repositories remain real.

Disposable PostgreSQL 16: `airos-patch5-pg16`, label `airos.task=patch5`, loopback
`127.0.0.1:55439`, new `patch5_test` database. Migrations reach
`030_source_revisions`; Patch 5 adds none. No production connections.

E2E-B uses real HTML acquisition and XLSX extraction from local HTTP fixtures,
hybrid Readiness, Analysis, Insights and typed coverage. Synthetic annual values
1000/950/900 produce six validated derived Findings: -50/-5%, -50/-5.263158%,
-100/-10%. Required coverage is complete and the authoritative outcome is
COMPLETED. Fresh persistence context retains readiness, coverage, Findings and
lineage; repeated Analysis preserves IDs and Evidence. The negative E2E reload
retains missing-observation/dependency diagnostics without generating Findings.

Commands (from the integration worktree; PostgreSQL flags and DATABASE_URL_TEST
must point only to the disposable database):

```powershell
python -m pytest tests/integration/postgresql/test_classified_readiness.py tests/integration/postgresql/test_executable_derivations.py -q --tb=short
python -m pytest tests/application/research_quality tests/application/analysis tests/domain/research_quality tests/application/report tests/application/qualitative tests/application/test_analysis_coverage_gate.py tests/application/test_ark06_readiness_sources.py -q --tb=line
git diff --check
```

PostgreSQL: **9 passed**, zero failed/skipped (includes inherited acquisition
regression cases). Focused Readiness/Analysis/outcome/H3/qualitative regression:
**326 passed, 113 subtests passed**, zero failed/skipped. Expanded local
regression: **1224 passed, 24 failed,
302 subtests passed**. All 24 reported failures reproduce on unchanged parent
commit 18f9d7d and fail at `source_identity.assert_snapshot_unchanged` in existing
Source fixtures, before the changed Readiness/Report behavior. Parent-only
verification: readiness fixture files 6 failed/25 passed/7 subtests; Report
coverage file 18 failed/11 passed/5 subtests (pytest includes failed subtests in
its failure count). No fixture assertions or Source immutability were weakened.

Affected existing files:

- `test_p1_31b_terminal_reconciliation_path_completeness.py` (one case);
- `test_p1_acceptance_replay.py` (one case);
- `test_prf08k_target_fidelity.py` (four cases);
- `test_report_coverage.py` (18 failures including subtests).

These pre-existing failures remain an explicit CI risk; the expanded suite is
not claimed green. Patch 5 qualification is limited to its contract and the
passing focused/legacy regressions, not end-to-end Report artifact acceptance.
