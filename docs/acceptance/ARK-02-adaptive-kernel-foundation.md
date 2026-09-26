# ARK-02 — Adaptive research kernel foundation

Status: **READY FOR CONTROLLED LIVE VALIDATION**, not live research acceptance.

Baseline: `acceptance/live-desk-research-01`,
`152995f3e7c36894fe5cfe346d58159b45566e14`, ahead 28 / behind 0 against
its local upstream reference. Existing uncommitted work was continued, not reset.
ARK-01 remains authoritative. This phase was entirely offline: no OpenAI/Tavily
requests, paid execution, historical rerun, or push.

## Completed delta

### Production attempt accounting

The single-flight controller reserves and commits an action before dispatch.
`dispatch.py` durably records each actual child attempt with logical action ID,
ordinal, provider/operation, cumulative reservation snapshot, retry flag and
`ambiguous` / `failed` / `returned` outcome. No prompt, response body, credential
or exception payload belongs to this ledger. Attempt outcome is distinct from
validated method outcome and does not imply sufficient research.

For ARK only, the OpenAI transport runs with SDK retries disabled and exposes
bounded retries explicitly using the configured SDK retry ceiling and retryable
HTTP statuses/header. Every such attempt consumes the same pending action's
operation, stage, partition, total LLM and retry dimensions. The existing single
structured-extraction recovery retry uses that same ledger. The old SDK path is
unchanged outside an ARK dispatch. Search is metered at the actual provider port;
retrieval is metered at the actual retrieval port, not merely at a surrounding
service which could catch its exception. Native HTTP timeout/body/redirect/SSRF
limits remain in the existing primitive.

An OpenAI timeout/connection failure cannot prove non-dispatch: it marks the
attempt ambiguous and stops, including when extraction catches its exception.
An uncertain search failure is also conservatively stopped. Neither a worker
retry nor a new worker ID obtains a new envelope. Failed or ambiguous exposure is
not refunded. Retry capacity may make fewer logical extractions possible; it does
not create extra calls beyond the eight-call reference envelope.

### Real Desk adapter

`application/methods/desk/` translates frozen Desk state into generic gaps,
finite actions, resource vectors, outcomes and stops. It uses the existing query
builder/retrieval arms, source selection/acquisition/provenance, content dedup,
chunk queue and adaptive depth ranking, extractor/grounding/relevance validation,
`qualifying_evidence`, readiness evaluation and terminal reconciliation.
No parallel legacy `ResearchLoopService` runs inside ARK.

The kernel stores IDs and bounded decisions. The method progress checkpoint
holds bounded, selected canonical candidate DTOs needed for restart, safe counters,
source-outcome state and canonical readiness references. It is not a raw provider
response dump. Provider exception text and extraction response previews are not
copied into the new durable diagnostics. Credential-bearing candidate URLs are
rejected rather than rewritten and fetched.

Novelty keys use immutable need/retrieval-arm/scope or canonical source-content,
need and original chunk offsets. Rewording a query or a URL alias does not buy a
fresh identical strategy. Before search, the adapter checks that a complete
fetch/extraction path still fits scoped capacities; single-flight ownership
prevents concurrent consumption. Each actual step is separately reserved before
its operation. This is staged reservation, not a claim of an atomic multi-action
path transaction. Finite candidate/decision bounds also cap control-only work.

The initial versus continuation fetch scopes are retained; the existing
`source_max_sources_per_run` is an initial-acquisition cap, not an invented whole-
scenario fetch cap. A persisted deadline is not renewed by restart. Expiry is a
safety stop, not substantive research insufficiency.

Integration verification exposed and corrected three concrete issues before the
full suite: the workflow needed the restored budget rebound for downstream tasks;
a zero-Evidence-only readiness fallback could not handle the first real fact;
and aggregate extraction failures include grounding rejection, not only invalid
provider output. The adapter now uses canonical stale-assessment reconciliation,
keeps the downstream guard at durable attempted exposure, and distinguishes
rejected, duplicate, invalid and schema-valid-empty outcomes. Existing integrity
rules and qualification thresholds were not changed.

### Principal real-Desk X replay

Actual production Desk primitives, extractor/parser, canonical repositories,
qualification and readiness services run against deterministic provider ports:

`6 initial valid-empty extractions -> 0 Evidence -> reassess -> reserve ->`
`continuation 7 -> outcome -> reassess -> continuation 8 -> safe refusal`.

Assertions verify 6 initial + 2 continuation, total 8, zero fabricated Evidence,
non-ready `insufficient_research`, and downstream gating. The same path executes
through a separately constructed worker with real PostgreSQL persistence.

Additional real-adapter cases cover readiness at extraction 7, cross-only yield
at 7 followed by another permitted opportunity at 8, useful Evidence without
assessment capacity, rejected unrelated/ungrounded output, no feasible acquisition
path, deadline expiry, and telemetry on/off equality. The cross-only fixture
explicitly permits two attempts for its remaining target; a per-gap ceiling of
one must not be bypassed merely because a global slot remains.

