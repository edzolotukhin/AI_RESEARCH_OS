# PRF-08R — Research discovery effectiveness diagnosis

**Dominant diagnosis: INSUFFICIENT_TELEMETRY.** The observed loss is mainly
zero-yield extraction, but the retained record cannot distinguish unsuitable
retrieval/selection from failure to extract qualifying facts actually present
in the selected material. One duplicate-content extraction is demonstrated;
it does not explain the other six nonproductive calls. No new deterministic
orchestration defect with a demonstrably useful missed alternative is proven.

## Baseline and method

Branch `acceptance/live-desk-research-01`; initial HEAD
`63528595ecbbbc8d1d16cf37ae10ae65bafa0283`, tracked/index clean, existing
untracked acceptance artifacts preserved. PRF-08P/Q are not redone.

Read the relevant PRF-08O/P records, source/query/selection code, and selected
metadata in the original PRF-08L PostgreSQL instance. All database access was
inside `BEGIN READ ONLY` transactions. No providers, activation, research
recomputation, migrations, fixture creation, Docker lifecycle changes or push.

Historical run: `966141f8-b07f-510c-8e41-66795ab65227`; design:
`0f333dd1-54bc-49a0-b758-0e308e61c336`; project:
`f8b634b0-dae6-44a1-86ed-cc1c00726e9f`. Sources S1–S6 use the labels in PRF-08O.
Qualification counts below reuse that accepted historical result and persisted
readiness/history, not a new evaluator applied to old Evidence.

## Per-IN funnel

An intent means one design IN; targeted queries are shown separately.
`R` means deterministically reconstructed portfolio allocation, not a retained
request log. `O` counts distinct query-ID/retrieval-arm pairs in saved source
discovery records. Baseline/localized searches can have identical query text
but different country parameters. Initial six baseline/five localized calls
and two targeted calls are recorded in aggregate.

The country resolver and provider/portfolio/query projection code are unchanged
from PRF-08O. Offline country resolution supports localization for IN1/3/4/5/6,
but not the string `UK regions and devolved administrations` used by IN2.
This reconstructs 11 initial arm invocations. The two missing provenance arms
are IN1-localized and IN6-localized; their responses/failures are NOT OBSERVABLE.

| IN / RQ | Intents initial + targeted | Queries R / O | Known response entries / retained distinct URLs | Selected/acquired source scope | Fetch attempts / successes in scope | Extraction primary / in-scope | Evidence / qualifying | Observed loss |
| --- | ---: | ---: | --- | --- | --- | ---: | ---: | --- |
| IN1 counts/definitions / RQ1 | 1+1 | 3 / 2 | ≥6 / 2 | S1, S5 | ≥2 / 2 | 2 / 2 | 0 / 0 | First empty; continuation repeats S1 content |
| IN2 regional breakouts / RQ2 | 1+0 | 1 / 1 | 3 / 1 | S2 | ≥1 / 1 | 2 / 2 | 1 / 1 | First empty; depth yields per-capita rates, not requested raw regional counts |
| IN3 site types / RQ2 | 1+1 | 3 / 3 | 9 / 2 | S3, S6 | ≥2 / 2 | 3 / 3 | 0 / 0 | Three empty calls; S6 second chunk not executed |
| IN4 operator announcements / RQ3 | 1+0 | 2 / 2 | 6 / 2 | S2, S3 | ≥2 / 2 | 0 / 4 | 0 / 0 | Shared statistical sources yield no IN4 Evidence; no dedicated primary attempt |
| IN5 utilization / RQ4 | 1+0 | 2 / 2 | 6 / 2 | S2, S3 | ≥2 / 2 | 0 / 4 | 0 / 0 | Shared installed-capacity sources yield no utilization Evidence |
| IN6 definition mappings / RQ5 | 1+0 | 2 / 1 | ≥3 / 1 | S4 | ≥1 / 1 | 1 / 1 | 0 / 0 | US regulation proxy yields empty |

Important counting limits:

- `provider_result_count=3` is the returned `results` array length, verified in
  the provider adapter, not the requested maximum. Repeated records of the same
  query/arm on two sources are counted once. These counts do not retain the
  full result list, snippets or per-IN canonical candidate sets. Complete
  per-IN candidate counts and unselected identities are **NOT OBSERVABLE**.
