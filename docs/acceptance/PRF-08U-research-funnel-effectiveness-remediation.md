# PRF-08U — Bounded research funnel effectiveness remediation

## Baseline and scope

Branch `acceptance/live-desk-research-01`; initial HEAD
`78c7ffa7e6dce0bab6dfc5c4d9e1a30b5821a055`, ahead 23 / behind 0 against the
recorded upstream. Tracked/index initially clean. Existing untracked acceptance
artifacts preserved. OFFLINE ONLY: no OpenAI, Tavily, new live run or push.
No historical outcome was evaluated with the new logic or rewritten.

## Exact demonstrated causes

PRF-08T had 11 search calls, 22 candidate observations, 9 fetches/7 successes,
8 extraction calls, 6 valid-empty, 5 stored Evidence/2 temporally qualifying.
The changes address separate deterministic mechanisms without claiming all poor
retrieval is solved:

1. `project_provider_query_text` treated timeframe as optional: a long timeframe
   or a full 220-character projection silently dropped it. Reference-only IN
   periods such as “Same observation periods as IN1” were not resolved against
   the frozen brief. IN3 lost the explicit date; IN2 repeated its previous text.
2. Targeted requests received new IDs but had no independent record of dispatched
   query content. Same complete aspect bundle or a projection omitting the target
   could produce an identical provider query.
3. The acquisition loop's need fairness preceded category alignment. Successful
   acquisition updated coverage even for a **known category mismatch**, allowing
   early completion after unrelated software documentation represented IN5.
   The January statistical candidate was initially skipped for source coverage,
   later acquired in continuation and productive. Original stored decisions were
   read only: StackOverflow/Dremio were `category_not_preserved`, geography proxy;
   the regional funding source was proxy; the US press release was nevertheless
   classified direct by existing signals. This last signal-quality limitation
   is not disguised as fixed by reordering.
4. Adaptive depth penalized only *two* observed empty calls. After first-source
   opportunities, an uncovered need could immediately receive a second empty
   chunk ahead of a productive/distinct opportunity. Existing canonical
   source/need exhaustion already handled completed valid-zero sources during
   targeted recovery; it is retained.
5. Temporal eligibility required metadata `observation_period`. PRF-08T Evidence
   `e7a29c65-e7e8-476e-a01e-3433ceb4fb50` had a leading as-of measurement in both
   canonical statement and excerpt but no metadata field, thus unresolved. No
   historical row was repaired or reclassified in storage.

## Query intent and repetition

`query_temporal_intent.observation_window` retains an explicitly dated IN period.
For quantitative or explicitly dated/deployment/change/measurement needs whose
period is absent or referential, it uses the brief's observation clause, not the
publication-availability suffix. Pure undated definition/methodology needs remain
undated. The initial and targeted builders use the resolved period in both the
complete query and provider projection. If a dated projection cannot fit safely,
it falls back to the complete internal query instead of discarding the constraint.

`research_executed_query_fingerprints` is a small canonical shared-state list of
SHA256 fingerprints of target-IN plus normalized executed query text. It is
written at dispatch, checkpointed by existing persistence, and is **not** derived
from optional/capped telemetry. Historical checkpoints lacking it remain valid.

Before a targeted call, a repeated text is replaced, within the same list size,
by a query constraining an existing requested/expected aspect as an exact phrase.
It retains the complete topic/need/geography/period context. Previously executed
alternatives are skipped; if no grounded distinct alternative remains, the
request yields no search instead of adding an unbounded retry. The existing
bounded research loop may proceed to another need. No arbitrary domain, operator,
market term or invented quality score is appended.

Initial baseline/localized arms remain separate provider strategies even when
their text matches; country/arm differences are not automatically wasted calls.
The history suppresses equivalent *continuation* opportunities, not all matching
text across different INs or retrieval strategies. Quoted aspects are a practical
distinct retrieval intent, not a promise that the provider returns different URLs.

## Candidate selection and valid-empty feedback

Within the unchanged attempt cap, selection orders known duplicates last, then
known category mismatches, then fewer already-persisted Evidence refs, existing
need-opportunity fairness, and the existing relevance order. Evidence counts are
raw canonical run-scoped refs, not a new semantic sufficiency calculation.
Known mismatch cannot establish acquisition coverage for an explicit expectation.
Legacy thin designs with no expectation preserve their established fail-open
coverage behavior. A mismatch can remain an auditable fallback; it is not a
fabricated successful target coverage signal.

Existing geography signals now demote **known proxy/unrelated** candidates before
expectation boosts. Unknown geography is not treated as known wrong: existing
official-statistics preference remains valid. This is signal ordering only, not
a new source/domain allowlist. No discovery provenance is relabeled across INs.

After first-opportunity fairness, one observed valid-empty with no productive
calls deprioritizes further depth from that source; it does not label unseen
chunks empty or prohibit all later depth. Distinct first opportunities still
precede depth. Technical failures are not treated as semantic exhaustion.
The existing target-specific completion, cross-IN Evidence retention, content
alias exhaustion, lineage normalization and conservative readiness remain intact.

## Conservative temporal rule

Existing explicit `metadata.observation_period` takes precedence and must still
be grounded in the excerpt. A conflicting/unusable explicit field is not replaced
by a guessed alternative. The new read-only fallback is intentionally narrow:

- both canonical `statement` and `source_excerpt` must start with `As of` and the
  **same exact day** (supported ISO or named-month representation);
- each date must directly introduce a measurement clause such as “there were”,
  with an optional intervening geography phrase;
- publication/release/forecast claims are not accepted as measurements;
- the same existing cutoff/forecast rules apply afterward; a post-cutoff as-of
  date remains out-of-period;
