# QNT-03 — canonical Quant Results → Findings → Insights

## Baseline and reuse map

The starting branch was `acceptance/live-desk-research-01` at
`6674fb1ddaab9b19feb51fe0d5a52780d8f4b028`, aligned with its upstream.
CI run `36460114429` was the accepted remote baseline. Existing historical
untracked acceptance/runtime artifacts were not selected for editing.

QNT-02's `StatisticalResult`, `AnalyticalComparisonResult`, immutable dataset,
analysis pin, persisted RD manifest and result-provenance projection remain the
only statistical authority. Existing QH Finding parser/support validator, RE
Finding lineage, QJ Insight synthesis/validator, RF Insight lineage, and shared
workflow/project/activity/revision infrastructure are reused. The existing
report/review path is unchanged. Desk remains an Evidence/citation/ARK method;
Quantitative remains a `persisted_dataset` method with no ARK.

## New-run Finding and Insight contracts

New opted-in CMF Quant runs seal `_cmf_quant_post_analysis` to
`QNT03_DETERMINISTIC_FINDINGS_V1` alongside the exact `QUANTITATIVE/1` method pin.
This first-write-only checkpoint key prevents silently switching a run's
post-analysis implementation after creation. Prior runs without this key retain
their historical QI/QJ behavior and are not backfilled.

On pinned runs QI uses a provider-free, bounded deterministic selector over the
persisted result bundle. It proposes eligible result and comparison IDs only;
the pre-existing QH parser and support validator resolve exact numerical values
and reject unsupported material. Both significant and non-significant supported
comparisons may produce Findings; non-significance is not a failed analysis.
The selector neither computes statistics nor generates a new p-value/CI.
Unsupported/incomplete provenance and absent eligible Findings fail closed as
operational Finding-generation errors.

Each supported Finding carries a frozen canonical authority binding run,
`QUANTITATIVE/1`, dataset version/fingerprint, source N, exact result/comparison
IDs and reproducibility fingerprints, procedure/version, denominators, filter,
base, weighting, missing-value semantics, and canonical significance/p/alpha.
The authority and Finding support fingerprints change with their bound inputs.
The persisted statistical result remains authoritative rather than the
formatted Finding text.

QJ receives an immutable projection of the accepted Finding set, including the
new canonical authority where present. Its model may interpret but not add or
repair statistics. Before accepted persistence, the new-run validator rejects
unbound numbers/percentages, altered N/base/p-values, confidence intervals,
unsupported significance, causal language, incompatible dataset authority, and
weighted/unweighted contradictions. Existing QJ Finding-reference and
analytical-context validation remains in force. The RF input authority binds
the exact Finding generation/support set. A changed source set cannot silently
keep a previous Insight authoritative.

The one-shot semantic authorization is consumed immediately before the QJ
provider boundary on pinned runs, not during deterministic QI. The approved
pre-QI boundary is rechecked after removing only the QI-produced output
references; dataset, plan and analysis authority remain in the check. A
PostgreSQL end-to-end test exposed and then verified this necessary boundary
adjustment. Existing ambiguous-provider-call non-retry semantics remain.

## Failure and observability semantics

Missing/unsupported source results, stale/incomplete provenance, no eligible
Findings, and QI rejection are operational Finding-generation failures, not
statistical insufficiency. A QJ provider error or malformed bounded structure
is an operational generation failure. Fully rejected QJ output remains a
persisted rejection record, not an accepted Insight; the run fails with
`QNT03_INSIGHT_VALIDATION_REJECTED`. No rejected numerical text is promoted as
valid. Existing stage/task progress, persisted generation records and lineage
manifests provide analysis/Findings/Insights/revision observability without
recording private provider prompts as Activity events.

The only statistical methods are the accepted QNT-02 procedures; no new
calculation, external evidence, Tavily, ARK, or citation path was added.

## Offline verification

