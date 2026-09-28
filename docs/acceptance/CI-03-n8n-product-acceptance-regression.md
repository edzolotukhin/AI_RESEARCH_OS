# CI-03 — n8n product acceptance finality regression

Date: 2026-09-28. Baseline branch `acceptance/live-desk-research-01`, commit `2050f59abf14cfc40c7a7be35ef75383240bd432`. Remote workflow: https://github.com/edzolotukhin/AI_RESEARCH_OS/actions/runs/36457227014. Unit tests, PostgreSQL repository contracts, PostgreSQL integration, and API tests passed. PostgreSQL API integration reported **48 tests, 42 passed, 6 failed, 0 errors**. All six failures were in `tests/integration/api/test_n8n_product_acceptance.py`:

- `test_api_restart_preserves_run_and_finality`
- `test_artifact_checksum_matches_content`
- `test_orchestrator_interruption_replay_same_key`
- `test_polling_requires_approved_review_not_completed_alone`
- `test_valid_authenticated_e2e_returns_approved_artifact`
- `test_worker_restart_continues_to_approved_artifact`

Each positive flow reached a terminal run with `final_review_verdict=None` instead of `approve`.

## Reproduction and first broken transition

The representative `test_valid_authenticated_e2e_returns_approved_artifact` failed identically in a clean container with declared dependencies and a disposable PostgreSQL database. A synthetic diagnostic run persisted three Sources and one Evidence, but readiness was insufficient. Its terminal payload had zero Findings, Insights, Reports, Reviews, and artifacts. Collection, extraction, and readiness tasks completed; Analyze, Report, and Review were skipped. The first broken transition for this positive acceptance fixture was **Evidence → authoritative readiness**, not Review or artifact persistence.

The n8n module still created each application container with the default deterministic retriever/extractor. Those return the identical undated `Acquired market report body text.` for multiple URLs, so current content-identity protection merges the aliases and temporal qualification excludes the undated Evidence for the canonical 2026 brief. This is the same **stale positive fixture class** corrected for Desk PostgreSQL tests in CI-02; it is not an orchestration, Review persistence, or production-code regression.

## Narrow correction

All four n8n test-container construction paths now use the tracked `dated_desk_overrides` fixture added by CI-02. It provides distinguishable fictional source content and an excerpt-grounded in-period observation date. The n8n harness API, idempotency/retry behavior, finality assertions, research readiness, Evidence integrity, and Review requirements are unchanged. No Findings or approval were inserted or fabricated.

## Verification

- Six formerly failing n8n tests: **6 run, 6 passed, 0 failures/errors**.
- Complete `test_n8n_product_acceptance.py`: **14 run, 14 passed, 0 failures/errors**.
- Exact PostgreSQL API integration discovery group from `.github/workflows/ci.yml`, with `-W error::ResourceWarning`: **48 run, 48 passed, 0 failures/errors** (63.845 seconds).
- Clean-environment proof: newly built `ai-research-os-ci03:local` image (`sha256:74a38926008d679123f65d899e8c9088f0594759af1a0835ae6b1d9c6c9358a4`) from the repository Dockerfile and declared `requirements.txt`; tests ran against dedicated disposable PostgreSQL database `ci03_test`. Both the n8n module and reused CI-02 helper are tracked repository files. No ignored helper, host-only package, external provider, or historical database was used.

Only an API integration test module changed; no shared product, Desk/ARK, Quantitative/QNT-02, migration, or provider path changed. Accordingly the full 3k offline suite was not repeated. A fresh remote workflow is still required after a separately authorized push. No OpenAI, Tavily, or live research calls occurred.
