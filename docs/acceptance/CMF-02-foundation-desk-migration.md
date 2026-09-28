# CMF-02 — Framework foundation and Desk migration

Opened: 2026-09-27. Final closure: 2026-09-28. Status: **READY_FOR_ACCEPTANCE**.
Baseline/current committed HEAD: `9941b93014aa0519907c4845f29083562b215b6b`.
Branch: `acceptance/live-desk-research-01`; ahead 36 / behind 0 against local
upstream tracking. No fetch, commit or push. Preserve the existing worktree on resume.
Authoritative architecture: `docs/architecture/CMF-01-canonical-method-framework.md`.

## Implemented slice (uncommitted)

- `application/methods/contracts.py`: frozen method identity with separately named
  contract/design/adapter/execution/integrity/sufficiency/analysis/review/report
  versions; capability record; generic MethodBinding protocol for design/need types,
  existing ARK adapter construction, typed stage delegation and report-source binding.
  Analysis/review policies in this first slice are existing canonical stage delegates,
  not duplicated analytical implementations or a new mutable result schema.
- `registry.py`: immutable explicit registrations, exact ID/version resolution,
  duplicate/unknown/incomplete registration rejection, support-kind/mode/format checks.
- `catalog.py`: Desk v1 is the sole production registration. No Quantitative method
  implementation, runtime discovery, plugins or fake production registration.
- `desk/binding.py`: delegates validation to validate_research_design, maps existing
  InformationNeed values unchanged, builds existing DeskAdapter, requires matching
  canonical Source dependencies in readiness/extraction, delegates existing stages
  and report source assembly. No copied thresholds or research strategies.
- `executor.py`: resolves the persisted version before delegating all six Desk stages.
- `versioning.py`: deterministic input/profile fingerprints and exact pinned bundle
  resolution; rejects incompatible identity, altered profile/design/brief and pin mismatch.

## Version envelope decision

Use the existing `_research_execution_v1` activation pin, adding nested `cmf` data.
The template research_kernel marker and run pin carry identical envelopes:

```
cmf:
  identity: method_id, version, name, contract_version, design_version,
            adapter_version, execution_version, integrity_version,
            sufficiency_version, analysis_version, review_version, report_version
  design_hash
  brief_hash
  profile_hash
```

Existing PostgreSQLWorkflowRunRepository.create copies the entire marker into JSONB
within activation. Existing checkpoint_results preserves the complete pin, refusing
replacement/deletion/injection by runtime checkpoint writes. No schema or kernel-store
change is needed for this shape. Offline preservation tests pass; real PostgreSQL
round-trip/worker verification is still pending and must not be inferred from inspection.
The existing digest provider computes hashes; no credentials are included in the envelope.

Report ID/source_version, review digest, renderer/template version and stored bytes remain
in existing deliverable records; they are not replaced by the method version.

## Routing and rollout

New activation is explicitly opt-in: `CMF_DESK_ENABLED=1`, with ARK enabled and the
existing required PostgreSQL backend. Defaults remain off. Invalid combinations fail
at composition. ResearchDesignWorkflowMapper validates through registered Desk binding
and attaches the envelope only to new opted-in templates.

Composition wraps search/evidence/readiness/analysis/report/review executors. Historical
runs without CMF envelope delegate unchanged. Workers continue resolving already-pinned
CMF runs even if the activation flag is subsequently disabled. No latest-version lookup.
VersionedDeskExecutor constructs the same canonical primitives/readiness/controller,
with CMF selecting the Desk adapter only when an envelope is present.

ProjectDeliverablesService resolves a CMF-pinned run's report-source provider before
calling the existing Desk source assembly. Legacy Desk and Quantitative routes remain
compatible; Quantitative is not migrated. Report sorting, status, exact source revision,
PDF/PPTX storage and download authorization are unchanged.

## Integrity and downstream behavior

No changes to `application/research_kernel/`, ledger, dispatch, fencing, kernel ownership,
qualification/citation/temporal/relevance/geography/lineage policies, ARK budgets or
telemetry. No auth/activity/review/report/PDF/PPTX renderer redesign.

Existing AnalysisService continues loading persisted run-scoped Evidence, applying
canonical qualification and emitting separate Findings and Insights. The nonempty CMF
replay verifies five qualifying inputs from nine persisted synthetic rows, unchanged
Evidence before/after analysis and Insight references to persisted Findings. CMF does
not add a separate analysis store or silently mutate Evidence.

Desk operational review order remains draft Report -> exact revision Review. Existing
draft exports stay draft; no claim that an exportable draft is accepted. API/UI regression
contracts also run through CMF source routing, covering review-after-draft, historical
downloads, immutable checksums, source identity and owner authorization.

