# ARK-06 — readiness Source repository integration

Date: 2026-09-27. Offline remediation only. No OpenAI/Tavily, live scenario,
historical recomputation, migration or push.

## Baseline and precise cause

Branch `acceptance/live-desk-research-01`, initial HEAD
`0d2752d88a613fae9b7e972200f6a069429bd1da`, ahead32/behind0 local tracking.
Tracked/index clean initially; historical untracked artifacts preserved.
ARK-05 run `3ce5679a-ff45-564f-be97-12df68ed7643` is retained as FAILED acceptance.

`VersionedDeskExecutor._kernel` built `ResearchReadinessService` with evaluator
and Evidence repository but omitted Source repository. The service defaulted
that dependency to None. ARK-04 canonical citation validation correctly failed
closed, but readiness consequently saw an empty set rather than the five valid
qualifying records visible to the adapter. No citation-coordinate defect was
involved. This is the production path, not an inference from test mocks.

## Production path and call-site review

|Path|Source dependency / authoritative semantics|
|---|---|
|Evidence persistence → DeskAdapter.qualified|Existing extraction Source repository → shared qualifying_evidence|
|VersionedDeskExecutor._kernel → readiness|Fixed explicit source_repository=self.sources, same repository passed to extraction/acquisition|
|Normal build_research_readiness_service|Already injects Source into readiness and ResearchLoopService|
|ResearchReadinessService.evaluate_for_context|Checks dependency, shared qualification, then evaluator|
|Readiness terminal reconciliation|Same repository through _finalize_terminal_readiness|
|Budget fallback|Same repository through _missing_readiness_fallback|
|ResearchLoopService continuation / reassessment / terminal helpers|All four qualifying_evidence call sites already pass self._source_repository|
|ARK continuation assessment|DeskAdapter.execute assess → same injected readiness instance|
|Worker restart/resume|Reconstructs executor with repository dependencies and persisted execution pin; same wiring on both executions|
|Analysis / Report / Review|Shared qualification uses injected Source repository; Review uses its Report service repository|

No alternative lookup implementation or hidden global dependency introduced.
The low-level citation validator remains unchanged and fail-closed.

## Minimal correction and explicit missing-dependency semantics

Only two product files change: executor injection and readiness dependency guard.
Readiness uses the existing `SourceRepository` abstraction explicitly. Before
initial evaluation, final reconciliation and budget fallback, missing/non-callable
Source lookup raises `ReadinessSourceUnavailableError`, diagnostic
`readiness_source_repository_unavailable`. This propagates as an operational
error through the existing task/worker error path, not an ordinary research
insufficiency result. No false readiness payload is published by these paths.
Even empty Evidence cannot hide a missing validation dependency. Actual backend
lookup exceptions propagate rather than being converted to empty Evidence.
Repository present but Source absent/invalid remains a normal fail-closed citation
rejection; no invalid record is promoted to qualifying.

Fixture changes explicitly supply existing synthetic Source repositories (or an
empty repository in genuinely empty fixtures). They do not bypass validation or
weaken assertions. No changes to strategy, queries, extraction, temporal/relevance/
geography policy, lineage, thresholds, phase labels, retry or budget ceilings.

## Deterministic ARK-05-shape replay

New `test_ark06_readiness_sources` uses fictional water-meter content, not live
provider payloads: nine independently persisted synthetic Evidence with canonical
Source checksums/spans; five Q1 2026 observations, four temporally unresolved.
All nine citations structurally validate. Only IN1 is populated out of five INs.
Authoritative readiness evaluator receives exactly five qualifying Evidence.
Final reconciliation retains counts IN1=5, IN2–IN5=0 and ready_for_analysis=false.
Reassessment also receives five. No forced READY and no historical run replay.

Additional regressions cover missing dependency including empty input/final gate,
backend outage, invalid and missing Source, real executor injection and restart.
PostgreSQL regression verifies authoritative readiness reads persisted Source,
excludes a bad stored span and does not mutate Evidence. Existing real-adapter
6+2, continuation, telemetry on/off, retry, ledger/fencing tests remain intact.

## Validation (groups overlap; do not sum as unique tests)

- Initial ARK/citation/retry/controller/checkpoint group: 66 tests PASS.
- Research quality: 477 tests PASS, 5.608s. Initial run exposed 19 legacy
  missing-dependency fixture errors; corrected explicit fixture wiring. A second
  run exposed two remaining empty/optional fixture omissions, also corrected.
