# ARK-04 — Citation integrity and telemetry phase semantics

## Scope and baseline

Offline remediation on `acceptance/live-desk-research-01`, starting HEAD
`871a7c7644f575289e125d692b35ba265013764e` (30 ahead / 0 behind local tracking).
No OpenAI/Tavily calls, live run, historical repair, policy redesign or push.
The existing untracked acceptance/runtime artifacts are not deliverables.

## Demonstrated root cause

ARK-03 run `b2aeac54-dd01-5908-a208-b096e03ca38c` persisted three defective
locators against source `1b538b34-822f-4add-910c-21c80e62450d`.
Its raw content SHA256 is
`3db24a4c07c05d2fb483327b983d77b76644b2d79f21bb5339b7a54ab7de6061`.

| Evidence | Stored half-open span | Correct full-source span | Historical qualification |
| --- | --- | --- | --- |
| 5e193ca2-e967-4d86-9ab5-ce2a46415825 | 2251:2421 | 9752:9922 | Qualifying |
| b3024cb7-3618-43e4-8e8c-a9313fcf821f | 2986:3286 | 10487:10787 | Nonqualifying |
| ab9746ca-9ca1-434b-ae2c-720910c77de4 | 2422:2910 | 9923:10411 | Nonqualifying |

The extractor receives a bounded chunk through a copied Source retaining the
full source ID/checksum. `_persist_candidate` previously grounded against that
chunk while supplying global chunk bounds (7500:13862). Those bounds exceeded
the shortened input, so `verify_grounding` fell back to searching its full input
— still only the chunk — and returned local offsets. Chunk normalization trims
leading whitespace; the demonstrated delta is 7501, not a safe blind +7500.
The model supplies excerpts, not these coordinates. Persistence preserved the
incorrect computed locator; neither a later source mutation nor invented excerpt
explains the defect. All 16 historical excerpts are grounded; 13 locators are valid.

Extraction still receives the same bounded text. Persistence now receives the
original canonical Source separately (retaining application-owned full-document
identity/alias metadata) and computes exact full-source locators,
using the existing preferred chunk range and exact-match fallback. No fuzzy
matching, guessed offset repair or historical rewriting is introduced.

## Canonical semantics and authoritative defense

The existing grounding representation is preserved: HTML references decoded
once, Unicode NFC, whitespace runs collapsed and trimmed; punctuation and case
remain significant. Offsets are half-open Python Unicode character indices into
the **full persisted Source after that normalization**, not bytes, UTF-16 units,
raw HTML positions or chunk-local indices. A focused edge case also exposed
double normalization in locator hash creation for nested HTML references:
`Literal &amp;lt; text` must hash the once-normalized `Literal &lt; text`, not
`Literal < text`. Hash creation now normalizes the original excerpt exactly once.

`application/evidence/citation_integrity.py` reads the referenced Source and
requires matching source/project identity, matching Evidence/Source content
checksum, SHA256 of actual persisted source text, integer in-range nonempty
bounds, exact normalized supporting span and matching excerpt hash. Missing
source/repository/locator fails closed. Validation never searches for alternative
coordinates or mutates a record. Invalid rows remain readable but nonqualifying.

The shared `qualifying_evidence` boundary runs this defense before unchanged
temporal qualification. Desk ARK, readiness initial/final reconciliation,
targeted research loop, Analysis, Report and Review all supply the canonical
Source repository. A generic fake-method call cannot certify Evidence without
source access. Citation telemetry uses `canonical_citation_filter`, distinct from
the temporal filter. ARK strategy remains separate from this shared truth boundary.

Old unit fixtures that claimed valid Evidence with nonexistent sources or
placeholder checksums now construct actual synthetic source text/checksum/span.
Existing sufficiency, temporal and budget assertions were not relaxed. The
explicit test-only fixture helper is never used on historical data. The existing
deterministic offline runner likewise produces grounded synthetic citations.

