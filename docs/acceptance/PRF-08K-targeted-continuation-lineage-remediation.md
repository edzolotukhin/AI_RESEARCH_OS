# PRF-08K — Targeted continuation fidelity and lineage identity

## Baseline and scope

Repository `C:\AI_AGENTS\AI_RESEARCH_OS`, branch `acceptance/live-desk-research-01`, initial HEAD `06bc571b51ce7b5e79cc1e45115edbd163542417`, ahead 13 / behind 0 against the recorded upstream. Tracked tree/index were clean; existing untracked acceptance/runtime artifacts were preserved. This task is **offline only**: no OpenAI, Tavily, live research activation, historical outcome recomputation, or push.

## Exact PRF-08J root causes

The original run `28b1b640-1ad0-5614-b1e0-4a01e9db3e19` preserved six initial extraction calls, two reserved calls, and a first targeted request for zero-Evidence IN3. `ProductionTargetedResearchRunner` passed acquired source IDs into `extract_for_source_ids`, but did not pass the requested IN. A reused source retained its legitimate broad run-scoped refs IN1/IN2/IN3/IN5. The extraction scheduler consequently assigned IN1 as primary and the LLM saw no explicit IN3 repair target. Its one reserved call returned two grounded items for IN1/IN5, not IN3. Those items are not invalid simply because they failed to repair IN3.

The loop then unconditionally reassessed all changed qualified Evidence. IN1/IN5's new fingerprints consumed the two remaining sufficiency calls. The next-loop sufficiency precheck stopped at six semantic calls before IN4 received its bounded turn, although one extraction reserve remained. The previous `improved` flag was already false for IN3; the defect was not a falsely ready report, but loss of target focus and premature spending on incidental cross-IN reassessment.

## New target semantics and bounds

- The production runner passes `target_information_need_id` through extraction service, run-scoped context and prompt. Targeted work items explicitly retain that primary IN. A source without the target in its authoritative run-scoped refs is not silently widened or relabelled; it receives no targeted extraction call. Existing allowed cross-IN refs remain valid, so useful incidental Evidence is not discarded or reassigned.
- The loop snapshots qualified Evidence before/after each attempt. Diagnostics distinguish target-qualified before/after/delta from global Evidence yield. Cross-only gains cannot mark the target as improved.
- When an attempt adds only cross-IN qualified Evidence, extraction capacity remains, and another actionable, non-stalled, non-exhausted zero-qualified-Evidence target exists, global semantic reassessment is deferred. Deterministic reconciliation keeps the target MISSING and marks changed positive-IN assessments stale rather than ready. The ordinary priority scheduler can then use the next bounded opportunity. When no such opportunity remains, ordinary evaluation/budget-stop behavior applies.
- No counter, retry limit, sufficiency threshold, search cap or worker policy is increased. The low-cost profile remains **6 initial + 2 reserved Evidence calls, total 8**, at most one Evidence call per targeted attempt, one configured gap round and one configured attempt per gap. Structured retries continue to consume the existing call budget. Deferral itself makes no model/search call. Sufficiency's existing cap of six remains authoritative; evidence gains do not bypass semantic readiness.

This is not search-until-success. Exhausted Evidence/sufficiency, stalled needs, per-gap bounds and terminal reconciliation remain valid stops. If all gaps are genuinely assessed sufficient, normal readiness can proceed. A remaining call is not a guarantee that useful public evidence exists.

## Lineage defect and generic rule

Read-only inspection of PRF-08J confirmed the persisted established origins `Department for Transport, sourced from Zapmap` and `Zapmap`, each with grounded attribution excerpts. `_independent_lineages` previously used only `.strip().casefold()` on the entire origin string, so the publisher-plus-upstream label and upstream-only label became different identities. The ONS population-denominator origin is a distinct attribution and is not merged into Zapmap.

The new pure `canonical_lineage_identity` uses Unicode NFKC, case folding and whitespace normalization. For an established origin whose full normalized text occurs in its stored basis excerpt, an explicit `publisher, sourced from upstream` identity relation resolves to the named upstream. This is a generic syntactic relationship, not a brand/domain allowlist or similarity match. There is no Zapmap literal in product code. Dataset names, legal suffixes, URL identities and merely similar organization names are not stripped or fuzzily merged. An unsubstantiated relationship is not resolved as an alias.

The existing grounded persistence boundary remains authoritative; candidate-supplied lineage cannot self-certify. Canonicalization is applied at read/evaluation time without rewriting origin metadata or historical rows. Unknown lineage remains unknown: it cannot corroborate a known origin or create extra independent streams. The prior single provisional unknown-stream behavior is retained, including its warning; it is not a promotion to established provenance.

The sufficiency cache contract advances from `prf-08c.1` to `prf-08k.1`, preventing previously cached semantic readiness from bypassing the changed independence rule. One literal version test was updated for this intentional invariant; a new regression proves an old-version cache entry is not reused. No schema migration is required.

## Deterministic evidence and validation

