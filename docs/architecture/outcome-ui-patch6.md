# Authoritative research outcome and UI — Patch 6

Parent: `b9e24cbcc2f75d91f9b3645c0c1c5526f5f7f973`.

## Read-only contract

Workspace consumes the existing `ResearchRunResultQueryService`, which delegates
product resolution to `derive_authoritative_outcome`. No alternative outcome
resolver, workflow transition or durable outcome rewriting is introduced.
Query-time resolution now passes the authoritative unresolved coverage IDs and
technical-failure flag into that resolver. In particular, a stronger coverage
gate's unresolved IN cannot disappear merely because some Findings were persisted.
Ambiguous durable metadata is projected as an unavailable/unknown result, not
success and not a fabricated methodological failure.

The shared presentation mapping is used by workspace, Desk workbench and project
outputs. The generic result presentation also recognizes the four product states.

| Research outcome | Ukrainian UI |
| --- | --- |
| COMPLETED | Завершено |
| PARTIAL | Завершено з обмеженнями |
| INSUFFICIENT | Недостатньо матеріалів |
| FAILED | Технічна помилка |
| Nonterminal execution, no final outcome | Виконується |
| Completed execution, ambiguous/missing outcome | Результат не визначено |

Legacy APPROVED maps to completed; NOT_READY to insufficient materials;
EXECUTION_FAILED to technical error. QUALITY_REJECTED retains its methodological
attention state. Paused/cancelled executions retain explicit Ukrainian labels.
A nonterminal execution never displays a final research outcome.

## Availability, reasons and history

Run-scoped Findings, Insights, Reports and Reviews are counted independently of
whether the product outcome can be resolved. Availability never establishes
research success. PDF/PPTX indicators use the existing read-only deliverables
catalog, filtered to the selected run; unreadable metadata stays unknown.
Links retain access to stored reports/files, including previous attempts.

Workspace and outputs select the latest Desk attempt through existing persisted
replacement lineage ordering. Design-generation workflows are excluded. Workspace
history links retain all previous Desk attempts and their own projected states;
a newer insufficient/failed run cannot erase an older successful result.

Bounded Ukrainian explanations show missing IN, observations, dependencies and
metric/unit/geography conflicts from durable readiness/coverage metadata. Provider
errors and raw research payloads are not exposed. A completed insufficient,
partial or unknown run no longer presents a 100% research-success progress bar;
any shown percentage explicitly describes execution stages.

The live Desk page reloads on terminal detail HTTP 409 as well as on a complete
detail projection: an ambiguous terminal outcome no longer remains stuck in a
running state. The reloaded terminal page stops polling and shows unknown status.

## Qualification

Tests cover actual resolver and memory repository projections, all four outcomes,
execution/product separation, missing Report/outcome, conflicting metadata,
readiness reasons, real stored Report availability, run-scoped file metadata,
latest-attempt precedence, read-only history and real authenticated UI GET pages.
Node executes the real polling script with deterministic HTTP boundary fixtures.
No actual research workflow or external AI provider is invoked.

Final result: **434 passed, 50 subtests passed, 0 failed, 0 skipped**. This includes
the complete query and UI suites plus authoritative outcome and Patch 5 classified
readiness regressions. One existing Starlette/httpx deprecation warning remains.
AST validation, JavaScript syntax validation and `git diff --check` pass.

```powershell
$env:PDF_FONT_PATH='C:\Windows\Fonts\arial.ttf'
python -m pytest tests/application/query tests/api/ui tests/application/research_quality/test_authoritative_outcome.py tests/application/research_quality/test_classified_readiness.py -q --tb=short
git diff b9e24cbcc2f75d91f9b3645c0c1c5526f5f7f973..HEAD --check
```

Changed production code is limited to query/presentation, templates and read-only
facade wiring. No migration, Source/Evidence/Analysis/Readiness/H3/Workflow Engine
change; no production, push, PR, merge or deployment.

## Changed files

- `application/query/research_outcome_presentation.py`
- `application/query/research_run_result_query_service.py`
- `application/query/project_workspace_query_service.py`
- `application/query/project_workspace_views.py`
- `application/query/desk_workbench_query_service.py`
- `application/query/project_outputs_query_service.py`
- `api/ui/project_workspace_facade.py`
- `api/ui/presentation.py`
- `api/templates/projects/detail.html`
- `api/templates/research/workbench_overview.html`
- `api/static/desk-workbench.js`
- `tests/application/query/test_research_outcome_ui.py`
- `tests/api/ui/test_research_product_outcome.py`
- `docs/architecture/outcome-ui-patch6.md`

## Mandatory Patch 7 acceptance blocker

The **24 pre-existing baseline failures** documented in
`readiness-coverage-patch5.md` remain unresolved. They must be resolved or explicitly
adjudicated before Patch 7 acceptance; Patch 6 PASS is not a clean full-repository
CI claim. Their Source immutability fixtures are outside this patch's UI/query
scope and were not weakened or bypassed. Patch 7 must also perform the integrated
product-level E2E acceptance and deferred OUTPUT/deliverable verification.