This is a deterministic replay of the historical failure pattern, not a replay
of paid payloads and not proof that historical X would have become sufficient.

### Versioned opt-in rollout

`ARK_DESK_ENABLED` defaults to false and requires PostgreSQL for new activation.
New eligible templates receive an immutable version-1 non-secret configuration
profile; run creation persists `_research_execution_v1`. Worker recovery loads
that pin, not the current activation flag. Existing executor IDs remain the same.
Unmarked old runs delegate to their original executors and cannot acquire ARK
semantics simply because a worker enables the flag.

Mismatch/unsupported version fails closed. General checkpoints cannot install,
replace or erase the execution pin or kernel-owned ledger/fence slots. Already
pinned runs remain supported when activation is disabled for new runs. The
worker verifies pinned LLM model/output configuration before proceeding.

## Bounds and exact recovery guarantee

Reference profile: **6 initial + 2 continuation = 8 actual extraction attempts**,
including bounded transport/structured retries. Per-gap and per-attempt ceilings
remain additional constraints. Assessment, total LLM and initial-stage downstream
reserves are separate dimensions; no hidden retry can escape those ledger limits.
Legacy stage counters are guards hydrated from durable exposure, not fresh budgets.
Search opportunities are finite approved arms; no free query-rewording loop or
unbounded search-until-success mechanism is introduced. No budget was increased.

PostgreSQL stores the ledger in reserved versioned JSONB slots; **no migration**.
Independent transactions, a refreshed row lock, database-clock lease validation,
revision CAS, execution-incarnation token and a one-use dispatch receipt fence
stale workers. A two-second row-lock timeout fails closed rather than permitting
unreserved execution. General workflow checkpoints preserve these owned slots.

**Not exactly once:** provider execution and database commit are not a distributed
transaction. A process can die after durable authorization but before dispatch,
or after remote execution/canonical persistence but before outcome completion.
An already-authorized stale operation can finish after lease takeover. Its old
writer cannot commit another ledger outcome. The new owner retains the complete
pending reservation and stops for reconciliation instead of replaying it.
Canonical Evidence persistence and kernel completion are not claimed atomic.
Where no idempotent provider lookup proves the result, availability is sacrificed:
no automatic replay, refund, manual result rescue, or fabricated completion.

The guarantee is bounded pre-authorized attempts, durable conservative exposure,
at-most-once automatic dispatch per attempt ordinal, and ambiguous-call fencing;
explicit permitted HTTP/structured retries have distinct ordinals. Successful
committed outcomes resume without double debit. These guarantees do not imply
exactly-once billing or remote cancellation.

## Validation evidence

Final targeted command (before canonical suite):

```text
python -m unittest tests.application.test_ark02_desk_integrity tests.application.test_ark02_desk tests.application.test_ark02_retry tests.application.test_ark02_kernel tests.application.test_ark02_checkpoint tests.application.test_dependency_boundaries tests.application.test_architecture_remediation tests.application.test_composition_root tests.application.execution.test_execution_budget_wiring tests.application.test_prf08w_temporal_relevance tests.application.test_prf08s_funnel_telemetry tests.application.research_quality.test_prf08i_evidence_aware_continuation tests.application.research_quality.test_prf08k_target_fidelity -q
```

**148 passed, 0 failures/errors, 0 skipped.** Includes 49 focused ARK tests;
real SDK tests use only in-process `httpx.MockTransport` and a synthetic key.

Final affected PostgreSQL command:

```text
python -m unittest tests.integration.postgresql.test_ark02_ledger tests.integration.postgresql.test_ark02_desk_worker tests.integration.postgresql.test_worker_execution tests.integration.postgresql.test_worker_api_claim_integration tests.integration.postgresql.test_durable_workflow_runtime tests.integration.postgresql.test_research_loop_progress_checkpoint_recovery tests.integration.postgresql.test_prf08s_funnel_telemetry tests.integration.postgresql.test_prf08k_lineage_identity -q
```

**30 passed, 0 failures/errors, 0 skipped**: 13 ledger/fencing, 6 new real Desk
API/worker/version/retry cases, and 11 affected existing integration cases.
Injected crashed-provider reconciliation and legacy empty-extraction failures
produce expected negative-case worker logs; neither is a failed test.

Isolation: internal network `ark02-ledger-test`, tmpfs PostgreSQL container
`ark02-ledger-test-postgres`, database/user `ark02_test`, no published DB port,
no historical volume, explicit disposable-test flags. Image
`ai-research-os-prf08x:5508fb1` supplied Python 3.11 dependencies; the current
application, infrastructure and tests were mounted read-only. This is not a claim
of a newly built production image. Only task-created test infrastructure is
eligible for cleanup; all historical containers remain untouched. After successful
validation, that exact task-created container and network were removed. Only their
reproducible tmpfs test data was discarded, not any historical volume.

### One canonical full offline run and focused correction

`python run_tests.py` was executed **exactly once**:

```text
Ran 3000 tests in 131.219s
FAILED (failures=4, skipped=151)
```

