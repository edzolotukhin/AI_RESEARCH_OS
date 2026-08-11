# P1-12 — Official-Statistics-Aware Source Selection

**Date:** 2026-08-11
**HEAD base:** `9b472c1b39aeb9fd6e8a8cb4d7d65143fa5faff0`
**Branch:** `acceptance/live-desk-research-01`
**Verdict:** **PASS**
**Live Search / second organic acceptance / commit / push:** none

---

## A. Executive verdict

**PASS.** Bounded source selection now preferentially preserves topic-aligned official/primary statistical candidates under `SOURCE_MAX_SOURCES_PER_RUN=30` without raising budgets, without heat-pump special-casing, and without weakening Sufficiency.

Offline P1-10 replay moves DESNZ / GOV.UK BUS statistics / MCS dashboard from `skipped_budget` into the attempted set.

**LIVE RE-ACCEPTANCE: READY FOR SEPARATE AUTHORIZATION**

---

## B. Proven P1-11 defect

Search returned official aspect-bearing statistics URLs, but attempt ordering under the 30-source cap marked them `skipped_budget` while lower-authority blogs consumed earlier slots.

---

## C. Existing selection path

```
SearchQueryBuilder.build_queries
→ SourceAcquisitionService._collect_candidates (provider results, URL dedup)
→ _select_groups
     evaluate_candidate(RelevanceContext per IN, SourceCandidate)
     best decision per canonical URL
     sort via selection_sort_key
→ _acquire_candidates
     attempt in sorted order until max_sources_per_run
     remainder → action=skipped_budget / reason=source_attempt_cap
```

**Files:**
`application/sources/source_acquisition_service.py`
`application/sources/deterministic_source_relevance.py`
`application/sources/source_budget.py` (`max_sources_per_run`, default 30)

**Pre-fix ranking key:**
`(-tier_rank, -need_coverage, -topic_score, geo_penalty, provider_rank, url)`

**Metadata at rank time:** title, snippet, URL/host, provider rank, IN/RQ tokens, EE aspects/nature/geo/timeframe, preferred_source_types.

---

## D. Root implementation mechanism

Add **expectation-aware boost** for quantitative/mixed INs when a candidate is:

1. topic-aligned (`topic_score > 0`, not ineligible), and
2. shows structural authority (`.gov`/public-sector host patterns and/or stats path/workbook markers), and
3. shows statistics content/path signals.

Authority alone never boosts topic-mismatched pages.

---

## E. Design

| Signal | Role |
| --- | --- |
| EE `requires_quantitative_evidence` / nature quantitative\|mixed | Enables boost path |
| Topic score / eligibility | Gate — no topic ⇒ boost 0 |
| Structural authority score | Host/path patterns (not org whitelist) |
| Statistics signal | Lexical + path markers (`statistics`, `dashboard`, `/statistics`, `.xlsx`, …) |
| preferred_source_types | Mild assist for official/regulator wording |
| need_coverage | Retained for cross-IN fairness |

**New sort key:**
`(-expectation_boost, -tier_rank, -need_coverage, -topic_score, geo_penalty, provider_rank, url)`

Boost precedes tier so geography-DIRECT blogs cannot displace PROXY-but-official statistics solely via geo token overlap.

---

## F. Files changed

| File | Change |
| --- | --- |
| `application/sources/deterministic_source_relevance.py` | Context fields, boost scoring, sort key, decision diagnostics |
| `application/sources/source_acquisition_service.py` | Best-decision key; skip payload retains score fields |
| `tests/application/sources/test_p1_12_official_statistics_source_selection.py` | Offline cases A–G + P1-10 replay |
| `docs/acceptance/P1-12-Official-Statistics-Aware-Source-Selection.md` | This report |
| `artifacts/acceptance/p1_12_p10_candidate_replay.json` | Replay ranks |

---

## G. Ranking / selection semantics

Deterministic for identical inputs. No live provider calls in tests. No URL hard-coding in production. Cap unchanged at 30.

Decision dict now includes `expectation_boost`, `authority_score`, `statistics_signal` (also on `skipped_budget` rows when a prior decision exists).

---

## H. Cross-IN fairness

Retained existing `-need_coverage` and coverage early-stop. No new scheduler. Multi-IN offline case requires ≥3 INs represented in top-30.

---

## I. Offline defect reproduction

P1-10 attempt order (first 30 attempted; rest skipped):

| Candidate | Old index | Old status |
| --- | ---: | --- |
| DESNZ heat-pump deployment quarterly stats | 31 | skipped_budget |
| GOV.UK BUS statistics collection | 37 | skipped_budget |
| MCS data dashboard | 43 | skipped_budget |

---

## J. Offline fix acceptance

Cases A–G in `test_p1_12_official_statistics_source_selection.py`: **PASS**

- A official stats > blog
- B official irrelevant transport stats ≯ relevant vendor page
- C non-gov primary dashboard can boost
- D blog “statistics” ≯ official collection
- E multi-IN distribution
- F below-cap unchanged cardinality
- G deterministic

---

## K. P1-10 candidate replay

| Candidate | OLD | NEW |
| --- | --- | --- |
| DESNZ quarterly deployment xlsx | 31 / skipped_budget | **1 / selected** |
| GOV.UK BUS statistics | 37 / skipped_budget | **23 / selected** |
| MCS data dashboard | 43 / skipped_budget | **6 / selected** |

Replay uses fixture titles for skipped rows that lacked title metadata in `selection_decisions` (observability gap, not product hard-coding).

---

## L. Regression results

- `tests/application/sources` package: **OK** (81 tests)
- P1-07.14.1 eligibility + acquisition budget + profile design search semantics: **OK**
- No live Search executed

---

## M. Budget invariants

| Knob | Value |
| --- | --- |
| `SOURCE_MAX_SOURCES_PER_RUN` | **30 unchanged** |
| Evidence / global / remediation | **unchanged** |
| Planner cardinality | **unchanged** |
| Sufficiency | **unchanged** |

---

## N. Residual debt

- Planner max-IN / envelope contract
- `remediation_reserved=0`
- fetch timeout / unsupported xlsx-pdf ingestion
- extractor zero-candidate yield
- skipped_budget title/snippet observability
- Review resume counters

---

## O. Live acceptance recommendation

**LIVE RE-ACCEPTANCE: READY FOR SEPARATE AUTHORIZATION**

Offline property for the demonstrated P1-11 break is satisfied. A separately authorized organic Brief→READY live run is the correct next validation; not authorized inside P1-12.

---

## P. git diff --check

See command output in final response.

---

## Q. git status --short

See command output in final response.

---

**Implementation verdict: PASS**

**STOP.** No commit. No push. No live run. No P1-13.