Focused deterministic tests cover exact result IDs/values/fingerprints, weighted
and cross-tab values, significant and non-significant z/Welch comparison
selection, provenance changes, and exact pin preservation. Adversarial QJ
tests cover valid interpretation, invented/altered percentages, N, denominator
and p-value, invented CI, false significance, causality, weighting mismatch,
stale source reference, malformed structure and provider failure. This is
offline evidence, not a claim that free-form language validation is formally
complete for every possible paraphrase or language.

The separate-worker PostgreSQL test uses a newly created disposable
`qnt03_test` database and two application containers. It verifies the current
CMF Quant method/post-analysis pin, QNT-02 analysis before the semantic gate,
zero model calls at QI, explicit authorization, a persisted deterministic
Finding with exact run/dataset authority, accepted bound Insight, subsequent
report compatibility, and absence of a Desk research-kernel key. The first
version of this test exposed the stale pre-QI authorization comparison; after
the narrow fix the test passed. The affected PostgreSQL/CMF/worker group:
**13 tests passed, 0 skipped, 0 failures/errors**. The disposable test
container was stopped/removed after the run; historical services were untouched.

Affected QNT-03/Quant/worker offline group: **56 tests passed**. A separate
affected API/CMF/Desk group: **40 tests passed**. One preliminary API command
named a nonexistent test module and returned an import error; the correctly
named command above passed. The added cross-tab/weighted Finding module alone:
**15 tests passed**. Expected negative-path worker log traces in the CMF group
are assertions of guarded failure, not failing tests.

The canonical `python run_tests.py` suite was executed **once**: **3133
tests total, 159 skipped, 1 failure, 0 errors**. The sole failure was
`StructuredOutputArchitectureTests.test_p_json_loads_only_in_validator`:
the new deterministic selector directly used a JSON parser despite the
existing project rule that parsing belongs to `JsonValidator`. This was a
QNT-03 architecture violation, not a stale test. The selector now invokes
the canonical validator and rejects non-object/malformed bundles. The exact
failing test plus both QNT-03 test modules were rerun: **44/44 passed**.
No other failure or error occurred in the complete run. In accordance with
the one-full-run test strategy, the entire suite was not rerun after this
narrow correction; thus the historical 3133-test execution is not described
as green. No other product code changed after that execution.

## Historical compatibility

The existing primary Quant API/database was inspected using the established
read-only audit streamed through stdin. It reported **224 historical state
records**, **0 payload checksum mismatches**, **0 authority fingerprint
mismatches**, and **0 protected raw/manifest checksum mismatches**. It found
7 datasets, 1 report-composition record, 1 terminal result, and 0 rewritten
legacy CMF Quant runs; that historical report has no accepted-report object.

Original Desk/ARK PostgreSQL environments were checked via `BEGIN READ ONLY`
with the previously recorded ordered Evidence `row_to_json` MD5 and full
workflow-row MD5. B, D, F, H, J, T, V, X, ARK-03, ARK-05 and ARK-07 matched
their prior count and both hashes (**11/11 accessible**). PRF-08O's original
container was not present, so its fresh comparison is **NOT VERIFIED**; no
replacement historical database was started. No historical data was changed,
recomputed, migrated or reseeded.

## Limits and live boundary

The Finding selector is bounded to 25 proposals and fails closed if the
eligible result set exceeds that bound; it does not silently drop results.
Current V1 comparisons expose p-values but no confidence intervals, so AI
cannot provide CIs. Language-level population generalization and implicit
contradiction detection remain conservative but not formally complete; exact
numeric/source validation and existing compatibility governance are the
enforced offline boundary. No OpenAI or Tavily calls were made in QNT-03.
The offline test double proves routing and rejection behavior, not the live
provider's real schema adherence or interpretive quality. A separately
authorized live provider check may assess that boundary later; it is not used
to establish deterministic statistical authority.

No migration, historical rewrite or push is part of this change.