The integrated synthetic PRF-08J fixture starts with IN3/IN4 empty and positive IN1/IN5. Its first targeted IN3 attempt appends only IN1/IN5 Evidence. Assertions prove IN3 stays empty, the attempt is not successful, cross-IN rows remain saved, no intermediate semantic calls are spent on those gains, and the remaining reserved call is directed to IN4. Total Evidence calls are eight and sufficiency calls six. Separate tests verify exhausted budgets, a last-slot cross-only result staying not ready, genuinely closed gaps stopping normally, actual extraction prompt/context target propagation, and rejection of scope widening. Mock LLMs only are used.

Lineage tests cover the observed attribution shape and an unrelated synthetic provider, Unicode/case/whitespace variants, genuinely different organization/dataset identities, missing attribution support, unknown provenance, and cache invalidation. A disposable PostgreSQL JSONB round trip proves equivalent origins count once while stored original names remain unchanged.

Commands/results on the final implementation:

- `python -m unittest tests.application.research_quality.test_prf08k_target_fidelity`: **11 passed**.
- `python -m unittest discover -s tests/application/research_quality -p 'test_*.py'`: **477 passed**.
- `python -m unittest discover -s tests/application/evidence -p 'test_*.py'`: **137 passed**.
- `python -m unittest discover -s tests/infrastructure/evidence -p 'test_*.py'`: **159 passed**.
- Materially affected integration/worker selection: **17 passed, zero skipped**. Modules: `test_prf08k_lineage_identity`, `test_prf08c_evidence_integrity`, `test_research_loop_progress_checkpoint_recovery`, `test_worker_execution`, `test_worker_api_claim_integration`, `test_worker_execution_service`, `test_worker_loop_failure_isolation`, and `test_worker_loop_defaults` in their existing PostgreSQL/application directories. These ran with the current source mounted read-only over the production-compatible PRF-08J dependency image, not its old product source. A new `ai_research_os_prf08k_test_postgres` used a tmpfs-only `prf08k_test` database on internal network `ai_research_os_prf08k_test`, no host port and no provider credentials. No historical volume was attached. External providers were unreachable from that test network. Existing migrations were applied only to this disposable database; no migration was added.
- Canonical `python run_tests.py`, run once: **2874 tests, 146 skipped, zero failures/errors**, 111.995 seconds. Integration skips in the standard offline run are not counted as PostgreSQL passes; the affected 17-test selection above ran separately with the disposable test flags enabled and zero skips.

No unrelated renderer/image/migration-cycle qualification was repeated: their implementations and schema did not change. The full offline suite includes their existing offline coverage; the targeted API→worker/checkpoint path was actually executed against disposable PostgreSQL.

After successful validation, only the newly created `ai_research_os_prf08k_test_postgres` tmpfs test container and `ai_research_os_prf08k_test` network were removed. Its synthetic test data was intentionally discarded and is reproducible from the tests; no historical container, named volume or acceptance artifact was removed.

## Historical preservation

Only SELECT queries were issued against original PRF-08B/D/F/H/J databases. Canonical Evidence digests use `md5(string_agg(row_to_json(e)::text, chr(10) ORDER BY e.id))`, scoped to recorded run IDs. All counts/checksums match their accepted records; all workflow statuses remain `completed`:

| Run | Evidence | Evidence digest | Workflow-row digest |
| --- | ---: | --- | --- |
| PRF-08B | 13 | `076646d8ec25f2a7d682ec420896af95` | `00ef1aa66c3b6194ba39d1a01c066de7` |
| PRF-08D | 33 | `84ce68280d94941b19414a46893f2868` | `01e242df696ac51050788442c6249471` |
| PRF-08F | 22 | `7937d0745c8c03a67ffc045c9fbbb6f5` | `3eedf9afcfbd4b61b1eaa672bc36f3f8` |
| PRF-08H | 24 | `3866b66b19d3ec31ff6210fafa297922` | `60fd6bb7a92d1c36f0bb04073d567e47` |
| PRF-08J | 27 | `299e88abe27b9363fd623f5f9e034eac` | `2e66c4ab0dbf4365877c97e61e053576` |

The B/D/F/H workflow digests match PRF-08J's recorded pre/post values. J's workflow digest is additional read-only fingerprint evidence in this task; its Evidence digest matches its accepted record. Historical sufficiency was not evaluated with the new normalizer; no run was restarted, recomputed, repaired, migrated or reseeded. Their original acceptance documents were not rewritten.

## Remaining limits and delivery

Live target-fidelity, actual provider responses/cost and productive coverage remain **NOT VERIFIED**. A focused prompt improves fidelity but cannot guarantee relevant Evidence; counters and target-specific success checks, not prompt promises, enforce the contract. Canonical lineage deliberately does not infer undocumented aliases, abbreviations or fuzzy name similarity. Other attribution phrasings require grounded structured identity evidence or a separately justified extension; unrelated-looking origins are not merged speculatively. No complete source-identity registry or new planning subsystem was introduced.

Only intended product/tests/this acceptance record are eligible for the local commit `PRF-08K harden targeted continuation and lineage identity`. No secrets, `.env`, paid-provider payloads, runtime dumps, historical-data edits or unrelated untracked artifacts belong in that commit. No push or live rerun is part of PRF-08K.
