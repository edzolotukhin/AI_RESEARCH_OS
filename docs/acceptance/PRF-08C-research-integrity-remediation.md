# PRF-08C — Desk research-integrity remediation

## Scope and historical baseline

This is an offline remediation of the first and only PRF-08B live Desk run. No OpenAI or Tavily calls were made for PRF-08C; the historical workflow was not restarted, rescued, or edited. The frozen PRF-08A quality criteria remain unchanged. Initial branch: `acceptance/live-desk-research-01`; initial HEAD: `c30cb4a61425979586b2b2877d953c78d89f4b12` (5 ahead, 0 behind). The PRF-08B run remains `47ac7841-2c94-52a0-870c-6d3d468a6a16`, with its justified `insufficient_research` result.

The first run acquired 6 pages from 8 attempted URLs, extracted 13 Evidence items, and covered only IN1; the other five needs had no Evidence. It exposed three integrity risks despite correctly blocking report generation: an exclusion/ROI phrase contaminated provider search text, an August 2026 observation could be mistaken for evidence before the frozen 1 July 2026 observation cutoff, and a government report and a specialist page drawing on the same underlying feed were counted as two independent sources. Publication/retrieval dates and distinct domains did not establish observation eligibility or data independence.

## Root causes and remediation

1. **Query contamination.** The category-subject resolver could mine tokens preceding a word such as “market” from the free-form business question. In the frozen brief, that prose includes an exclusion of unsupported ROI/market-share claims. The prior resolver was reproduced offline with the synthetic frozen-brief shape and returned `presented observations unsupported roi` as a subject. The fallback was removed. Explicit market/category hints are bounded to five tokens; otherwise the resolver uses positive design/question context. ROI remains allowed when it is the legitimate subject, rather than being globally blacklisted. Query tests verify need/question binding and that a subsequent run does not inherit the first run's exclusions.
2. **Temporal eligibility.** Evidence had no grounded observation-period field and sufficiency could treat a page about an August observation as eligible merely because the source was acquired. The extractor now requests the observation period separately from publication date; persistence retains it only when the period is present in the grounded source excerpt. A dated frozen Brief supplies the observation cutoff from its observation clause, excluding a later source-availability clause. Month, day, quarter, year and ranges are parsed conservatively. Unknown periods, forecasts and periods extending past the cutoff remain stored as contextual evidence but do not qualify toward dated needs. The same filter is applied before readiness, targeted/terminal reconciliation, analysis, reporting and review. No historical Evidence is retroactively rewritten.
3. **False source independence.** The former deterministic signal counted distinct Source IDs. It now counts established underlying `data_origin_id` values, supported by a source-text attribution excerpt. Candidate metadata cannot self-certify `data_lineage`. Shared-origin documents count as one stream; unknown-origin documents contribute at most one provisional stream in aggregate and cannot corroborate an established stream. A warning exposes unknown lineage. The semantic assessor is instructed not to equate retrieval, publisher or document distinctness with need relevance or underlying independence. The sufficiency cache fingerprint includes observation period and lineage, with contract version `prf-08c.1`; a change to either invalidates the previous assessment.

No schema migration is needed: the grounded period and lineage are stored in existing Evidence JSONB metadata. The synthetic two-source harness now declares two actual distinct origins; it no longer relies on different URLs as proof of independence.

## Invariants and regression evidence

- A provider query is derived from positive brief/design context; exclusion prose cannot become its category subject. A genuine ROI research question still generates an ROI query.
- For the frozen dated Brief, an item qualifies only when its excerpt grounds an observation period no later than 1 July 2026. A later publication about 1 July may qualify; a publication containing end-August observations does not. Unknown dates do not silently pass the gate.
- Two documents using one established underlying feed count as one independent origin. Two unknown-origin documents do not satisfy a two-independent-source requirement. The requirement remains a deterministic gate even if a semantic assessment sounds confident.
- Insufficient need coverage still blocks analysis/report. The integrated PRF-08B failure-pattern test combines shared-feed July evidence, an excluded August item and missing IN2/IN3, and expects NOT_READY.
- Run-scoped source/evidence provenance and the original historical result are retained; no provider calls or production-data repairs were used to make tests pass.

