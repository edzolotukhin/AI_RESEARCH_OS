# Recovery 2 — Forensic Diagnostics & Risk Assessment

## 1. Executive Summary

Последний provider-backed запуск `43570382878` не достиг Evidence и последующих стадий.
Подтверждённая причина отказа — `SourceAcquisitionError`: успешно acquired только 2
источника при минимуме 3. `source_count=12` означает количество persisted source records
проекта и не является числом успешно retrieved источников.

Точная причина, по которой остальные кандидаты не дали третий acquired source, по
сохранённому artifact не устанавливается: в нём нет `SourceAcquisitionSummary`, selection
decisions или funnel events. Поэтому HTTP failures, unsupported content, duplicates,
qualification и budget exhaustion остаются неразделёнными.

Deterministic reproduction выявила отдельный дефект ранней наблюдаемости: summary
создавался, но не записывался в shared state до исключения. Это исправлено локально;
quality gate и minimum `3` сохранены.

**Вердикт:** следующий real E2E — `NO-GO` до получения acquisition funnel diagnostics.
Минимальный безопасный шаг — использовать диагностический commit `21f171251a8ee48a1b7bb574c39ce467385c2686`
и собрать новый bounded run только после отдельного разрешения на provider calls.

## 2. Scope & Evidence Inventory

| Evidence | Что подтверждает |
|---|---|
| GitHub run `43570382878` | preflight/schema/API/Worker/key registration passed; real E2E failed; PDF diagnostics skipped |
| Run artifact `recovery2-real-research-e2e` | агрегированные diagnostics предыдущего harness; acquisition funnel breakdown отсутствует |
| `application/sources/source_acquisition_service.py:194-320` | построение query portfolio, сбор candidates, acquisition summary и minimum gate |
| `application/sources/source_acquisition_service.py:724-924` | selection, attempt cap, budget stop, duplicate tracking и retrieval result accounting |
| `application/research_funnel_telemetry.py:74-196` | durable bounded search/candidate/acquisition/decision telemetry |
| `application/executors/search_executor.py:25-32` | сохранение `source_acquisition` в shared state/task result |
| `application/runtime/workflow_runtime_persister.py:110-162` | сохранение failed-task snapshot при наличии funnel/diagnostic state |
| `tools/real_research_e2e.py:223-255` | прежний набор API diagnostics и добавленная extraction durable results |
| `tests/tools/test_real_research_e2e_contract.py` | 6 targeted tests, включая sanitised acquisition projection |

Секреты, provider payloads, полный текст источников и credentials в отчёт не включаются.

## 3. Execution Timeline

По GitHub job metadata:

| Stage | Status | Evidence |
|---|---|---|
| Workflow authorization/preflight | completed | job `preflight`, success |
| Checkout/dependencies | completed | `real-e2e`, success |
| Schema | completed | `Apply schema`, success |
| Isolated API/Worker | completed | `Start isolated API and Worker`, success |
| Disposable API key | completed | `Register disposable API key`, success |
| Research Brief/Design/Approval | completed | provider-run diagnostics supplied by owner; no failure reported here |
| Search/Source Acquisition | failed | `SourceAcquisitionError`, acquired 2 < minimum 3 |
| Evidence | not reached | no Evidence persisted for this run |
| Readiness | not reached | blocked by failed Search |
| Analysis | not reached | blocked by failed Search/Readiness |
| Findings/Insights | not reached | no persisted results |
| Report/Review/Finalization | not reached | no persisted results |
| PDF diagnostics | skipped | separate job skipped because real E2E mode failed |

Thus later-stage risks cannot be inferred from this execution; they require separate
free tests or a future provider-backed run after acquisition is observable.

## 4. Confirmed Root Causes

### 4.1 Confirmed execution failure

`SourceAcquisitionService.acquire_for_context()` builds the portfolio and candidates,
then raises when `acquired < self._budget.min_successful_sources`
(`source_acquisition_service.py:210-320`). The recorded error states `2` acquired and
minimum `3`. This is a quality-gate refusal, not evidence of a valid partial research
product.

