# AI Research OS — Project Handoff

## Current state

- Production baseline: `8d9876fbff9539abef641921ee5ab73f121c2b1f` (Merge #37).
- Active integration branch: `codex/r1-temporal-integration`.
- R1 scope: grounded observation-period normalization in Evidence extraction/temporal qualification.
- Production is not changed; no deployment or real research run is authorized by this handoff.

## Architecture constraints

- Citation Integrity remains fail-closed.
- Publication/retrieval dates never establish observation periods.
- Ambiguous dates without an explicit year remain unknown.
- Readiness, Analysis, Report, workflow orchestration, schema and migrations are unchanged.
- `PARTIAL` and `INSUFFICIENT` remain authoritative product outcomes; technical workflow completion is not product success.

## Verified evidence

- R1 targeted regression: 46 passed, 18 subtests.
- Structured extraction regressions: 28 passed.
- R1 changes are limited to the two temporal/extraction modules and their focused test file.
- Controlled local E2E previously proved Findings, DERIVED Findings, Insights and PDF/PPTX; production case still requires durable diagnostics.

## Current blocker

The real Ukraine population run has persisted Evidence but no Findings or Insights. The next diagnosis must use durable task, extraction, readiness and analysis records; counts of Sources alone are not sufficient evidence.

Recovery 2 preliminary gate (2026-11-13): R1 targeted regression remains green (`46 passed, 18 subtests`). A disposable PostgreSQL run could not be qualified because Docker Engine was unavailable in the execution environment. The available local production-mode test uses deterministic search/evidence and a mock LLM, and did not complete within the bounded run; it is not evidence of a real public-source E2E. No external or paid AI calls were made.

Recovery 2 harness: `tools/real_research_e2e.py`, `.github/workflows/real-research-e2e.yml` and `docker-compose.recovery2-e2e.yml` provide a manual-only, fail-closed provider-backed run. The harness uses the public Research API and the existing worker pipeline, writes aggregate diagnostics only, and requires staging-only Search/LLM secrets plus explicit `run_real_e2e=true` and numeric limits. Preflight review verified Python compilation, fail-closed behavior and whitespace; external providers have not been called. Stage call/token caps are passed to both API and Worker through the disposable overlay. The application caps are hard execution limits; a hard monetary cap is not available in the current application contract, so owner/provider billing limits remain required before execution. Early failures now also write sanitized diagnostics.

CI corrective review (2026-11-13): fixed the structured-output architecture violation in the harness by using `JSONDecoder.decode`, and restored grounded textual quarter qualification by comparing normalized source/reference periods only when an explicit source spelling is present. Targeted regression: `43 passed, 22 subtests`; no provider calls were made.

## Next milestone — Recovery 2

Run a controlled, non-production E2E qualification of the R1 integration with a 2015–2021 fixture once isolated PostgreSQL/Docker is available; separately obtain explicit approval and an enabled, bounded provider budget before any real public-source/AI execution. Then classify the production case from existing durable diagnostics before any further code change.

## Collaboration rule

ChatGPT/Codex must preserve this handoff, avoid production mutations, and report evidence with file/test/commit references. The product owner approves commits, push, deployment and real research runs separately.