## Contract harness / equivalence

`tests/application/test_cmf02.py` includes reusable RegistryContract tests, used by
Desk and a test-only independent FakeMethod. Fake stage dispatch resolves through the
same registry without modifying registry/controller code. Tests cover exact identity,
duplicate/unknown versions, pinned template, design validation, needs, missing/changed
pin/input/profile, checkpoint preservation and required Source wiring.

Real VersionedDeskExecutor replay compares pre-CMF and CMF paths with offline provider
ports: six initial valid-empty extractions, two bounded continuation calls, zero Evidence,
same used resources and safe insufficient refusal. CMF telemetry off/on gives identical
canonical decisions/state. No byte identity requirement for incidental IDs/timestamps.
Intentional difference: new template/run marker contains the CMF envelope.

`test_cmf02_boundaries.py` covers nonempty readiness equality, unresolvable citations
excluded from qualification, persisted analysis inputs, no Evidence mutation and
Finding/Insight support separation. `tests/api/ui/test_cmf02_deliverables.py` inherits
the established document/review/authorization contracts with a synthetic CMF pin.

`tests/integration/postgresql/test_cmf02_worker.py` reuses the existing API/worker/ledger
contracts with CMF activation, including restart with activation disabled, legacy runs,
ambiguous provider recovery, bounded retry and protected pin writes. These tests exist
but their live-database execution did NOT complete in this continuation.

## Actual tests and chronology

1. Initial targeted group: 47 tests, one fixture error (missing source/analysis/deliverable
   plans in a reused low-level ARK fixture). Corrected only the new CMF test fixture;
   product validation was not weakened.
2. CMF plus existing document group: 29 tests PASS, 3.192s.
3. Combined CMF, ARK02/04/06, analysis/review/report and document API group:
   **121 tests PASS, 42.355s**, zero failures/errors/skips reported.
4. Expanded CMF group initially exposed a test-only missing fake executor delegate.
   Supplied the normal callable delegate; no production workaround.
5. Final focused command:
   `python -m unittest tests.application.test_cmf02 tests.application.test_cmf02_boundaries tests.api.ui.test_cmf02_deliverables -q`
   **32 tests PASS, 1.929s**. Includes fake dispatch and telemetry parity additions.
6. Canonical full `python run_tests.py` executed **exactly once**:
   **3059 run, 2905 passed, 153 skipped, 1 failure, 0 errors; 241.426s**.
   Private ignored log: `.env.cmf02-runtime/full-offline.log`.

The sole full-suite failure is
`StructuredOutputArchitectureTests.test_p_json_loads_only_in_validator` in
`tests/application/structured_output/test_structured_output_layer.py`.
It reports exactly `.env.ark07-runtime/infra02_observe.py` and
`tools/acceptance_health.py` as json.loads users. Neither file is changed by CMF-02.
`git show HEAD:tools/acceptance_health.py` confirms the offending call is in the committed
baseline; the ignored observer already existed. Direct rerun reproduces the same failure.
No test exclusion, rule weakening, unrelated INFRA fix, or historical runtime-file edit.
This is an existing regression-gate conflict, not a demonstrated CMF failure. The suite
is nevertheless NOT green. No second full run was performed.

## PostgreSQL / API / worker infrastructure gate

Created only new disposable test infrastructure:

- internal network `cmf02-test` and `cmf02-test-postgres`, tmpfs storage;
- fallback `cmf02-local-test-postgres`, tmpfs storage, host loopback `127.0.0.1:18439`;
- synthetic role/database `cmf_test` / `cmf02_test`, no provider credentials,
  no historical volumes, no production connection or root .env reuse.

The first container test launch failed before testing with Docker HTTP 500. Docker
subsequently responded, but the second launch failed importing `/app/domain/legacy`
with `OSError: [Errno 12] Cannot allocate memory` through the read-only source mount.
No test execution count is inferred from these attempts.

Fallback local Python used only the loopback disposable database with test safety flags.
The affected group was CMF worker, ARK ledger/worker/citation, PRF05A activation and
worker API claim modules. Existing migrations through 016 were logged in the disposable
database, but the group stalled without a terminal summary. A separate read-only
connection with five-second connect timeout failed with ConnectionTimeout. The test
process was interrupted; **PG/API-worker group NOT VERIFIED**, not passed/skipped.
No migration was added or applied to a historical database.

A single cleanup attempt to stop only the two newly created CMF test PostgreSQL
containers exceeded 25 seconds. Their final stopped/running state is UNVERIFIED;
they may remain allocated. No further lifecycle commands or Docker restart were
attempted. The existing acceptance services were never selected for stop/removal.