### 4.2 Confirmed metric distinction

The acquisition summary separately records `candidate_count_raw`,
`candidate_count_unique`, `candidates_attempted`, `acquired_count`, `failed_count`,
`skipped_duplicate_count` and `skipped_budget_count`
(`source_acquisition_service.py:268-299`). The API-level `source_count=12` is a project
source-record count and cannot identify which of those categories accounts for the gap.

### 4.3 Confirmed observability gap

The application persists `source_acquisition` through `SearchExecutor` and the generic
task-result codec, while funnel telemetry persists candidate and acquisition events
(`search_executor.py:25-32`, `research_funnel_telemetry.py:85-106`). The old E2E harness
only collected resource counts and research-result fields
(`tools/real_research_e2e.py:223-247`), so the artifact did not expose those durable
fields.

### 4.4 Deterministically reproduced early-failure gap

В deterministic test с `acquired_count=2` и `min_successful_sources=3` исключение
возникает после построения summary. До исправления `SearchExecutor` не успевал выполнить
свою запись shared state, потому что она находилась после `acquire_for_context()`.
В результате failed-task persistence мог сохранить funnel journal, но не summary counters.
Минимальный fix в `source_acquisition_service.py` записывает
`context.write_shared("source_acquisition", summary.to_dict())` непосредственно перед
обоими minimum-gate exceptions. Это не меняет selection, retrieval, retry, budget или
quality-gate semantics.

## 5. Source Acquisition Failure Analysis

### Definitions

- **Discovery:** provider query execution and raw candidate production. In code this is
  `portfolio_queries`, `candidates_found` and `candidate_count_raw`.
- **Deduplication:** grouping/canonicalization and content identity checks. The summary
  exposes `candidate_count_unique` and duplicate counters.
- **Selection/qualification:** `_select_groups()` and candidate decision actions. A
  candidate can be ineligible or exhausted before retrieval.
- **Retrieval:** `_resolve_source_for_group()` and retriever result status. Only
  `ACQUIRED`/`TRUNCATED` contribute to `acquired_count`; failed/unsupported statuses
  contribute to failures and categories (`source_acquisition_service.py:813-868`).
- **Budget:** source group cap and wall-clock budget can mark pending candidates as
  skipped (`source_acquisition_service.py:760-780`).
- **Persistence:** a source record may exist even when its retrieval status is failed or
  unsupported; persistence therefore does not prove successful acquisition.

### What is and is not proven

| Question | Finding |
|---|---|
| Were 12 records persisted? | Confirmed by run diagnostics. |
| Were exactly 2 successful acquisitions? | Confirmed by the durable error/diagnostics. |
| How many were raw vs unique candidates? | Unknown in the old artifact. |
| How many failed HTTP/retrieval? | Unknown for the old run; deterministic fixture now proves the counters are retained for future failed runs. |
| How many were duplicate content/URL? | Unknown. |
| How many were ineligible/exhausted? | Unknown. |
| Did source/time budget stop acquisition? | Unknown; `budget_exhausted` and skip counters were not captured. |
| Were retries available? | The code has a bounded retrieval portfolio and continuation path, and it continues through pending groups under the cap. No evidence shows that a retry would have been attempted in this specific run. |
| Is there a confirmed code defect? | Yes, an early-failure observability defect; no functional acquisition defect is proven. |

The source minimum must not be lowered and failed records must not be counted as
successful. A code fix is not justified until the missing counts identify a concrete
failure mode.

## 6. Full Pipeline Risk Register

