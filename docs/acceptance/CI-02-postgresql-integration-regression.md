# CI-02 — PostgreSQL integration regression

Date: 2026-09-28. Branch: `acceptance/live-desk-research-01`.
Remote commit: `36ae94921f0bb2784dc4e67ab04448d5c1d76003`.
GitHub Actions: https://github.com/edzolotukhin/AI_RESEARCH_OS/actions/runs/36430286149 (job `108954412127`). Unit tests and PostgreSQL repository contracts succeeded; the PostgreSQL integration step reported 156 tests, 13 failures, 2 errors, 1 skip. The raw GitHub job-log endpoint returned HTTP 403, so the exact remote names of all 15 symptoms could not be independently read. The repository's exact CI integration discovery command was reproduced locally.

## First broken transition

The representative `test_two_same_brief_runs_complete_with_shared_sources` originally reproduced `finding_count == 0`. A synthetic run had three acquired Source records, one persisted Evidence, and a completed workflow, but `research_readiness` was `insufficient_research`, `ready_for_analysis=False`, blocking `in-rq-1`, termination `no_material_improvement`. Analyze, Report, and Review tasks were skipped. Thus the first unexpected transition for this *positive downstream fixture* was Evidence → authoritative readiness, not Findings persistence or Review persistence. `test_two_runs_keep_independent_review_and_artifact_state` had the same downstream symptom (`final_review_verdict=None`). No Findings or Review were fabricated.

The common deterministic retriever returned exactly `Acquired market report body text.` for three different URLs. Current content-identity protection correctly treated these as aliases of one acquired content. The deterministic extractor's statement/excerpt supplied no observation period. The canonical brief specifies `2026`; current temporal qualification correctly refuses unknown observation time for that dated need. Consequently the old synthetic fixture no longer met the precondition for tests that intend to exercise Analysis, Findings, Insights, Report, Review, and artifacts. This is a stale positive integration fixture, not a reason to relax production sufficiency, citation, temporal, or deduplication rules.

## Correction and CI-01 relation

Added a test-only, explicit dated Desk source/retriever fixture. It uses three distinguishable fictional observations of Purina brand awareness in Germany's pet-food market and grounds the `2026-06-30` observation date in both stored source text and extracted Evidence. Only the positive PostgreSQL Desk integration flows opt into it. The default deterministic smoke provider and all product paths remain unchanged. Existing downstream assertions remain intact.

CI-01's SAV `output_format="dict"` correction is unrelated: the failed representative Desk path has no SAV upload. CI-01's tracked Quantitative PostgreSQL helper replacement is likewise unrelated to this Desk fixture. Neither CI-01 change was reverted. QNT-02 exact method pin, dataset binding, and Quant no-ARK behavior were not changed.

## Reproduction and verification

- Representative repeated-run test: failed before correction (`finding_count=0`), passed after correction.
- Windows host, before correction, exact 156-test PostgreSQL group: 14 failures, 3 errors, 1 skip. Fourteen failure names and three error names were collected locally; the extra local PDF/PPTX errors arose because the host Python lacked the declared `reportlab` package. A later Windows rerun after the fixture correction had only 2 failures, 1 error, 1 skip: PDF/PPTX on missing host dependency, plus migration smoke because the previously exercised disposable migration database was no longer pristine. These are local environment/test-isolation effects, not product-code changes.
- Fresh image `ai-research-os-ci02:local` (`sha256:168c3377f7d0dfef9e9abd82ffef2f6b24ef9be6daba2ae85db37c6452616f62`) built from the current source with the declared `requirements.txt`, pinned Node dependencies, and DejaVu font. It used only the dedicated `ai_research_os_ci02_test_postgres` PostgreSQL container and separate disposable `ci02_test` and freshly recreated `ci02_migration_test` databases. Exact CI discovery group with `-W error::ResourceWarning`: **156 run; 155 passed; 1 skipped; 0 failures; 0 errors** (137.123 seconds). The migration smoke used its separate pristine database.
- Focused dated-source fixture test: 1 passed, checking date grounding and distinct content.
- No shared production module changed, so unrelated Desk/CMF/Quant/API/worker suites were not rerun. Their product behavior is unchanged; the affected PostgreSQL group includes Desk and Quant integration scenarios.

The corrected tests import only tracked repository support after staging; no ignored helper, provider credential, historical acceptance artifact, or local-only Python package is required by the clean container. The newly built image includes the changed test sources via the repository's Dockerfile, and the PostgreSQL test databases are disposable. This verifies the local correction, **not** a new GitHub Actions result for a future commit.

## Limitations

The remote raw log HTTP 403 prevents a one-to-one naming of the 13 remote failures and 2 remote errors. Local reproduction identified the shared first broken transition, and the exact 156-test CI group is green in the clean container. A new remote run is still required after the local commit is pushed by the owner or a separately authorized task. No paid provider calls or live research occurred.
