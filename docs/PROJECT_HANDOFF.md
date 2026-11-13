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

## Next milestone — Recovery 2

Run a controlled, non-production E2E qualification of the R1 integration with a 2015–2021 fixture, then classify the production case from existing durable diagnostics before any further code change.

## Collaboration rule

ChatGPT/Codex must preserve this handoff, avoid production mutations, and report evidence with file/test/commit references. The product owner approves commits, push, deployment and real research runs separately.