- New regression module final: 7 tests PASS, 0.239s.
- Final combined ARK02/04/06 and PRF08W group: 92 tests PASS, 11.917s.
- PostgreSQL/API/worker affected group: 31 tests PASS, zero skips, 36.670s.
  Modules under tests.integration.postgresql: test_ark04_citation_integrity,
  test_ark02_ledger, test_ark02_desk_worker, test_worker_execution,
  test_worker_api_claim_integration, test_durable_workflow_runtime,
  test_research_loop_progress_checkpoint_recovery, test_prf08s_funnel_telemetry,
  test_prf08k_lineage_identity.
- Final PostgreSQL citation/readiness + Desk worker group: 7 tests PASS,
  zero skips, 9.735s; includes newly added persisted-readiness assertion.
- Canonical `python run_tests.py` executed exactly ONCE: **3018 tests run,
  152 skipped, 0 failures/errors, 153.021s**. No second full run. Final targeted
  checks cover subsequent fixture/import cleanup and explicit type annotation.
- `git diff --check` passes. Logs stay private/ignored, not committed.

PostgreSQL tests used new internal-only network `ark06-readiness-test`, container
`ark06-readiness-test-postgres`, tmpfs database `ark06_test`, no host port or
historical volume. Production dependency image ai-research-os-ark05:95b5d3a with
current code/tests mounted read-only. No root .env/provider credentials passed.
Expected negative worker cases log exceptions while their test assertions pass.

### Additional pre-existing limitations, not hidden

Explicit execution-namespace test enumeration (outside canonical discovery)
ran 20 budget tests: 19 passed, one failed:
`DownstreamReserveWorkflowTests.test_workflow_proceeds_to_readiness_after_downstream_reserve`
in tests/application/execution/test_budget_exhaustion_acceptance.py.
It expects downstream analysis after its synthetic extraction setup; actual false.
The same test failed when both its test module and readiness module were loaded
from committed baseline HEAD into an isolated Python process. Other unchanged
dependencies were the current worktree; no claim of a second full baseline suite.
An initial comparator import attempt failed before executing the test and is not
counted as reproduction. No assertion or production workaround was added.

The previously established two-run Review integration failure remains the ARK-04
documented baseline limitation; not rerun, not reclassified as ARK-06. Neither
these limitations nor skipped integration tests are described as passing tests.

## Fresh historical integrity

Read-only transactions against original databases. Method: Evidence count and
`md5(string_agg(row_to_json(e)::text,chr(10) ORDER BY id))`; full workflow row
`md5(row_to_json(w)::text)`. All match ARK-05/ARK-04 recorded baselines.
No new qualification, sufficiency recomputation, migration, repair or write.

|History|Evidence|Evidence MD5|Workflow MD5|
|---|---:|---|---|
|B|13|076646d8ec25f2a7d682ec420896af95|00ef1aa66c3b6194ba39d1a01c066de7|
|D|33|84ce68280d94941b19414a46893f2868|01e242df696ac51050788442c6249471|
|F|22|7937d0745c8c03a67ffc045c9fbbb6f5|3eedf9afcfbd4b61b1eaa672bc36f3f8|
|H|24|3866b66b19d3ec31ff6210fafa297922|60fd6bb7a92d1c36f0bb04073d567e47|
|J|27|299e88abe27b9363fd623f5f9e034eac|2e66c4ab0dbf4365877c97e61e053576|
|O|1|135c9ec526cdd2672bd61b52e7902f7d|9dcb9c3b7526dd0eeb2a625876460c28|
|T|5|3c15be644e3a45f47955bc1da2bfd412|eab5db1fd4860e5011a91c6fefed1e53|
|V|21|7f9ca2da74d75c5bae0107a425108309|0efe638f7ce58baa6dc785d499f340ce|
|X|0|NULL|cc468d87e5efe063634cfbd4b75afd31|
|ARK03|16|e93284678aa04afd32cee577a1601093|b6dfb8368131bc7ab75d201dd8ae0917|
|ARK05|9|b561fd1f26f08a9086683686ff14bf41|25a78ae449ae0cccc04ef1a3af42ae6d|

## Closure

No known ARK-06 correctness blocker remains. Live corrected readiness, eventual
research sufficiency and downstream deliverables remain NOT VERIFIED. This fix
does not solve the four uncovered INs or retroactively accept ARK-05.
No provider calls or live run; no migration, deployment change, historical writes
or push. Reviewed deliverables are two product files, tests/fixture dependency
wiring and this record. No secrets, .env, runtime dumps or provider payloads.
One local commit authorized: `ARK-06 wire source repository into readiness`.

ARK-06_READY_FOR_LIVE_REVALIDATION
