# PRF-08S — Safe research funnel telemetry

## Baseline and scope

Branch `acceptance/live-desk-research-01`, initial HEAD
`5c77191b1397ead7d5b94bee9fc8feea0bfe9ea4`; tracked/index initially clean,
21 ahead / 0 behind the recorded upstream. Existing untracked acceptance/runtime
artifacts are excluded from this change. No OpenAI, Tavily, live research or push.

PRF-08R identified missing observations, not a proven new selection defect.
This change adds observations only: no ranking, query generation, extraction
capacity, retry policy, qualification threshold or continuation changes.

## Model and correlation

`application/research_funnel_telemetry.py` adds a versioned bounded journal in
`WorkflowContext.shared_state.research_funnel_v1`. Existing task-result JSONB
checkpoints persist and restore it; no schema change or migration. Failed tasks
with a journal also retain the existing task-result snapshot. Legacy snapshots
without this key remain valid; historical telemetry is not backfilled.

The journal is enabled by default. Setting execution metadata
`research_funnel_enabled=False` disables observation for comparison. Context-local
bindings isolate services/runs. Observer errors are counted without replacing the
research result or exception. Maximum retained events: 4096; maximum text field:
2048 characters. Dropped events are counted, not silently claimed complete.

Correlation chain:

`run_id + monotonic event sequence -> search event/call ordinal -> candidate
ordinal/ID -> canonical URL SHA256 -> acquisition event + source ID -> extraction
event/ordinal + source/content SHA256 -> Evidence ID -> supported-IN qualification`.

Each search stores the actual provider query projection, target RQ/IN, retrieval
arm and query hash. Sanitized/truncated queries explicitly have `query_exact=false`.
Returned URLs remain visible even outside the candidate limit. Candidate IDs are
search-local: repeated URLs have separate discovery identities but join the same
canonical source. Candidate decisions link acquisition IDs; failures retain
candidate IDs and an attempted flag, including retriever exceptions.

Extraction events distinguish initial/continuation, target IN, scope, source,
content fingerprint, chunk, valid-empty/invalid-output/failure/success, persisted
Evidence counts, target counts and cross-IN counts. Cross-only means target absent;
cross-IN includes multi-IN Evidence. Produced Evidence events include IDs/refs and
dedup-hit, never statements. Retry ordinals use retained structured-attempt counts;
intermediate outcomes not retained by the existing extractor are explicitly unknown.

## Decisions and qualification semantics

Candidate reasons include selected, duplicate URL/content, candidate limit,
unsupported/invalid URL, already exhausted, ineligible, lower-priority coverage
completion, acquisition-budget unavailable, existing selection rule and interrupted
stage. Existing selection reason codes are retained safely alongside these categories.
Extraction queue removals expose duplicate content; unused work exposes budget
exhaustion or interruption. No usefulness score is inferred from a URL.

Per-Evidence qualification observes the existing canonical temporal filter:
applicable-satisfied/failed, not-applicable, unknown/incomplete period, no exact
cutoff and the existing unknown-need passthrough. It does not invent per-Evidence
geography or lineage rejection where the product has no such filter. Existing
grounding/provenance rejection enums remain extraction outcomes. Need-level
sufficiency records actual status, Evidence count and independent-source count.
Temporal eligibility is not represented as proof of full methodological sufficiency.

## Data minimization

Only explicit field allowlists enter the journal. No snippets, page bodies,
Evidence text, raw provider/LLM output, hidden prompts or arbitrary error strings.
Known credential formats, credential assignments and secret-valued environment
matches are redacted; unrelated environment values are not copied. URLs lose
userinfo/fragments and sensitive query values. Source/canonical hashes preserve
joins even when display text is redacted. Tests use synthetic secret markers only.
Existing canonical data/diagnostics are not rewritten or duplicated into this journal.

## Deterministic proof and validation

The PRF-08O-shaped fixture returns five URLs across three IN queries, including
an alias, unused candidate, multiple empty extractions and one qualifying cross-IN
Evidence. On/off compares selection summaries (excluding elapsed time), exact
fetch calls, extraction scheduling/scopes and full sufficiency output. Identical
decisions and conservative refusal; unrelated Evidence never counts as target repair.
The deliberately capped journal also leaves sufficiency unchanged.

