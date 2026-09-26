# PRF-08W — Temporal semantics and Evidence relevance integrity

## Baseline and scope

Branch `acceptance/live-desk-research-01`; initial HEAD
`c503e5844e05777fcbdf69fef927a77129cb9784`, recorded upstream ahead 25 / behind 0.
Tracked/index initially clean; pre-existing untracked acceptance artifacts preserved.
Offline only: no OpenAI/Tavily calls, no live run, no push. No search/orchestration,
budget, retry, source selection, lineage or content-dedup changes. No migration.

## Proven mechanisms in PRF-08V

The existing temporal parser recognized `Q1 2026` but not `first quarter of 2026`.
It therefore read the latter as the entire year ending 31 December 2026 and
rejected Evidence `b1cf4b52-857c-441f-976c-0636826fe463` against 1 July 2026.
The same evaluator compared only the latest observation date to the cutoff:
Evidence `7e50448d-9d8c-44b7-8aa6-9ae9b4cfff7d` with observation metadata `2024`
passed despite the frozen boundary starting 1 January 2025.

Five digital-gold statements were grounded in their source but not in the subject
of IN6. Source discovery linkage and extraction-provided valid IN IDs passed
`validate_candidate_provenance`; an exact quote then passed grounding. Neither
checked subject continuity. Generic definitions/comparability language was
mistaken for the intended need. These facts did not pass V's temporal filter,
but could already inflate raw stored coverage and productive-yield counts.

## Temporal semantics

`observation_interval` accepts a complete supported period or explicit range:
ISO/existing named-month exact dates, named month/year, calendar quarters
`Q1 2026`, `2026 Q1`, `first quarter [of] 2026` (likewise second/third/fourth),
and explicit years. Dates are validated; invalid exact dates cannot silently
degrade to a valid month/year. Quarter endpoints use actual calendar days.
Range endpoints retain order, including mixed precision; reversed/ambiguous or
arbitrary-prose expressions remain unknown. No fiscal-quarter inference.

Grounding checks the original metadata expression in the canonical excerpt
before normalization. Publication-only occurrences are not observation authority.
No arbitrary date is mined from surrounding prose. Existing conservative,
matching claim/excerpt as-of fallback and static-methodology exception remain.

The brief's first observation clause supplies a full interval when expressible
in that supported grammar; the publication-availability clause is excluded.
Qualification requires containment of the **whole observation interval** within
both boundaries. Thus 2024 fails for the frozen case, Q1 2026 succeeds, Q3 2026
fails, and year 2026 cannot partially qualify against July. A year-only brief is
now itself bounded, not automatically undated. Unsupported narrative brief forms
retain the established exact-day-cutoff compatibility path; this is not a general
natural-language temporal parser. No historical rows or metadata are rewritten.

## Earliest generic relevance boundary

The authoritative candidate-to-Evidence provenance boundary now validates each
proposed IN independently before deduplication/persistence. For explicitly
expected needs it derives subject tokens from IN description, narrowing them
with related RQ overlap where available, excluding geography/time and generic
research/method/aspect language. Both claim and excerpt must retain subject
support. Source titles, URLs and self-declared metadata cannot certify relevance.

Unrelated refs are removed; valid other-IN refs survive and RQ refs are rebuilt
from those INs. An entirely unsupported candidate raises a provenance-boundary
rejection classified `relevance`; no row, coverage increment or produced-Evidence
event is created. Existing aggregate provenance rejection counters remain
compatible, with the more precise reason in candidate diagnostics.

No topic/domain allowlist or literal digital-gold/EV exception exists. Fixtures
use water meters, pumps and collectible certificates. Existing ID and grounding
validation still apply. The guard is a deterministic negative subject-continuity
check, **not** a general semantic proof: synonyms, implicit subjects/table-only
excerpts may be rejected conservatively; overlapping topical words are not proof
of complete metric/geographic entailment. Legacy needs without explicit
expectations and genuinely generic descriptions retain compatibility behavior;
absence of structured subject information is not invented negative evidence.
This limitation is explicit, not a claim to reject every conceivable unrelated
sentence across all legacy designs.

## Regressions and validation sequence

New module `tests.application.test_prf08w_temporal_relevance`: **24 passed**.
It covers pre-window years, quarter forms and containment, post-cutoff quarters,
whole-year overlap, publication-only data, arbitrary/unknown prose, exact/month
dates, invalid dates, reversed/mixed ranges, year-only brief, target/cross-IN
retention, wrong-ref removal, generic research wording, unrelated-topic rejection,
self-certification/claim laundering rejection, no persistence/readiness contribution,
and telemetry on/off equivalence. Existing U/S/K/P tests preserve 6+2, lineage,
content dedup, valid-empty behavior and query intent.

- Initial W/U/S/K/P selection: **84 passed** (then 23 new W tests).
- Initial evidence/readiness suites: **153 / 477 passed**.
- Canonical `python run_tests.py`: **invoked exactly once**, 2950 run,
  **2798 passed, 149 skipped, 3 errors**, 162.137 seconds. This was not green.