The previously remaining standard-suite issues were diagnosed separately. The report-review test error was a **fixture/setup issue**: its mocked Brief had `timeframe=Mock`, incompatible with the new temporal guard's string contract. It now uses the real frozen `WorkflowTemplate.research_brief_snapshot`, preserving its original parse-failure diagnostic assertion. The sufficiency-fingerprint test failure was an **obsolete literal version expectation** after an intentional cache-integrity contract change. The assertion now expects `prf-08c.1`; an added test proves that changing only the period or lineage of an item with the same ID changes the fingerprint. Neither test was weakened to suppress a product failure. Both individual tests passed (1/1 each), followed by 163/163 focused offline tests.

| Check | Actual result |
| --- | --- |
| Canonical standard offline suite (`python run_tests.py`) | 2,835 run; OK; 144 skipped; 0 failures/errors. |
| Focused PRF-08C/query/lineage/sufficiency/review tests | 163 run; OK; 0 skipped. |
| PostgreSQL production-image suite, dedicated disposable database | 119 run; OK; 1 skipped. |
| PostgreSQL API integration | 48/48 passed. |
| Worker integration | 10/10 passed. |
| No paid provider calls | Confirmed; all remediation reproductions use offline/synthetic data. |

The PostgreSQL, API and worker results were obtained after the final product-code changes. Subsequent edits were only to the two diagnosed test expectations/fixtures and a fingerprint regression test, so they did not invalidate those integration results. A host-only PDF integration attempt lacked `reportlab`; the production image includes it and passed the relevant PostgreSQL suite. Two optional image-local PDF inspection tests lacked test-only `pypdf` in the production image. These dependency limitations are not counted as product test failures or as a passed optional inspection.

## Historical preservation and limitations

Fresh read-only verification at **2026-09-25 12:33 UTC** against the isolated `ai_research_os_prf08b-postgres-1` database confirmed the historical run `47ac7841-2c94-52a0-870c-6d3d468a6a16` still belongs to project `3cb532f7-1c76-469c-a023-6ba6607e23f8`, uses template `6153cbf5-de05-4f36-a1ac-30048d5184a5`, and is `completed` at version 12. The original three acquisition/extraction/readiness tasks remain completed; analysis, report writing and review remain skipped. The saved readiness state remains `research_outcome=insufficient_research`, `ready_for_analysis=false`, termination `evidence_remediation_budget_exhausted`, with IN1–IN6 and RQ1–RQ5 blocking. Its 13 Evidence rows all reference IN1. Findings, Insights, Reports, Reviews, PDF deliverables, presentation jobs and artifacts are all **0**, both for this run and in the isolated database overall.

The canonical Evidence checksum was recomputed with `md5(string_agg(row_to_json(e)::text, chr(10) ORDER BY e.id))` over the `evidence` table and is **`076646d8ec25f2a7d682ec420896af95`**, exactly matching the pre-remediation digest. The brief and original PRF-08B acceptance document were not rewritten. Only `SELECT` queries were used; the run was not rerun, recomputed, migrated, reseeded or repaired. No PRF-08C database write, live provider call or push was performed. Historical source payloads and untracked acceptance artifacts were not staged or modified.

This is a conservative gate, not proof that the next search will succeed. Explicit day-level cutoff enforcement applies where the frozen Brief has a parseable day; looser or ambiguous timeframes require review rather than an invented exact cutoff. The source-text grounding check confirms attribution text exists, not that the named provider is empirically independent; unknown lineage can withhold readiness. Mixed passages and forecasts require careful downstream review. Existing bounded search, source-selection and provider-call budgets remain; PRF-08C does not guarantee sufficient relevant sources, complete temporal metadata from the extractor, provider availability, a green live rerun, or exact provider cost.

## PRF-08D readiness

The offline integrity gates, affected integration checks and historical preservation check pass. PRF-08C is ready to be committed locally. After this checkpoint, PRF-08D may be planned as **one separately authorized controlled live rerun** with its own baseline, preflight and operational spending limits. It has **not** been executed here. PRF-08C offline fixture success does not prove live research success or relax PRF-08A acceptance quality.