- no publication timestamp, arbitrary embedded date, undated claim, mismatched
  date or non-exact period is promoted by this fallback.

These are canonical extraction fields, not source-publication metadata. A date
only in an unrelated excerpt sentence is insufficient. No new metadata field,
schema migration or historical backfill is introduced. Nonmatching language or
syntax remains conservatively unresolved. Claim-specific static-methodology
eligibility from PRF-08E is unchanged.

## Bounds and observational invariant

No configuration, maximum-results, source cap, retry limit or budget was raised.
Query replacement is at most one-for-one; exhausted alternatives produce fewer
calls. Acquisition loop still increments the same considered counter before each
attempt and never refunds failed/duplicate fetches. Depth ranking changes order,
not call limits. Explicit regression checks six initial calls then rejection,
two reserved continuation calls then rejection: **6+2=8**.

PRF-08S journal is untouched and never read by the new policy. On/off fixtures
compare actual acquisition/extraction calls and final sufficiency; outcomes match.
Its query/selection/result hooks observe the new decisions. The canonical history
exists independently of telemetry and contains hashes, not raw response payloads.

## Validation evidence

New `tests.application.test_prf08u_funnel_effectiveness`: **20 passed**, including
material/nonmaterial time queries, repeat/alternative exhaustion, zero-Evidence
priority, domain-independent ranking, mismatch coverage, valid-empty feedback,
explicit/as-of/unknown/publication/arbitrary/post-cutoff temporal cases, 6+2 and
the deterministic PRF-08T-shaped composite fixture. The fixture combines multiple
empty extractions and unused/duplicate candidates, on/off parity, repeated query
recovery, weaker-versus-aligned bounded acquisition, safely dated canonical
Evidence outside the metadata period field and conservative final refusal.

Targeted results:

- PRF-08U + PRF-08S + PRF-08K target fidelity + PRF-08P content identity:
  **61 passed**.
- Source discovery suite: **210 run, 208 passed, 2 skipped**.
- Evidence suite: **153 passed**; research-quality suite: **477 passed**.
- Final temporal/PRF-08U/PRF-08S/PRF-08C selection: **46 passed**.
- Canonical `python run_tests.py`, exactly once: **2927 run, 2778 passed,
  149 skipped, zero failures/errors**, 160.639 seconds.

Sequencing disclosure: the full run was already in progress when final inspection
refined the as-of parser to accept the demonstrated intervening-geography shape
and tightened the directly introduced measurement clause. Therefore it is not
claimed as a fresh whole-suite run of that final localized revision. After this
change, all evidence (153), research-quality (477), focused temporal (46), and
final new regressions (20, including extended composite assertions) were rerun.
The full suite was not repeated, honoring the exactly-once instruction.

Affected isolated PostgreSQL/API-worker selection: **22 passed, zero skips**,
including journal JSONB/failed checkpoint, content identity, lineage, temporal
roundtrip, source provenance concurrency, research-loop progress recovery,
worker claim/API execution and worker failure isolation. After final temporal
refinement, the four temporal/journal PostgreSQL tests were rerun separately:
**4 passed, zero skips, failures or errors**.
Current source was mounted read-only into the production-compatible image;
test PostgreSQL used an internal network and tmpfs, no historical volume or keys.
Existing migrations to `016_prf06f_pptx` ran only on this disposable test DB.

Two provisional approaches were corrected before closure, without weakening old
tests: ranking *unknown* geography below direct broke one official-statistics
test; counting generic legacy category mismatches as failed coverage broke six
thin-fixture coverage tests. The final narrow signal rules restore all seven.

## Historical preservation

Fresh original-container `BEGIN READ ONLY` checks compare Evidence count,
`md5(string_agg(row_to_json(e)::text,chr(10) ORDER BY id))` and workflow-row MD5.
No PRF-08U evaluator was applied to any historical Evidence. All match prior
accepted fingerprints, all workflow statuses remain completed:

| History | Evidence | Evidence MD5 | Workflow MD5 |
| --- | ---: | --- | --- |
| B | 13 | 076646d8ec25f2a7d682ec420896af95 | 00ef1aa66c3b6194ba39d1a01c066de7 |
| D | 33 | 84ce68280d94941b19414a46893f2868 | 01e242df696ac51050788442c6249471 |
| F | 22 | 7937d0745c8c03a67ffc045c9fbbb6f5 | 3eedf9afcfbd4b61b1eaa672bc36f3f8 |
| H | 24 | 3866b66b19d3ec31ff6210fafa297922 | 60fd6bb7a92d1c36f0bb04073d567e47 |
| J | 27 | 299e88abe27b9363fd623f5f9e034eac | 2e66c4ab0dbf4365877c97e61e053576 |
| O | 1 | 135c9ec526cdd2672bd61b52e7902f7d | 9dcb9c3b7526dd0eeb2a625876460c28 |
| T | 5 | 3c15be644e3a45f47955bc1da2bfd412 | eab5db1fd4860e5011a91c6fefed1e53 |

## Remaining live NOT VERIFIED and delivery

Actual new provider results, better live yield and substantive sufficiency are
NOT VERIFIED. Existing geography classification can still label a foreign
document direct; this patch uses existing signals, not a semantic classifier.
No claim that a discarded unacquired page is useful, or that all historical
unresolved facts now qualify. Phrase-focused searches can still return duplicates.
Broad engine redesign, new search calls and temporal speculation are excluded.

Reviewed deliverables are application policy changes, two small query helpers,
one regression file and this record. No secrets/environment files, raw provider
or page dumps, historical mutations, migration or unrelated runtime artifacts.
Requested single local commit: `PRF-08U improve bounded research funnel effectiveness`.
No push; no live validation was performed.
