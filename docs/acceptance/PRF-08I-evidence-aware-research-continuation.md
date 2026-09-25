# PRF-08I — Evidence-aware research continuation

## Baseline and scope

Baseline: `5697e16a8d806adcc4a22565a78b21b19ffdac4a`, branch `acceptance/live-desk-research-01`. This remediation is offline only. No new live research run, OpenAI/Tavily call, historical-result recomputation, or push was performed.

## PRF-08H root cause

PRF-08H run `027af6f6-08d2-57dd-b9bf-42701dee261b` recorded 12 searches, 6 acquisition attempts, 5 acquired pages, 24 raw Evidence, and 13 qualifying Evidence. Three required Information Needs had zero Evidence; readiness remained false. The acquisition phase's `coverage_complete_early_stop` used acquired source-to-IN references, not extracted and qualifying Evidence. This is a source-acquisition bound, not proof of research completeness. Extraction then consumed the whole eight-call Evidence allowance. The default remediation reserve was zero whenever `EVIDENCE_MAX_LLM_CALLS` differed from 50. The post-extraction readiness loop detected insufficiency but had no Evidence-call capacity for targeted continuation, so it stopped with `evidence_remediation_budget_exhausted` and no continuation attempt. Formal source coverage therefore became effectively terminal despite missing Evidence.

## New semantics

The source-acquisition early stop remains a bounded first-pass decision; it is not treated as the final research-completeness decision. After extraction and qualification, the research loop refreshes run-scoped raw and qualifying Evidence before scheduling each bounded gap attempt. Actionable needs are prioritized within the existing first-opportunity/fairness cohort: zero raw Evidence, raw Evidence but zero qualifying Evidence, then qualifying Evidence below sufficiency. Sufficient needs are excluded by the existing gap selector. Source and candidate references never substitute for Evidence. Temporal and lineage qualification still use the established qualifier; no thresholds are relaxed. Repeated failed gap attempts remain subject to existing per-gap and per-round limits, allowing a bounded alternative to receive a turn.

For an eight-call Evidence profile, the initial pass now receives six calls and two are reserved for targeted remediation. The default per-targeted-attempt cap is one call in low-cap profiles, distributing the reserve across gaps. Total Evidence allowance remains eight. The stock 50-call profile retains its six-call reserve and prior per-attempt default. Other explicit configured limits and overrides remain authoritative. If there is no remaining bounded capacity or no qualifying improvement, the loop stops conservatively with insufficient research; it does not manufacture readiness or a report. The change does not enlarge the total Evidence-call envelope, although within already configured search, acquisition, iteration, and worker limits it can use remaining targeted-research capacity that PRF-08H did not use. With PRF-08H's one round and one attempt per gap, at most six required INs can receive one targeted attempt each, while the eight-call Evidence ceiling remains unchanged.

## Deterministic verification

- New PRF-08I fixture reproduces formal source coverage for all required INs with several having no Evidence; the loop performs only the two reserved targeted Evidence attempts and does not report ready without qualifying Evidence.
- Separate tests cover zero Evidence, post-cutoff/nonqualifying Evidence, qualifying-but-insufficient Evidence, sufficient needs excluded from scheduling, bounded alternative after a failed attempt, exhausted budget, and a genuinely Evidence-supported ready result.
- Existing bounded-remediation and fairness contracts remained green. The canonical offline suite completed: **2862 tests, 145 skipped, 0 failures/errors**. PostgreSQL integration tests in that suite were skipped because disposable PostgreSQL test flags/database were not configured. No persistence schema, repository, API contract, or worker transaction code changed; those integration gates were not rerun against a disposable PostgreSQL database.
- `git diff --check` reported no whitespace errors.

## Historical integrity and limitations

The prior PRF-08B, PRF-08D, PRF-08F, and PRF-08H acceptance records remain present and were not edited. After Docker recovery, both `desktop-linux` and `default` contexts exposed the original four healthy PRF-08 PostgreSQL containers and their separate volumes. Fresh read-only `SELECT` queries against each original database used the canonical `md5(string_agg(row_to_json(e)::text, chr(10) ORDER BY e.id))` method, scoped to the recorded run ID:

| Run | Evidence count | Fresh checksum | Previously recorded | Result |
| --- | ---: | --- | --- | --- |
| PRF-08B `47ac7841-2c94-52a0-870c-6d3d468a6a16` | 13 | `076646d8ec25f2a7d682ec420896af95` | Same | PASS |
| PRF-08D `245281e2-c401-5ce8-9e0a-1c69b130d762` | 33 | `84ce68280d94941b19414a46893f2868` | Same | PASS |
| PRF-08F `8b587f8b-43f0-5e2c-85b5-83c7792e37a9` | 22 | `7937d0745c8c03a67ffc045c9fbbb6f5` | Same | PASS |
| PRF-08H `027af6f6-08d2-57dd-b9bf-42701dee261b` | 24 | `3866b66b19d3ec31ff6210fafa297922` | Same | PASS |

All four workflow rows still have their recorded IDs and `completed` status. PRF-08D's full workflow-row fingerprint, `md5(row_to_json(w)::text)`, remains `01e242df696ac51050788442c6249471`, matching the earlier PRF-08E/08G record. Only read-only queries and Docker inventory commands were used. No historical run was rerun, recomputed, migrated, reseeded, repaired or otherwise mutated.

Live effectiveness and cost are **NOT VERIFIED**. A future single bounded live rerun requires a current-code isolated environment, owner authorization, and fresh historical integrity verification when the original database context is accessible. This record does not rewrite PRF-08H's refusal or assert that PRF-08I has produced a report.