- Direct isolation identified the three errors in:
  `ResearchEndpointTests.test_production_mode_completes_desk_research_pipeline`,
  `EvidenceApiTests.test_owner_can_list_and_get_evidence_after_extraction`, and
  `SourceApiTests.test_owner_can_list_and_get_sources_after_search`.
- Generic `Desk research sources relevant to the linked objective` was wrongly
  treated as a subject. Added domain-neutral task words to the exclusion set;
  an explicit new regression now covers this. No valid expectation weakened.
- The remaining pipeline fixture then reached a legitimate temporal refusal:
  its undated generic smoke excerpt could no longer satisfy a year-only brief.
  Only that test now injects a synthetic dated retriever/extractor through existing
  overrides. Date appears in actual source text/excerpt and metadata. Assertions
  still require analysis/report/review/artifact completion; no gate is mocked out.
- Corrected API evidence/source/workflow + W/U/S/K/P selection: **99 passed**.
- After the final product correction, evidence **153 passed**, research-quality
  **477 passed**, final new W module **24 passed**.

The sole full-suite result is retained honestly; the three errors were resolved
and verified in their affected tests. No second full run is claimed or performed,
honoring the exactly-once instruction. Final broad evidence is that full run plus
the corrected affected selections, not a freshly green full-suite run.

## Affected PostgreSQL/API-worker checks

Temporary internal network `ai_research_os_prf08w_test`, tmpfs PostgreSQL instance
`ai_research_os_prf08w_test_postgres`, DB/user `prf08w_test` / `prf08w`. No host
port, production volume or provider credentials. Existing migrations through
`016_prf06f_pptx` applied only to this disposable DB; no schema change introduced.

Initial bind-mounted test clients failed during import with OS error 12
(`Cannot allocate memory`), before tests executed. A network-disabled standard
image rebuild could not install npm dependencies. Neither is counted as passed.
Recovered without restarting any historical service: offline overlay FROM the
existing production-compatible PRF-08V image, COPY current application/tests,
no dependency downloads or problematic runtime mounts.

The recovered pre-final selection passed **45 tests, zero skips** (22 affected
PG/API-worker tests plus then-23 W tests). Final rebuilt-image selection:
**46 passed, zero skips/errors/failures**, 3.554 seconds (22 affected checks plus
24 W tests), image config `0432d44134d7cd94b56027deffe08f1278ed67f24c6fb2fc2f2392fbb93bcbb2`.
Modules: PG `test_prf08s_funnel_telemetry`, `test_prf08p_content_identity`,
`test_prf08k_lineage_identity`, `test_prf08c_evidence_integrity`,
`test_source_provenance_concurrency`, `test_research_loop_progress_checkpoint_recovery`,
`test_worker_execution`, `test_worker_api_claim_integration`; application
worker execution/loop isolation/defaults, and the new W module.

## Historical integrity

Original databases read only using `BEGIN READ ONLY`; ordered Evidence row MD5
and workflow-row MD5. No new evaluator applied to history. B/D/F/H/J/O/T counts
and both fingerprints match previous records; V count/Evidence MD5 matches its
accepted record. V workflow MD5 is a fresh baseline, not a fabricated prior value.

| History | Evidence | Evidence MD5 | Workflow MD5 |
| --- | ---: | --- | --- |
| B | 13 | 076646d8ec25f2a7d682ec420896af95 | 00ef1aa66c3b6194ba39d1a01c066de7 |
| D | 33 | 84ce68280d94941b19414a46893f2868 | 01e242df696ac51050788442c6249471 |
| F | 22 | 7937d0745c8c03a67ffc045c9fbbb6f5 | 3eedf9afcfbd4b61b1eaa672bc36f3f8 |
| H | 24 | 3866b66b19d3ec31ff6210fafa297922 | 60fd6bb7a92d1c36f0bb04073d567e47 |
| J | 27 | 299e88abe27b9363fd623f5f9e034eac | 2e66c4ab0dbf4365877c97e61e053576 |
| O | 1 | 135c9ec526cdd2672bd61b52e7902f7d | 9dcb9c3b7526dd0eeb2a625876460c28 |
| T | 5 | 3c15be644e3a45f47955bc1da2bfd412 | eab5db1fd4860e5011a91c6fefed1e53 |
| V | 21 | 7f9ca2da74d75c5bae0107a425108309 | 0efe638f7ce58baa6dc785d499f340ce |

All workflow statuses remain completed. Their stored refusals and live acceptance
records were not changed. The new policy is applied only by future execution;
there is no migration/backfill or historical repair.

## Bounds, delivery and live limitations

No LLM/search/acquisition/extraction/retry limit changed; 6 initial + 2 continuation
remains 8. New guards perform no calls. PRF-08S on/off is observationally identical.
No offline suite or integration selection uses paid providers. Current live
acceptance containers are not upgraded by this task. Live yield, multilingual
semantic coverage and final Desk/report/PDF/PPTX success remain NOT VERIFIED.

Reviewed scope: temporal parser/filter, pre-persistence relevance helper/hook,
diagnostic reason, new deterministic regressions, one explicitly dated API smoke
fixture, this report. No credentials/env files/runtime dumps/historical payloads
in the intended commit. Existing artifacts preserved. No push.