| ID | Risk | Confirmation | Probability | Impact | Priority | Mitigation |
|---|---|---|---|---|---|---|
| R2-A1 | Acquisition cannot reach minimum | **CONFIRMED**: 2 < 3 | High | Critical | P0 | Capture funnel categories; fix only the proven retrieval/selection cause |
| R2-A2 | Candidate count confused with acquired count | **CONFIRMED**: 12 vs 2 | High | High | P0 | Keep distinct counters and fail closed at minimum gate |
| R2-A3 | Root cause lost from E2E artifact | **CONFIRMED**: old artifact lacks summary/events | High | High | P0 | Use bounded durable-results projection in commit `21f17125` |
| R2-A4 | Retrieval HTTP/content failures | **UNKNOWN** | Medium | High | P1 | Obtain failure-category counts; free unit/integration tests for categories |
| R2-A5 | Duplicate/identity collapse reduces usable sources | **UNKNOWN** | Medium | Medium | P1 | Obtain unique/duplicate counters and content identity decisions |
| R2-A6 | Source/time cap leaves candidates unattempted | **UNKNOWN** | Medium | High | P1 | Record budget flags and skipped-budget counts |
| R2-A7 | Evidence quality/temporal qualification blocks later stages | **POTENTIAL**; R1 covers grounded periods | Medium | Critical | P1 | Run deterministic qualification tests; provider run only after acquisition gate |
| R2-A8 | LLM/provider timeout, rate limit or schema failure | **POTENTIAL**; not reached or not isolated here | Medium | High | P1 | Preserve per-stage error categories and hard call/token settings |
| R2-A9 | Report/PDF/finalization failure | **POTENTIAL**; separately seen in prior diagnostics, not this run | Medium | Medium | P1 | Keep PDF diagnostics separate and run targeted free acceptance |
| R2-A10 | Technical status could be mistaken for product success | **POTENTIAL**; acceptance harness now rejects failed/missing outcomes | Low/Medium | High | P1 | Require terminal outcome and stage success in harness |
| R2-A11 | Provider-backed behavior differs from deterministic tests | **CONFIRMED as test limitation** | High | High | P1 | Treat real E2E as separate acceptance gate |
| R2-A12 | Diagnostics contain sensitive payloads | **POTENTIAL** | Low | High | P2 | Aggregate-only projection; omit URLs, content and IDs |

Methodological risks (temporal scope, geography, comparable definitions, evidence
coverage and lineage) remain material even after acquisition succeeds. They are not
proven failures in this run because Evidence was never reached.

## 7. Diagnostic Coverage & Blind Spots

Commit `21f17125` adds `_source_acquisition_diagnostics()` in
`tools/real_research_e2e.py`. It reads `/workflow-runs/{run_id}/results`, extracts the
durable `source_acquisition` summary and `research_funnel_v1`, and emits only aggregate
counts: query/candidate/attempt/acquired/failure/duplicate/budget metrics, failure
categories, selection actions/reasons and funnel event/status counts. Targeted tests
also verify that URLs and private IDs are absent from the projection.

This commit is observability-only. It cannot make a failed acquisition succeed, cannot
retry providers, cannot change the source minimum, and cannot reconstruct data that was
not present in the old artifact. It can establish the missing split on a future run if
the task result is available through the API.

Remaining blind spots:

1. The old run cannot be retroactively classified without its missing task snapshot or
   service logs containing the summary.
2. Aggregate counts do not prove semantic correctness of individual sources.
3. Provider-side rejection/rate-limit details may be unavailable by design.
4. No provider-backed retry should be inferred from the presence of a portfolio; actual
   invocation counts require the new telemetry.

The deterministic closure also changes the acquisition service to persist its summary
before raising the minimum gate, and updates the focused source-acquisition tests. The
old artifact remains unchanged and therefore cannot be retroactively enriched.

Local qualification after the fix: source acquisition/service and budget tests plus the
E2E diagnostics contract: **24 passed**. R1 temporal/citation targeted tests:
**42 passed, 22 subtests passed**. `git diff --check`: pass. No full suite was run.

Diagnostic-closure qualification added a failed-checkpoint regression and re-ran the
relevant funnel, acquisition, budget, harness and persister tests: **48 passed**.
The PostgreSQL funnel test was not executed because Docker is unavailable in this
environment; it remains a required external qualification, not a claimed PASS.

Prepared PostgreSQL qualification test:
`tests/integration/postgresql/test_prf08s_funnel_telemetry.py::FunnelPostgreSQLTests::test_failed_acquisition_summary_survives_reload_and_sanitized_projection`.
It covers both acquired `2` and acquired `0`, persists through the real workflow-run
repository, reloads through a fresh repository instance, maps the result through the
API task-result response shape, and applies the same sanitised harness projection.
Execution is still pending because Docker is unavailable locally.