## Telemetry correction

Desk primitive decorators previously labelled every acquisition
`continuation_search` and every extraction `continuation_extraction`. Search and
acquisition were separate ARK actions, but the search observer finalized selection
before acquisition, falsely reporting unavailable acquisition budget and losing
candidate linkage in the later acquisition observer.

Acquisition labels now reflect the dispatched reservation's initial/continuation
resource; extraction labels reflect whether a continuation target is supplied.
Search records selection as deferred. Acquisition reuses retained candidate
events and finalizes only actually attempted identities. Controller logic never
reads these labels. Existing telemetry-disabled behavior remains unchanged.

## Validation

- New deterministic citation/real-Desk regression module: 12 tests passed.
  Includes the three historical offset shapes using synthetic text, wrong source,
  project, bounds/types/hash/checksum, content drift, Unicode/newlines/HTML,
  repeated exact spans, source ends, real later-chunk persistence and phase labels.
- Research-quality discovery: 477 tests passed after explicit fixture wiring.
- Analysis: 42 passed; Report: 19 passed; Review: 35 passed.
- PostgreSQL/API/worker affected group: **31 tests passed, zero skips** in 29.306s.
  Modules: `test_ark04_citation_integrity`, `test_ark02_ledger`,
  `test_ark02_desk_worker`, `test_worker_execution`,
  `test_worker_api_claim_integration`, `test_durable_workflow_runtime`,
  `test_research_loop_progress_checkpoint_recovery`, `test_prf08s_funnel_telemetry`,
  `test_prf08k_lineage_identity`, under `tests.integration.postgresql`.
  The new persistence regression proves invalid stored spans are excluded without
  modifying the stored rows; valid spans survive.
- PostgreSQL ran on dedicated internal-only network `ark04-citation-test`,
  container `ark04-citation-test-postgres`, disposable database `ark04_test`,
  tmpfs storage and no host port. Production dependency image
  `ai-research-os-prf08x:5508fb1` used current application/domain/infrastructure/tests
  read-only mounts; no root environment or provider credentials supplied.
- Canonical `python run_tests.py`: **3011 tests run in 173.959s;
  2 failures, 0 errors, 152 skips**. Exactly one invocation; do not describe this
  historical full-run result as green. Skips include class-level integration
  setup skips and are not passed tests.

### Post-full-run closure and exact limitations

The two failures were
`tests.application.test_prf08s_funnel_telemetry.FunnelTests.test_actual_temporal_rejection_visible`
and `test_o_pattern_and_on_off_decisions_identical`. The fixture omitted the
Source repository; its added future Evidence also reused an unrelated locator.
Supplying real synthetic source/span setup fixes both without weakening either
temporal rejection or on/off equality assertions.

Explicit evidence-module enumeration was also necessary because that namespace
directory is not importable by direct unittest discovery. Its 153 tests exposed
one ARK-04 regression: passing the full source discarded the application-owned
content identity added to the extraction copy. Preserving that metadata with the
full text corrected it without changing dedup behavior. An initial direct
discovery invocation failed before collecting tests; it is not a test pass.

Final targeted command: `python -m unittest <all test_*.py modules under
tests/application/evidence> tests.application.test_prf08s_funnel_telemetry
tests.application.test_ark04_citation_integrity tests.application.test_ark02_desk
tests.application.test_ark02_desk_integrity -q`: **194 passed, no skips,
0 failures/errors, 10.747s**. Includes 6+2 replay, real Desk telemetry on/off
controller-state equality, nested-entity hash, full-source dedup metadata and the
two exact full-run failures. No second canonical full run was performed.