## Fresh historical gate

Prepared the established READ ONLY SQL: Evidence count and ordered
`md5(string_agg(row_to_json(e)::text,chr(10) ORDER BY e.id))`, plus
`md5(row_to_json(w)::text)` for each workflow. Expected values are the ARK-07 record's
B/D/F/H/J/O/T/V/X/ARK03/ARK05 table, plus ARK07 Evidence7,
`d4b8d9ca51f0dad3dca7c539498973b9` / `b0906e3a442a040ce0865ffd08682e99`.

The first historical query, B via `ai_research_os_prf08b-postgres-1`, exceeded the bounded
35-second Docker exec timeout. The sequence stopped safely. Therefore **none of the 12
fresh comparisons is certified**; the other 11 were not queried by this attempt.
No outcome recomputation, repair, migration, reseed, provider call or historical mutation.
Prior checksums remain reference evidence only, not a substitute for this required gate.

## Completion blockers and resume scope

Do not commit this work yet. Preserve the implementation and targeted evidence.
Remaining: restore stable access to the disposable test database without touching
historical services; complete affected PG/API/worker tests; complete all 12 historical
READ ONLY comparisons; resolve/classify the existing non-CMF architecture conflict with
owner direction as necessary. Do not rerun the full suite just for repetition.
No live acceptance is required or authorized by CMF-02.

No OpenAI/Tavily calls, live research, Quantitative implementation or push. Existing
untracked historical artifacts and root .env remain untouched. Index remains unstaged;
only intended CMF code/tests/this record are new or modified. Final commit is withheld
until mandatory acceptance gates are actually met.

Final static checks: `git diff --check` PASS; CMF files secret-pattern scan zero hits;
no staged files; HEAD unchanged, ahead 36 / behind 0. New test/runtime files remain
local and the runtime log directory is ignored. No acceptance-evidence commit exists.

## Offline gate conflict closure — owner-authorized narrow continuation

Classification: **B — pre-existing INFRA-02 violation of the established parsing
boundary, not a CMF-02 regression**. The exact failing assertion scans Python sources
for direct JSON decoding outside JsonValidator and the explicit deterministic planner
exception. The assertion and its allowed/excluded paths were not changed.

Offenders were `tools/acceptance_health.py` (committed in `21d475a`, INFRA-02) and
the existing ignored `.env.ark07-runtime/infra02_observe.py`. Both used direct decoding
of Docker inspection output. The already accepted `tools/acceptance_http.py` demonstrates
the canonical infrastructure parsing convention: JsonValidator. No evidence justified
exempting Docker helpers from the existing rule.

Remediation: health CLI now calls parse_worker_state, which delegates syntax parsing to
JsonValidator and requires an object; invalid syntax/root type produces a generic safe
ValueError caught as EXECUTION FAILURE. Added repository-root import bootstrapping for
direct-script invocation, following acceptance_http. The ignored observer now uses the
same validator and checks for a nonempty list before selecting its inspected container.
Only that helper's parsing code was updated; the observer was NOT executed and prior
observations/reports/database outcomes were not changed. It remains ignored/untracked.

INFRA classification logic itself is unchanged: HEALTHY, APPLICATION FAILURE,
HEALTHCHECK TIMEOUT, CONTAINER NOT RUNNING and EXECUTION FAILURE retain their meanings.
The committed worker timeout override remains 15s; Docker inspect's existing 30s host
timeout is unchanged. Raw invalid input and arbitrary probe output are not disclosed.

Targeted commands and actual results:

- `python -m unittest tests.application.structured_output.test_structured_output_layer.StructuredOutputArchitectureTests tests.test_acceptance_health -q`
  — **16 PASS**, 66.044s, no failures/errors/skips.
- `python -m unittest tests.application.structured_output.test_structured_output_layer tests.test_acceptance_health tests.application.test_dependency_boundaries -q`
  — **52 PASS**, 53.694s, no failures/errors/skips. Includes the previously failing
  rule, canonical syntax validator cases, all health categories, slow-success/timeout
  regression, parser delegation, malformed/non-object input and mocked CLI redaction.
- `git diff --check` PASS; no timeout-config diff. Architecture rule unchanged.

No CMF production/test code was changed by this continuation. These helpers are not
called by CMF runtime, so the accepted CMF targeted evidence was reused. No full suite,
Docker command, PostgreSQL/worker integration, provider call or live run was executed.
The CLI regression mocks subprocess.run; it does not invoke Docker.

