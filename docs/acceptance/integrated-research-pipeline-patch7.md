# Integrated Research Pipeline — Patch 7 qualification

Date: 2026-11-12. Branch: `codex/integrated-research-pipeline`.
Patch 7 parent: `950b5bc113f8c5ecc36c58e7311fbf9fb37d7dc4`.
Combined release baseline: `ea6e41dc6b1410482f37ef8d6a5ea0b989103969`.
This is local release-candidate qualification, not production deployment approval.

## Integration corrections

- H3 now accepts reproducible DERIVED Findings through the existing typed-coverage validator, with qualifying input citations, dependency Findings and deterministic recomputation. Derived values remain calculated results, never fabricated input Evidence. Forged results/checksums fail before provider dispatch.
- Structured numerical Evidence contributes its validated metric, period, unit, geography and finite value to H3 scope. H3 citation catalog references are claim-scoped; several claims can cite the same displayed source without overwriting ownership.
- Revision loads the exact persisted ReviewResult rather than deserializing the smaller checkpoint summary as a full record. Project/run/design/report/attempt/verdict mismatches are rejected.
- Optional explicit `InformationNeed.output_format` supports `table` and `chart` only for OUTPUT. The default is omitted from serialization, preserving historical Design fingerprints. Missing format/dependencies cannot silently satisfy an OUTPUT obligation.
- OUTPUT materials are verified against frozen Design and validated H3 claims before review and again when projecting deliverables. Tables/charts contain those confirmed comparable values. Missing or altered materials fail closed. Existing PDF/PPTX renderers and Workflow Engine are unchanged.

## Regression failures and fixture corrections

The 24 known failures originated in citation fixtures that overwrote immutable Source fields while keeping the same ID. The fixture now reuses identical content or creates a separate immutable synthetic revision and rebinds only synthetic fixture Evidence. Historical persisted Evidence is not rewritten. The four affected suites passed: **53 tests and 19 subtests**.

Full qualification exposed additional stale expectations: concrete executor access after existing method wrappers; an invalid-objective fixture failing earlier IN validation; expected Alembic head 029 rather than 030; obsolete no-context navigation diagnostics; fake checksums and mismatched RQ fixture IDs. PostgreSQL regressions additionally required distinguishing Source IDs from URLs after REFETCH, and setting the migration fixture's process-local database context explicitly.

The crypto architecture test now enforces the API-key boundary in authentication/security components. Its previous blanket prohibition on `hashlib`, `hmac` and `secrets` throughout application code contradicted approved content digests and UX-01A password identity. See ADR-014 cryptography layering and `docs/architecture/UX-01A-pilot-identity-membership.md`. Production authentication, password handling and crypto implementations did not change. Other crypto boundary tests remain intact.

No failure was converted to skip/xfail. No historical production data was accessed or changed.

## Reproducible environment and commands

Disposable Docker PostgreSQL 16: task-labelled container `airos-patch7-pg16`, published only on `127.0.0.1:55439`. Fresh databases: `patch7_test` and `patch7_migration_test`. All database credentials are synthetic and local. Apply repository Alembic migrations to head `030_source_revisions`; migration tests also exercise legacy 029 upgrade/backfill and schema lifecycle.

PowerShell setup (supply the disposable connection URLs through environment variables):

```powershell
$env:POSTGRESQL_INTEGRATION_TESTS='1'
$env:POSTGRESQL_DISPOSABLE_TEST_DATABASE='1'
$env:DATABASE_URL_TEST='<isolated patch7_test PostgreSQL URL>'
$env:DATABASE_URL_MIGRATION_TEST='<isolated patch7_migration_test PostgreSQL URL>'
$env:PDF_FONT_PATH='<temporary DejaVuSans.ttf path>'
python -m pytest tests/integration/postgresql -q --tb=line --junitxml="$env:TEMP/airos-patch7-postgresql-final.xml"
$env:AIROS_ACCEPTANCE_ARTIFACT_DIR='<acceptance package outside the Git worktree>'
python -m pytest tests/integration/postgresql/test_integrated_research_acceptance.py -q --tb=short --junitxml="$env:TEMP/airos-patch7-e2ec-final.xml"
$env:DATABASE_URL=$env:DATABASE_URL_TEST
python -m pytest tests/integration/postgresql/test_q1_17_quantitative_ui_persistence.py -q --tb=short
```

The 88 PostgreSQL cases outside `tests/integration/postgresql` were also run with the same disposable URLs: `tests/application/execution/test_lease_guards.py`, `tests/application/ports/test_postgresql_repository_contracts.py`, PostgreSQL readiness, PostgreSQL API/authorization/idempotency/external orchestration contracts and `tests/integration/worker/test_process_crash_recovery.py`. Exact node IDs and results are included in the package test summary.

For the offline full suite, clear PostgreSQL opt-in variables in that process and retain `PDF_FONT_PATH`:

```powershell
python -m pytest tests -q --tb=line --junitxml="$env:TEMP/airos-patch7-final-all.xml"
node --check infrastructure/documents/pptx_runtime/render.mjs
node --check infrastructure/documents/pptx_runtime/paginate.mjs
git diff --check
```

Pinned PptxGenJS dependencies were installed using `npm ci --prefix infrastructure/documents/pptx_runtime --omit=dev --ignore-scripts --no-audit --no-fund`. DejaVu was obtained inside a separate task-only Docker container and copied to a temporary directory, not installed globally or committed. No external AI calls were made; HTTP acquisition used loopback fixtures.