Final PostgreSQL validation after hash/telemetry corrections: the above 31-test
group plus `test_prf08c_evidence_integrity`: **33 passed, no skips, 33.238s**.
After the final full-source metadata correction, reran
`test_ark04_citation_integrity`, `test_ark02_desk_worker`,
`test_prf08s_funnel_telemetry`, `test_report_crash_recovery`,
`test_report_concurrency`, `test_review_crash_recovery`,
`test_review_concurrency`, `test_run_report_artifact_isolation`:
**18 passed, no skips, 14.677s**. These groups overlap; do not sum them as unique
tests. Expected negative worker tests log errors while their assertions pass.
The shared downstream fixture now persists real checksum/locator and an explicit
2026 observation period already stated in its synthetic text and brief.

An additional existing integration test remains failing:
`tests.integration.postgresql.test_two_run_review_isolation.TwoRunReviewIsolationPostgreSQLTests.test_two_runs_keep_independent_review_and_artifact_state`,
line 68: expected `final_review_verdict == 'approve'`, actual `None`.
It reproduced identically on exact committed HEAD `871a7c7644f575289e125d692b35ba265013764e`
unpacked by `git archive HEAD application infrastructure domain tests` into a
separate ephemeral container (1 test, 1 failure, 1.319s). Thus it is not introduced
by ARK-04. No production workaround, test exclusion or weakened assertion was
added. It remains a pre-existing downstream acceptance limitation, not a claim
that the entire PostgreSQL suite is green.

Compilation and `git diff --check` pass. No known ARK-04 correctness failure
remains; the unrelated baseline failure is explicitly retained above.

The 6 initial + 2 continuation = 8 extraction envelope, retries, acquisition/search
ceilings, queries, rankings, qualification policy and sufficiency thresholds are
unchanged. Live citation revalidation and live telemetry labels remain NOT VERIFIED.

## Fresh historical integrity — 2026-09-27

Read-only transactions against each original database used Evidence count and
`md5(string_agg(row_to_json(e)::text,chr(10) ORDER BY id))`, plus
`md5(row_to_json(w)::text)` for its workflow row. All matched previous records.
No historical qualification outcome was rerun/recomputed. O resides in the L
container. ARK-03 remains the original failed acceptance, not retroactively passed.

| History | Evidence | Evidence MD5 | Run-row MD5 |
| --- | ---: | --- | --- |
| B | 13 | 076646d8ec25f2a7d682ec420896af95 | 00ef1aa66c3b6194ba39d1a01c066de7 |
| D | 33 | 84ce68280d94941b19414a46893f2868 | 01e242df696ac51050788442c6249471 |
| F | 22 | 7937d0745c8c03a67ffc045c9fbbb6f5 | 3eedf9afcfbd4b61b1eaa672bc36f3f8 |
| H | 24 | 3866b66b19d3ec31ff6210fafa297922 | 60fd6bb7a92d1c36f0bb04073d567e47 |
| J | 27 | 299e88abe27b9363fd623f5f9e034eac | 2e66c4ab0dbf4365877c97e61e053576 |
| O | 1 | 135c9ec526cdd2672bd61b52e7902f7d | 9dcb9c3b7526dd0eeb2a625876460c28 |
| T | 5 | 3c15be644e3a45f47955bc1da2bfd412 | eab5db1fd4860e5011a91c6fefed1e53 |
| V | 21 | 7f9ca2da74d75c5bae0107a425108309 | 0efe638f7ce58baa6dc785d499f340ce |
| X | 0 | NULL | cc468d87e5efe063634cfbd4b75afd31 |
| ARK-03 | 16 | e93284678aa04afd32cee577a1601093 | b6dfb8368131bc7ab75d201dd8ae0917 |

No schema migration, historical repair, paid call or push. Reviewed changes are
limited to shared citation defense, canonical-source grounding/hash, observer
labels, dependency wiring, deterministic fixtures/tests and this record. No
credentials, environment files, raw provider payloads, runtime logs or historical
artifacts are Git deliverables. The approved local commit subject is
`ARK-04 enforce citation integrity`; final SHA is reported after creation.

ARK-04_READY_FOR_LIVE_REVALIDATION