Historical full-suite fact remains **3059 total / 2905 passed / 153 skipped /
1 failure / 0 errors**. That run is not relabelled green. Only its specific offline
conflict is now closed by targeted verification. PG/worker and fresh historical DB gates
remain pending; CMF-02 overall is not yet accepted. Existing CMF changes are preserved,
index remains unstaged, no commit/push; committed HEAD remains
`9941b93014aa0519907c4845f29083562b215b6b`.

## Final integration and closure — 2026-09-28

The prior Docker/worker interruptions remain part of this record. Docker Engine was
responsive at recovery. `ai_research_os_ark07-postgres-1` and API were healthy;
API `/ready` returned HTTP 200. Worker had been left exited with code 255 after
Docker restart (`restart: no`, restarts 0, OOM false). Only the existing
`ai_research_os_ark07-worker-1` was started; API/PostgreSQL were not restarted.
Its configured automatic healthcheck timeout was 15s. Six distinct new automatic
health probes passed with exit=0 over 62.2s, worker Running, restarts 0, OOM false.
PostgreSQL/API remained healthy with restarts 0/OOM false; Docker responded after
the window. No HTTP 500, DNS error, no-route-to-host, health timeout or restart loop
was observed in this recovery window. Historical infrastructure incidents are not erased.

The required affected integration command was:

`python -m unittest tests.integration.postgresql.test_cmf02_worker
tests.integration.postgresql.test_ark02_ledger
tests.integration.postgresql.test_ark02_desk_worker
tests.integration.postgresql.test_ark04_citation_integrity
tests.integration.postgresql.test_prf_05a_activation_transactions
tests.integration.postgresql.test_worker_api_claim_integration -v`

Result: **41 run, 41 passed, 0 failed, 0 errors, 0 skipped; 62.271s**. It used
only disposable `cmf02_test` via loopback `127.0.0.1:18439`, with integration and
disposable-database guards enabled. Its helper applied established migrations
through 016 only to this test database; no new migration or historical migration.
Tests covered CMF method/version pin persistence, API activation, separate worker,
restart with activation disabled, no legacy promotion, checkpoint protection, 6+2,
structured retry accounting, stale revision/CAS/lease fencing, no double dispatch,
Source/citation integrity, activation transactions and worker API claim. The prior
offline CMF readiness, telemetry and Desk equivalence tests remain valid. All provider
ports were synthetic/offline; no real OpenAI or Tavily call occurred. No new functional
regression was demonstrated.

### Fresh historical integrity

Twelve original isolated PostgreSQL environments were queried using `BEGIN READ ONLY`
with a 15s statement timeout. For each one exactly one workflow row matched the
established Evidence count, ordered Evidence `row_to_json` MD5 and full workflow-row
`row_to_json` MD5 in `docs/acceptance/ARK-07-final-live-acceptance.md`.

| Environment | Evidence rows | Count and both checksums |
| --- | ---: | --- |
| PRF-08B | 13 | MATCH |
| PRF-08D | 33 | MATCH |
| PRF-08F | 22 | MATCH |
| PRF-08H | 24 | MATCH |
| PRF-08J | 27 | MATCH |
| PRF-08O | 1 | MATCH |
| PRF-08T | 5 | MATCH |
| PRF-08V | 21 | MATCH |
| PRF-08X | 0 (Evidence MD5 NULL) | MATCH |
| ARK-03 | 16 | MATCH |
| ARK-05 | 9 | MATCH |
| ARK-07 | 7 | MATCH |

**12/12 verified**, no historical mutation, outcome recomputation or live rerun.

### Disposable resources

Read-only inspection established that only `cmf02-local-test-postgres` was running;
`cmf02-test-postgres` was exited. Both exact containers were created by this CMF-02
work, held only synthetic tmpfs test data, had no mounts/named volumes; private
network `cmf02-test` had no other containers. The local test container was stopped;
both were removed, then the empty CMF network removed. Final Docker container and
network listings showed no CMF disposable resources. This deletion removes only
recoverable-by-recreation synthetic test data; no historical acceptance volume or
artifact was selected.

### Final evidence and limits

The historical single full suite remains exactly **3059 total / 2905 passed /
153 skipped / 1 failure / 0 errors**. Its sole failure was later root-caused to
direct JSON parsing in pre-existing INFRA helpers and closed with JsonValidator;
post-fix targeted groups passed 16/16 and 52/52. It is NOT retroactively called
green. The full suite was not rerun, as authorized for closure. CMF targeted groups
remain 121/121 and final 32/32 PASS. All required PostgreSQL/API/worker and fresh
historical integrity gates now pass.

CMF remains opt-in for new Desk runs; Quantitative is not onboarded. No CMF live
research, new feature, product budget change, provider call or push. Prior Docker
instability is retained as operational history; no current correctness blocker was
observed. This acceptance record claims local closure only, not remote CI.