## Results

| Qualification | Passed | Failed | Skipped | Subtests |
|---|---:|---:|---:|---:|
| Full offline suite | 4554 | 0 | 353 | 1147 |
| Full PostgreSQL suite | 276 | 0 | 2 | 26 |
| PostgreSQL contract/API/worker cases outside that directory | 88 | 0 | 0 | 47 |
| Final E2E-C plus additional negative cases | 10 | 0 | 0 | 0 |
| Separate quantitative fresh-context test | 1 | 0 | 0 | 0 |

Counts overlap: focused reruns are not added to full-suite totals. Pytest JUnit `tests` also counts successful subtests; full offline JUnit has 6054 results and 4907 test cases. PostgreSQL full JUnit has 304 results and 278 test cases. Three additional negative cases were qualified in the final focused E2E run after collection of the full PostgreSQL suite.

Offline skips primarily represent PostgreSQL tests without opt-in; the 88 outside the main PostgreSQL directory passed separately as well. Remaining existing skips require unavailable historical acceptance artifacts, a DESNZ workbook, or a Linux-specific hard-coded font path. Real Desk PDF/PPTX rendering is independently required and passed in E2E-C. PostgreSQL's two skips were: historical offline replay needing a source database/snapshot (deliberately not connected to production), and the quantitative test requiring `DATABASE_URL`. The latter was rerun separately and passed. Thus the only unexecuted PostgreSQL case needs a historical source snapshot, not synthetic E2E-C data.

## E2E proof

`tests/integration/postgresql/test_integrated_research_acceptance.py` uses production ApplicationContainer, actual scheduler/worker/checkpoints, actual repositories, HTTP retrieval, XLSX extraction, deterministic Evidence mapping, readiness, Analysis, H3, Review/Revision, Finalization and production renderers. Only external Search/LLM provider boundaries use deterministic synthetic adapters.

- E2E-A: existing HTML is REFETCHed through landing → resource → extensionless octet-stream XLSX. Three-hop acquisition paths, cell/header locators, immutable historical Source/citation and fresh PostgreSQL reload are asserted. Source revisions, concurrency, backfill and identity cases also pass in `test_source_revisions.py`.
- E2E-B: synthetic observations 2019=1000, 2020=950, 2021=900 produce one ACQUIRED Finding and six validated DERIVED Findings: YoY −50/−5%, −50/−5.263158%; cumulative −100/−10%. Dependency/evidence lineage, rounding and complete coverage are asserted.
- E2E-C: first Review requests revision; second Review approves revision 2. OUTPUT table and native PPTX chart contain the actual verified series. PDF text and PPTX table/chart XML are checked. Approved files, checkpoints and authoritative COMPLETED survive a fresh ApplicationContainer. Draining after reload creates no additional Sources, Evidence, Findings or artifacts.
- Insights must reference the actual persisted Findings and share project/design/run scope; their IDs survive reload. Persisted H3 claims cover every non-OUTPUT IN, carry citations and real Evidence refs, and contain only confirmed source/calculated values. The PDF contains the calculated values with Ukrainian decimal formatting as well as the input series.
- Negative cases: missing year → INSUFFICIENT without Report; incompatible units/geography reject derivations; ambiguous headers reject Evidence (structured pipeline test); persisted invalid citation does not qualify; provider outage and a test-only PostgreSQL Findings insert failure → FAILED. No production fault injection switch was added.

The exported package contains synthetic XLSX, actual PDF/PPTX and `e2e-c-proof.json` (Design, cell provenance, acquisition paths, Findings/derivations, typed claims, verified OUTPUT). It is evidence for independent review, not a substitute for that review.

## Release, migration and rollback checklist

1. Obtain separate release approval. Verify exact target SHA, clean release diff and CI; inventory current deployed SHA, actual database revision and feature settings without exposing secrets.
2. Create and verify a fresh backup including actual release/schema metadata, checksum and Restic integrity; establish a tested isolated restore path.
3. Pause new dispatch and drain workers before changing code/schema. Do not mutate running research snapshots. Rehearse the exact deployment against an isolated restored database first.
4. This combined release includes Patch 1 migration **030_source_revisions** after 029. Patch 7 adds **no migration**. Review legacy identity ambiguity refusal; an ambiguous legacy backfill must abort, never guess binary content equality.
5. Under separate approval apply the exact reviewed migration and deploy matching API/worker images. Check actual Alembic head, API/worker readiness, task ownership and logs. Smoke-test a synthetic isolated project with explicit OUTPUT contracts before admitting new production dispatch.
6. Rollback before revision writes may use the prior code/schema only after downgrade preconditions are established. Migration 030 deliberately refuses downgrade if revisions share canonical URLs. After new revision writes, do not delete revisions or rewrite Evidence to force downgrade: coordinate verified backup restoration or a forward fix while workers remain drained. Preserve the new-state backup/audit before restore.

## Remaining limitations

- Composed DERIVED H3 authority remains unsupported and fails closed; ordinary legacy ACQUIRED composition/replay regressions pass. This qualification does not claim composed DERIVED replay support.
- Historical untyped OUTPUT descriptions are not guessed into table/chart semantics. Explicit missing formats are an actionable contract error, not a fabricated success; historical persisted snapshots are not rewritten.
- Historical offline replay without its source snapshot remains unverified. Existing Starlette/Alembic deprecation warnings remain non-failing.
- Production rollout, historical research recovery, paid-provider behavior and independent reviewer approval are outside this local qualification.