There were **0 errors**. Preserve that result; do not describe it as a green full
run. Skips include explicit PostgreSQL/service gates, private opt-in benchmarks
and the unavailable configured PDF font. The raw unittest skip total includes
class-level skips; it is not a passed-test count. Relevant PostgreSQL gates above
were actually executed separately, not counted as passed skips.

All four failures were in `tests.application.test_ark02_retry.RetryTests`:

- `test_ambiguous_timeout_is_never_retried_even_if_extractor_swallows`
- `test_existing_sdk_retry_ceiling_not_increased`
- `test_retry_cannot_exceed_shared_capacity`
- `test_sdk_retry_has_precommitted_attempt_reservation_and_safe_terminal_outcome`

Root cause was new test-fixture import lifetime, not relaxed retry semantics.
The existing `AgencyFacadeTests.test_agency_import_does_not_require_openai_module`
removes all `openai` modules from `sys.modules`. A discovery-time imported
`OpenAI` class then belonged to the old SDK exception hierarchy while the tested
transport imported current exception types. The 11-test agency+retry reproduction
produced exactly those four failures. Moving the fixture's SDK import into client
construction fixes the stale type identity; assertions and production code remain
unchanged. The direct executor fixture also scopes its budget context so it cannot
leak into later tests.

Post-correction command: the 148-test command above with
`tests.agency.test_agency_facade` prepended. **153 passed, 0 failures/errors,
0 skipped (22.746s)**. This includes the exact failing interaction and all affected
ARK/integrity/architecture tests. No product code changed after the full run;
the PostgreSQL results therefore remain applicable. The full suite was not rerun,
as requested. Compilation and `git diff --check` passed.

Earlier continuation checkpoints (28 core, 66 core/runtime/architecture, 21 PG)
remain development chronology, superseded by these expanded final gates. An
initial JSON tuple/list mismatch, the new telemetry fixture's method-wrapper
signature, and the per-gap cross fixture setup were resolved with focused tests;
no canonical assertions or historical outcomes were weakened to obtain green.

## Fresh historical read-only verification

All original containers were accessible. Fresh checks after the final product
changes used `BEGIN READ ONLY` and the canonical PRF-08X method:

```sql
SELECT count(*), md5(string_agg(row_to_json(e)::text, chr(10) ORDER BY id))
FROM evidence e WHERE workflow_run_id = '<historical run ID>';
SELECT status, md5(row_to_json(w)::text)
FROM workflow_runs w WHERE id = '<historical run ID>';
```

| History | Evidence | Evidence MD5 | Workflow row MD5 |
| --- | ---: | --- | --- |
| B | 13 | 076646d8ec25f2a7d682ec420896af95 | 00ef1aa66c3b6194ba39d1a01c066de7 |
| D | 33 | 84ce68280d94941b19414a46893f2868 | 01e242df696ac51050788442c6249471 |
| F | 22 | 7937d0745c8c03a67ffc045c9fbbb6f5 | 3eedf9afcfbd4b61b1eaa672bc36f3f8 |
| H | 24 | 3866b66b19d3ec31ff6210fafa297922 | 60fd6bb7a92d1c36f0bb04073d567e47 |
| J | 27 | 299e88abe27b9363fd623f5f9e034eac | 2e66c4ab0dbf4365877c97e61e053576 |
| O | 1 | 135c9ec526cdd2672bd61b52e7902f7d | 9dcb9c3b7526dd0eeb2a625876460c28 |
| T | 5 | 3c15be644e3a45f47955bc1da2bfd412 | eab5db1fd4860e5011a91c6fefed1e53 |
| V | 21 | 7f9ca2da74d75c5bae0107a425108309 | 0efe638f7ce58baa6dc785d499f340ce |
| X | 0 | NULL (empty aggregate) | cc468d87e5efe063634cfbd4b75afd31 |

Every value matched. B/D/F/H/J/O/T/V remain `completed`; X remains `failed`.
O resides in the PRF-08L container (the verification output labels that container
L). No history was recomputed, migrated, reseeded, restarted or repaired.

## Live limitations and delivery

Live provider effectiveness, latency, actual token/currency usage, API-provider
availability and full downstream live deliverables remain **NOT VERIFIED**.
Missing provider usage/cost is UNKNOWN, not a reported zero-price live run.
No new billing subsystem or provider monetary cutoff is claimed. A later authorized
live gate must freeze and inspect its actual profile, remaining scenario allowance
including design spend, telemetry, credentials and operational cost envelope.
Default ARK activation remains disabled; this task did not start a live run.

Only intended kernel/Desk integration, provider guard, persistence ownership,
focused tests and this acceptance record belong in the one local commit:
`ARK-02 implement adaptive research kernel foundation`.
No production data, root `.env`, credentials, paid-provider payloads, generated
reports, unrelated acceptance artifacts or historical records are part of it.
No schema migration. No push. The existing untracked artifacts are preserved.

ARK-02_READY_FOR_LIVE_VALIDATION