Targeted commands/results:

- `python -m unittest tests.application.test_prf08s_funnel_telemetry`: 14 passed.
- PRF-08P content identity plus PRF-08K target fidelity: 27 passed.
- `python -m unittest discover -s tests/application/sources -p 'test_*.py'`:
  210 run, 208 passed, 2 skipped.
- Corresponding evidence discovery: 153 passed; research_quality: 477 passed;
  runtime: 37 passed.
- Disposable PostgreSQL/API-worker selection: 20 existing tests passed;
  two new JSONB/failed-task tests passed after correcting a test-only call to
  `on_task_finished` (the initial combined 22-test attempt had 21 passes/1 error
  from calling nonexistent `on_task_completed`). No product defect was masked.
- Canonical `python run_tests.py`, executed exactly once: 2907 tests in
  134.669 seconds; 2758 passed, 149 skipped, zero failures/errors. Integration
  skips are not counted as passes; affected PostgreSQL paths ran separately above.

The affected integration selection covers PRF-08S JSONB restore/failure, PRF-08P
content aliases, PRF-08K lineage, PRF-08C integrity, provenance concurrency,
research-loop progress recovery, worker execution/API claim, worker service and
loop failure isolation/defaults. Current source directories were mounted read-only
into the existing production-compatible runtime image. PostgreSQL 16 used a new
internal test-only network and tmpfs database `prf08s_test`, never historical storage.
Integration flags were explicitly enabled; passed tests were not skipped.

## Fresh historical integrity

Read-only transactions on the original containers compared Evidence row counts,
ordered `row_to_json` MD5 aggregates and workflow-row MD5 with prior records.
No evaluator, research recomputation, migration or data repair was executed.

| History | Evidence | Evidence MD5 | Workflow MD5 |
| --- | ---: | --- | --- |
| PRF-08B | 13 | 076646d8ec25f2a7d682ec420896af95 | 00ef1aa66c3b6194ba39d1a01c066de7 |
| PRF-08D | 33 | 84ce68280d94941b19414a46893f2868 | 01e242df696ac51050788442c6249471 |
| PRF-08F | 22 | 7937d0745c8c03a67ffc045c9fbbb6f5 | 3eedf9afcfbd4b61b1eaa672bc36f3f8 |
| PRF-08H | 24 | 3866b66b19d3ec31ff6210fafa297922 | 60fd6bb7a92d1c36f0bb04073d567e47 |
| PRF-08J | 27 | 299e88abe27b9363fd623f5f9e034eac | 2e66c4ab0dbf4365877c97e61e053576 |
| PRF-08O | 1 | 135c9ec526cdd2672bd61b52e7902f7d | 9dcb9c3b7526dd0eeb2a625876460c28 |

All six match and remain completed. PRF-08O resides in the original PRF-08L
database; PRF-08L's stopped attempt is not reinterpreted. PRF-08O's missing
historical funnel observations remain missing, not inferred or fabricated.

## Next live questions and limitations

The next separately authorized run can identify returned vs absent URLs, each
bounded selection reason, failed acquisition vs duplicate content, empty vs invalid
extraction, actual target vs cross-IN yield, temporal rejection and remaining
need-level sufficiency. This does not prove that an unselected URL was useful:
that requires source inspection, not a speculative telemetry score. Live provider
behavior and next-run research sufficiency remain NOT VERIFIED.

Crash before an existing checkpoint may lose in-memory events. Capped/redacted
journals explicitly cannot claim a complete exact trace. Intermediate retry bodies
are deliberately unavailable. No historical backfill, analytics UI or new endpoint.

## Delivery review

Only the telemetry module, five service/persistence hooks, two focused test files
and this record are intended. No environment files, credentials, provider dumps,
generated artifacts or unrelated changes are included. Requested local commit:
`PRF-08S add safe research funnel telemetry`. No push.