## 8. Remediation Options

### P0 — acquisition evidence before code change

Use the pinned integration commit `21f17125` in the workflow and collect the bounded
summary on the next explicitly approved provider run. Acceptance requires non-null
acquisition diagnostics and a classification of every gap between raw, unique,
attempted, failed, duplicate, budget-skipped and acquired.

### P1 — only after classification

If HTTP/content failures dominate, add a narrowly bounded retriever fix and free
regression tests. If selection/qualification dominates, correct the relevant rule and
test candidate classification. If budget exhaustion dominates, inspect configured caps
and timing; do not silently raise them or weaken quality gates. If duplicates dominate,
verify canonical/content identity before changing anything.

### P2 — durable operational diagnostics

Keep aggregate funnel telemetry in CI artifacts, ensure early failure still uploads it,
and add a free fixture test for the complete acquisition funnel. No new crawler or
research orchestration is warranted by current evidence.

## 9. Prioritized Action Plan

1. **P0:** review the deterministic early-failure fix and ensure the workflow pins its
   resulting integration SHA before any provider run.
2. **P0:** obtain one explicitly approved bounded provider run; do not treat it as a
   product acceptance run unless acquisition diagnostics are present.
3. **P1:** classify the gap from durable counters; implement only the demonstrated local
   defect, with free regression tests first.
4. **P1:** re-run deterministic acquisition/quality tests and inspect Evidence/Readiness
   contracts before any paid rerun.
5. **P2:** after Search is proven, separately qualify Evidence, Readiness, Analysis,
   Report and Finalization; this failed run supplies no evidence for those stages.

## 10. GO/NO-GO Recommendation

**NO-GO.** Current evidence does not establish that unchanged Source Acquisition can
reach the minimum of 3, and it does not establish why it did not. A next provider run is
not justified as an unbounded retry; it requires explicit authorization, diagnostic
artifact verification and the existing 24 LLM-call / 12-source / 4096-token / timeout
limits.

The architecture is sufficient to express the required fail-closed pipeline contracts,
but operational readiness for a quality research report is not established. Search
failure prevented all downstream qualification.

## 11. Open Questions for Independent Auditor

1. What were `candidate_count_raw`, `candidate_count_unique` and `candidates_attempted`
   in run `43570382878`?
2. Which failure categories contributed to the two-source shortfall?
3. Were duplicate content identities or canonical URLs responsible for any discarded
   candidates?
4. Was `budget_exhausted` true, and what were the skipped-budget and skipped-ineligible
   counts?
5. Did the provider return additional candidates after the initial portfolio, or was
   continuation never reached because Search failed at the first acquisition gate?
6. After acquisition succeeds, do real Evidence periods, readiness, Analysis, report and
   finalization satisfy their separate acceptance contracts?

## Final Classification

- Last real E2E outcome: `FAILED`.
- Confirmed root cause: acquisition quality gate observed only 2 successful sources;
  the old run's detailed candidate breakdown is not recoverable.
- Confirmed secondary defect: early failure did not persist `source_acquisition` summary;
  deterministic fix and tests now close this observability gap for future runs.
- Cross-process PostgreSQL/API reload: `NOT VERIFIED` in this environment because the
  disposable PostgreSQL runtime could not be started (`docker` unavailable).
- Exact breakdown of the remaining candidates: `UNKNOWN` from retained evidence.
- Diagnostic commit `21f17125`: observability improvement, not a functional fix.
- Uncommitted diagnostic-closure diff: `application/sources/source_acquisition_service.py`,
  `tests/application/sources/test_source_acquisition_service.py`, and
  `tests/application/sources/test_source_acquisition_budget.py`; it preserves the
  minimum gate and only makes the already-built summary durable before failure.
- Production impact: none; no production access or mutation was performed.
- Next real E2E: `NO-GO` until diagnostic coverage is accepted and a bounded run is
  separately authorized.