- Acquisition/extraction scopes overlap: S2 and S3 were discovered for several
  INs. Do not sum the per-IN source/scope columns as independent calls.
  Initial actual fetches = 4, successes = 4, failures = 0. Targeted successful
  acquisitions = 2; targeted total attempts/failures are NOT OBSERVABLE.
- Initial selection decisions use their best scoring IN: S3→IN5, S2→IN2,
  S1→IN1, S4→IN6. This is not the extraction primary target. The latter is
  IN1, IN2, IN3, IN6, IN2, IN3, then targeted IN1 and IN3: exactly eight.
- IN4/5 were included in four extraction contexts, not ignored altogether;
  discovery membership does not mean a document actually contains those facts.
- The sole IN2 Evidence was qualified but readiness remained partial: the
  persisted assessment explicitly identifies missing `regional_count`.

## Capacity-loss accounting

13 searches: 11 initial plus two continuation. Initial search recorded 27 raw
candidates, 18 canonical URL groups. Four URL groups were acquired and 14
were left unattempted after formal coverage completion. No initial candidate
was recorded ineligible/exhausted/duplicate; zero initial retrieval failures.
Unattempted URLs and their rankings/snippets were not retained in the summary.

Eight extraction opportunities reconcile without inventing rejected candidates:

| Disjoint call category | Calls | Evidence |
| --- | ---: | --- |
| Productive S2 depth | 1 | One raw and qualifying IN2 Evidence |
| Known duplicate-content continuation S5 | 1 | Zero; detailed response shape not retained |
| Valid empty, nonduplicate opportunities | 6 | Zero: S1 first, S2 first, S3 first/depth, S4 first, S6 first |

Thus seven calls produced no Evidence. Five of six INs remained zero. The
duplicate category overlaps the broader no-target-Evidence category and is
not counted twice. No reserve slot was lost by PRF-08K; 6+2=8 was consumed.

Other requested classifications:

- Query misalignment: no wholly unrelated query demonstrated. Specific
  compression/temporal omissions are documented below; their causal cost is
  NOT OBSERVABLE.
- No useful candidate returned: NOT OBSERVABLE; empty extraction is not proof.
- Useful candidate returned but not selected: NOT OBSERVABLE for the 14 URLs.
- Selected irrelevant candidate: S4 is a US regulatory proxy in a UK case,
  but whether it could supply comparative definitions is not established.
  It cost one empty call; do not label all its content irrelevant by domain.
- Acquisition failure: zero recorded initially; targeted total NOT OBSERVABLE.
- Extraction technical failure: zero in the seven detailed work-item traces;
  continuation #1's response classification is NOT OBSERVABLE.
- Geography/time/lineage rejection: zero demonstrated in retained candidate
  outcomes; first continuation's detailed rejection counters are NOT OBSERVABLE.
  Six empty arrays are not candidates rejected by qualification.
- Unknown lineage did not create independent corroboration. IN2 remained
  partial, so conservative sufficiency is not evidence of a broken gate.

## Query effectiveness

Saved `provider_query_text`, query ID, RQ/IN IDs, retrieval arm, country and
result count establish the following, without regenerating a live query:

- All saved queries retain an IN-specific description and UK geographic
  meaning. Provenance RQ/IN links match the persisted design. Parent RQ text
  appears in the long IN1/IN6 fallback queries; compact IN2–IN5 omit that full
  sentence but retain their specific intended metric/entity in the description.
- Common prefix is exactly `publicly accessible chargers rated least`.
  It is linguistically incomplete. IN1/2/4/5 restore `50 kW+` in their core
  descriptions; IN3's saved query has no explicit power threshold. This is a
  visible specificity limitation, not proof that it caused the low yield.
- IN1 baseline and targeted #1 are text-identical, including the RQ and fixed
  2025/2026 cut-offs. A different source URL came back, but with identical full
  content. This is the strongest observed lack of effective diversification.
- IN3 baseline/localized text is
  `publicly accessible chargers rated least United Kingdom Counts/shares by site-type (retail, destination, en-route) only where definitions and tagging are disclosed and comparable`.
  Targeted #2 appends only `site type definition`; it retains the target but
  does not specifically add counts, power or a date window.
- IN2 ends with `Regionally segmented counts/shares of 50 kW+ chargers/devices/sites with clearly matched definitions and dates across regions`.
  The saved request has no explicit observation window despite the design's
  2025/latest-2026 requirement.
- IN4 retains `Dated operator and retailer announcements naming 50 kW+ deployments, partnerships, or openings, with stated power levels and locations`.
  IN5 retains `Publicly disclosed utilization or use indicators for 50 kW+ chargers with clear method, scope, time base, and sample definition`.
  Neither provider query retains explicit 2025–1 July 2026 dates.
- The unchanged generic projector treats dates as optional (≤48 characters,
  a year present, total ≤220). It preserves whole required units or falls back
  to full internal text. This explains observed omission, not a new proven
  defect warranting a heuristic change here. IN1/6 use full fallbacks retaining
  temporal context. Search-time omission does not remove downstream temporal
  qualification.
- Localized arms repeat text but add country prioritization: not equivalent
  requests in every parameter. IN3/4/5 visibly reused S2/S3 across searches.
  Whether other returned candidates offered diversification is NOT OBSERVABLE.
- Initial searches precede Evidence, so they cannot target an already-covered
  Evidence need. Both continuations targeted zero-Evidence IN1/IN3; IN2's
  partial assessment was reused, not researched again. No improper preference
  for an already-covered need is demonstrated.

## Candidate selection: what the rule proves and does not prove

The recorded selection scores classify S2 direct and S1/S3/S4 proxy. S3's
best IN is utilization with expectation boost 132; S2 has boost 101. The
generic group selection uses best category/expectation/tier/topic/geo scores
and then acquisition coverage fairness. Source discovery references are
unioned by `_update_coverage_from_source` after successful acquisition.
Formal coverage therefore became 6/6 from four documents, independently of
later evidence yield, causing `coverage_complete_early_stop` with 14 URLs left.

This distinction between discovery coverage and qualifying Evidence explains
the funnel discontinuity. It does **not** prove that extending collection
would have selected a useful document within the same envelope. We lack the
14 candidates' identities, scores, per-IN memberships and contents. Ranking
cannot be replayed faithfully from four surviving decisions. A statistically
authoritative page receiving a high lexical/expectation score for a different
metric is a risk, but its superiority/inferiority to the omitted alternatives
cannot be established. Classification among A/B/C is therefore **D**.

## PRF-08P counterfactual

S1/S5 are the one proven full-content alias pair. Under unchanged inputs,
PRF-08P can suppress S5's repeated processed chunk for the same IN. This saves
at most one demonstrated downstream call; it does not refund an unknown
mirror's acquisition, authorize another search or establish any new Evidence.

The first four source documents were distinct, so PRF-08P's distinct-content
early-stop check alone does not demonstrate that the initial four-source
selection would change. The next distinct candidate in IN1's search result
list is **NOT OBSERVABLE**. S6 is known to have been used later for IN3, but
there is no evidence it was an eligible next IN1 candidate. Its unprocessed
second chunk is known, yet the unchanged one-call-per-targeted-attempt cap
means a spared global call is not automatic permission to process that chunk.
No qualifying result for that chunk/another candidate is persisted.

Accordingly PRF-08P plausibly prevents one waste, but a material outcome change
or closure of any of the five zero-Evidence INs cannot be predicted from this
record. No historical run was replayed, rescued or reinterpreted.

## Validation, preservation and next gate

Seven SELECT-only reconstruction assertions passed: six sources, five content
checksums, six initial work items, two continuation entries, eleven initial
queries, 27 raw candidates and 18 canonical groups. An offline resolver probe
confirmed the five supported localized geographies and the IN2 exception.
SQL per-IN provenance aggregation reproduced observed arm counts
`2,1,3,2,2,1` and source counts `2,1,2,2,2,1`. An initial diagnostic SQL query
needed an explicit JSON→JSONB cast; it failed without writes and was corrected.

Fresh historical O Evidence count/digest: 1 /
`135c9ec526cdd2672bd61b52e7902f7d`; workflow digest
`9dcb9c3b7526dd0eeb2a625876460c28`, both unchanged. Other histories were not
touched; their PRF-08P preservation evidence is reused. No product/schema/test
changes, full suite or unaffected integration gates were required.

Next gate requires a separately scoped observability decision before making
causal ranking/search changes: retain bounded per-query result identities and
IN/arm mapping, selection/rejection scores/reasons and unattempted candidates,
plus every continuation's safe extraction outcome and chunk coverage. Do not
archive secrets or arbitrary raw provider payloads. This recommendation is
not implemented and does not authorize a paid rerun or broader planner design.

One documentation-only local commit:
`PRF-08R diagnose research discovery effectiveness`. No push.
