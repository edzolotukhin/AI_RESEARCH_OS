# PRF-08B — controlled live Desk acceptance record

**Preflight decision: GO at 2026-09-25 07:56 UTC, before the first paid call.** All mandatory gates below are PASS under the owner's operational-budget clarification; provider validity will be tested by the first controlled operation, not a separate speculative ping.

At the preflight GO decision, no paid call had yet occurred. This record applies the frozen [PRF-08A contract](PRF-08A-live-research-acceptance-spec.md), SHA-256 `B3F32B438716B76E76D8BA13A412FC1B4F65C98AAADDF4562E17E46FBFECD5C6`. Owner clarified that USD 5.00 is an operational ceiling, not a requirement for a provider-side monetary cutoff. Approximate USD 7 balance is not permission to spend more than USD 5; preserve approximately USD 2.

## Baseline and environment

- Initial Git: `acceptance/live-desk-research-01` at `200e69110daac69c0e3bfced6606ebc97e982257`, origin divergence 0 behind / 4 ahead; tracked/index clean. Existing untracked acceptance artifacts were not moved or edited.
- Dedicated Compose project `ai_research_os_prf08b`, image `sha256:321fe762bb2164899628745aa619ae4e4626f07dc88a118f53ddeedf0607bb97` built from current source (not an older prebuilt image), network `ai_research_os_prf08b_acceptance`, PostgreSQL volume `ai_research_os_prf08b_postgres_data`, protected-data volume `ai_research_os_prf08b_protected_data`. API bound only to `127.0.0.1:18081`; PostgreSQL has **no host binding**. The existing port-8000, n8n and PRF-07B containers/volumes were not changed.
- Isolated database `prf08b_acceptance`, migration head `016_prf06f_pptx`; `/ready` and authenticated project/design HTML returned 200; PostgreSQL/API/worker Docker healthchecks healthy. Worker has `restart=no` to prevent automatic replay after a crash. Isolated local owner registered through the existing authentication service; credentials are not included here.
- Isolated API and worker each report required OpenAI/search credentials *configured* (presence only), `gpt-5`, Tavily, live/non-deterministic stage wiring, and PRF-08B database URL category. Credential validity/connectivity is not proven by a paid test; the first authorized provider operation will test it.

## Frozen brief and persisted snapshot

Project `3cb532f7-1c76-469c-a023-6ba6607e23f8`, `PRF-08B — UK public rapid charging, controlled live acceptance`, created via product `/ui/projects` with DESK selected. Brief submitted via product `/ui/projects/{id}/brief` and read back from the isolated database; PostgreSQL `md5(brief::text)` is `7262e5080260e56109b7e95431ec481c` before design generation. Five objective records, language `en`, geography `United Kingdom`; no design or workflow run yet.

- **Title:** `UK public rapid EV charging: retail-site opportunity evidence review, 2025–July 2026`.
- **Decision question:** For a mid-sized UK retail-property operator considering further due diligence, establish what public sources support about the scale and change of the public 50 kW+ network, regional/site-type distribution, observable use and operator presence through 1 July 2026; identify unsupported or definition-dependent commercial questions. No investment recommendation or profitability assertion.
- **Objectives:** compare documented 2025 versus latest eligible 2026 cut-offs with the same metric/definition; describe comparable regional and retail/destination/en-route distribution; use dated primary operator disclosures without treating announcements as current verified inventory; distinguish use from installed capacity and disclose gaps/contradictions/dependencies; deliver a cited limited Desk report, not a forecast. The UI parser splits objectives on commas as well as newlines, so punctuation was normalized to retain five intact objectives. This is a form-format adjustment, not a changed research requirement.
- **Geography:** United Kingdom; do not silently equate Great Britain or England with UK. **Observation period:** 1 January 2025–1 July 2026; sources available by 25 September 2026. Later publications qualify only if they clearly report the fixed observation period.
- **Category:** publicly accessible EV chargers rated at least 50 kW at retail, destination or en-route sites; all-public-charger totals only as context.
- **Inclusions:** installed public 50 kW+ chargers; dated regional/site-type counts with definitions; dated primary operator disclosures labelled as such; utilization evidence only with method/scope.
- **Exclusions:** private/home/workplace-only charging, connectors mislabelled as chargers, 2027 forecasts as 2026 observations, unsupported ROI/market-share estimates, anecdote-to-population claims, investment advice.
- **Ambiguities:** charger/device/connector/site, cut-off/feed differences and DfT–Zapmap underlying-data dependence.
- **Output:** cited saved Desk report with limitations and site-due-diligence implications; PDF/PPTX only after evidence/review gate. The project UI has no separate exclusions/deliverables inputs; these requirements were explicitly included in the supported business-question field, rather than falsely claiming that canonical `exclusions`/`deliverables` tuples were populated. Read-back verified the phrases and the five objectives; owner can review them in the UI.

## Preflight gate record

| Mandatory gate | Verdict / evidence |
| --- | --- |
| Repository baseline and frozen PRF-08A contract | PASS — SHA, branch, clean tracked/index and document checksum recorded above. |
| Isolated environment and database | PASS — dedicated Compose project/network/volumes, no PostgreSQL host port, no shared PRF-07B/default volume. |
| API, worker and migrations | PASS — healthy and ready; migration `016_prf06f_pptx`. |
| Credentials and provider configuration | PASS for safe presence in both new processes and complete live config; provider validity deferred to first authorized call, without a speculative paid ping. No secret values exposed. |
| Provenance | PASS from implementation: report sections retain finding/insight/evidence refs; Evidence retains source ID/checksum; citation registry maps citation IDs to original Source URL. Actual live chain to be audited later. |
| Observability | PASS to implemented boundary: task/run timestamps, task results, logical LLM/search counts, acquired sources, output/reasoning tokens where returned, worker/job and report/artifact times. Input tokens, SDK-internal retries and exact charges remain UNAVAILABLE; no false zeros. |
| Persisted frozen brief / project | PASS — project ID, selected DESK, field read-back and checksum above; material limitations retained in a supported field. |
| Design-gating readiness | PASS — product design page accessible, current design absent, approval required before activation. Generated design and ID to be checked after the first paid call; any material loss stops activation. |
| Owner budget | PASS — USD 5.00 operational maximum, not a target; provider-side hard monetary cap NOT AVAILABLE. |
| Operational cost controls | PASS — 19 stage-capped run calls plus at most 3 planner attempts, six-IN search envelope, bounded research rounds, source/time limits, no worker auto-restart and the conservative estimate/stop rule below. SDK internal retries and input-token visibility remain disclosed uncertainties, not a monetary hard cap. |

## Operational cost envelope — preregistered before provider call

Configured worker: `gpt-5`, maximum 24 run logical calls, stage caps Evidence 8 / Sufficiency 6 / Analysis 2 / Report 2 / Review 1 (sum **19**); planner up to 3 structured-output attempts before the run budget. Up to six information needs, at most two initial query arms per need and one targeted attempt/query per gap in one gap round imply approximately **18** planned maximum Tavily search operations for six distinct gaps (subject to inspect actual dispatch). Search results/query 3; acquired sources/run 8; source-acquisition wall limit 300 s; automatic report review/revision remains the accepted product behavior. Worker is single-instance and will not auto-restart after a crash. SDK transport retry defaults remain an uncertainty; they are not counted as free and errors trigger a stop/reassessment.

For a deliberately high practical planning allowance of **60,000 input tokens per logical call** across 22 possible planner + run calls and **8,192 output tokens per call**, the envelope at published `gpt-5` rates ($1.25/1M input; $10/1M output) is `$1.65 input + $1.80224 output = $3.45224`. At Tavily pay-as-you-go $0.008/credit and basic search 1 credit/query, 18 queries add `$0.144`, making **$3.59624**, before uncertain SDK retries. A 25% contingency gives **$4.49530**. This is a conservative *practical estimate*, **not** a mathematical worst-case or actual billed charge. It preserves ~$0.50 below USD 5 in this scenario. Sources: OpenAI `https://developers.openai.com/api/docs/models/gpt-5`; Tavily `https://www.tavily.com/pricing` and `https://help.tavily.com/articles/6938147944-basic-vs-advanced-search-what-s-the-difference` (checked 2026-09-25). Actual Tavily plan/credits and charges are not verified by this estimate.

**Operational stop rule:** after the synchronous design call, assess returned outcome and application-visible usage before approval; stop before activation if estimated committed+remaining envelope cannot fit USD 5. During the worker run, monitor persisted stage/usage/failure state frequently; if the conservative running estimate (60k input per observed logical call plus returned/max output as appropriate, all observed search calls and 25% contingency) approaches USD 5 or retries/large prompts invalidate the 60k assumption, stop only this disposable worker and preserve the run. Do not restart it to improve an unsatisfactory outcome. Exact billing remains UNAVAILABLE unless separately verified from provider statements; never report the estimate as actual cost.

## Live acceptance observations

**Design generation:** product UI POST began `2026-09-25T07:58:00Z` and returned at `07:58:38Z` (38 s including HTTP/redirect). This was the first paid-capable operation; provider billing and exact tokens are UNAVAILABLE. One successful generated design is persisted as DRAFT, ID `42228fb0-b8bf-4371-8f4c-12cd608c5c9d`, input fingerprint `0bea46d612195b847247156b9f7aacaeb90160439faee48423225de26fb1e2d4`. It has 5 research questions / 6 information needs. RQ1 scale/change, RQ2 region/site type, RQ3 operator disclosures, RQ4 use versus capacity, RQ5 unsupported questions; IN1/2 national counts and comparison, IN3 regional/site type, IN4 operators, IN5 utilization, IN6 gaps/dependencies. Source strategy prioritizes definition-preserving official/primary material. Assumptions explicitly exclude private charging and connector-count confusion; publication/observation cut-offs and announcement-vs-inventory status are retained. No material frozen constraint was lost; design gate **PASS**. No manual edit or second generation occurred.

**Post-design budget recheck:** one successful planner-generation UI operation observed; application does not persist planner input/output token usage, so charge is UNAVAILABLE. Conservatively retain the preflight allocation for *three* planner attempts in the envelope rather than crediting unused attempts as spendable. Remaining modeled run and search still fit the USD 5 operational estimate with contingency. An internal SDK transport retry cannot be ruled out, so later monitoring must preserve that uncertainty.

The subsequent single workflow run and all observed downstream outcomes are recorded below. Preserve the first result even if it fails PRF-08A.

## First and only live run — observed result

Approved generated design `42228fb0-b8bf-4371-8f4c-12cd608c5c9d` through the product UI at `2026-09-25T08:00:07Z`; frozen brief checksum remained `7262e5080260e56109b7e95431ec481c`. Activated DESK once through the product UI at `08:01:46Z`, creating run `47ac7841-2c94-52a0-870c-6d3d468a6a16`. The separate worker claimed it. Durable workflow was created `08:01:47.991Z`, started `08:01:51.124Z` and reached status `completed` at `08:03:21.416Z` with **research outcome `insufficient_research` / `ready_for_analysis=false`**, not an approved research result. Collect Sources, Extract Evidence and Assess Research Readiness completed. Analyze Findings, Write Research Report and Review Research Report were **skipped**. Findings 0, insights 0, reports 0, review results 0; no PDF/PPTX request was made. The first outcome was not modified, rescued or restarted.

### Search and source ledger

The Source Acquisition task reports **12 Tavily calls**, six baseline and six localized, 26 raw candidate results, 24 unique URLs, 8 attempted URLs (the configured cap), 6 acquired pages, 2 HTTP errors, 16 unique candidates not attempted due to cap, no truncations, 50.351 s elapsed and acquisition coverage only **3 of 6** information needs. It records uncovered IN3 (region/site type), IN4 (operator) and IN6 (gaps). The 12-call count is an application logical count, not a provider invoice. Only result-producing source metadata preserves actual query text; zero-result arm text remains NOT VERIFIED.

Observed query text for IN1 baseline/localized began `presented observations unsupported roi United Kingdom` before the 50 kW+ count description. IN2 and IN5 result-producing queries shared that **irrelevant ROI preamble** before their distinct need descriptions. This appears to have been drawn from brief exclusion wording, but the implementation cause is not proven by this run alone. The six design IN intents were distinct; their executed query phrasing was not cleanly topic-bound. Do not rewrite the queries retrospectively.

| Source ID prefix / assigned IN | URL / retrieval | Acceptance classification |
| --- | --- | --- |
| `387b5cd7` / IN5 | `https://www.cncoptimization.com/calculators/roi-capacity` / acquired | Laser/CNC ROI, irrelevant to UK EV use. |
| `77da2539` / IN2 | `https://thebetatheory.co.uk/blog/how-to-measure-b2b-marketing-success-2026` / acquired | B2B marketing ROI, irrelevant to charger change. |
| `a8783e15` / IN5 | LinkedIn EVgo Q3 earnings post / acquired | Unverified UK scope and utilization; not suitable evidence for this brief. |
| `f5e1a18a` / IN2 | Forbes AI ROI article / HTTP failed | Irrelevant candidate even if fetched. |
| `2d17589c` / IN2 | Sender marketing ROI statistics / acquired | Irrelevant. Selection decision labelled it `selected` with `no_positive_topic_signal_unscored` and topic score 0. |
| `68729600` / IN1 | `https://www.zapmap.com/ev-stats/ev-charging-statistics` / acquired | Relevant category/definitions but page updated Sep 2026 and includes **end-August 2026 observations**, outside frozen observation cutoff. Underlying Zapmap feed also supplies DfT. |
| `217adc76` / IN1 | EVCandi UK charger news / HTTP failed | Retrieval failed; no evidence. |
| `cac0defd` / IN1 | `https://www.gov.uk/government/statistics/electric-vehicle-charging-infrastructure-statistics-1-july-2026/public-electric-vehicle-charging-infrastructure-statistics-1-july-2026` / acquired | Official publication dated 27 Aug 2026 reporting 1 Jul 2026: eligible observation period. DfT explicitly says CPO data are collated by Zapmap. |

The official [DfT source](https://www.gov.uk/government/statistics/electric-vehicle-charging-infrastructure-statistics-1-july-2026/public-electric-vehicle-charging-infrastructure-statistics-1-july-2026) and [Zapmap page](https://www.zapmap.com/ev-stats/ev-charging-statistics) were opened at the original publishers after the run. They are **derivative/shared-feed**, not two independent measurements of the same national statistic. Yet IN1's saved readiness assessment recorded `independent_source_count=2`, a false-diversity signal. Source record `published_at` was NULL for all eight attempted URLs, so reliable freshness requires reading the page/claim text. No independent study/source was observed for a central national comparison. This run does not establish whether all 24 unique candidates were relevant; 16 were not fetched.

### Evidence and sufficiency

Evidence extraction used its full **8 logical LLM calls**, processed 6 acquired sources and 8 of 19 planned work items, yielded 13 persisted Evidence records, all attached to **IN1** and the DfT/Zapmap pages. Six calls returned valid empty results; two returned candidates; two candidates were rejected by excerpt grounding. No evidence was persisted for IN2–IN6. Stage reported `evidence_max_llm_calls`, 11 skipped work items, 4 sources without evidence and no remediation reserve (`0`). Source-to-evidence IDs and checksums are durable. Three spot checks against the opened originals: DfT's 1 July 2026 50 kW+ count is present and in-period; the DfT passage explicitly identifies Zapmap/CPO provenance; Zapmap's 24% power-band statement appears on a page dominated by end-August 2026 figures. This is not a complete report-claim audit; no report exists.

The stored readiness assessment marked IN1 **partial** (site/location definition missing despite 13 items) and IN2–IN6 **missing** (0 Evidence each). All five RQs were blocked. System and reviewer both judge **NOT_READY justified**; the product appropriately withheld analysis/report rather than fabricating an answer. However, the saved IN1 assessment called the two shared-feed pages independent, and persisted Zapmap Evidence includes statements expressly about end-August 2026 (for example IDs `65cc89de`, `ae9a1f5b`) despite the fixed 1 July cutoff. Neither reached a report, but both are research-integrity near misses. The reported termination `evidence_remediation_budget_exhausted` is consistent with zero reserve at the deliberately bounded eight-call Evidence cap, but obscures the separate search-selection relevance failure; both factors must be retained.

### Timing, usage, failure and cost

| Operation | Observed UTC / duration | Metering |
| --- | --- | --- |
| Design generation | 07:58:00–07:58:38, 38 s UI wall | One successful design; exact planner attempts/tokens UNAVAILABLE. |
| Design approval / activation | 08:00:07 / 08:01:46 | Human/operator wait separated from worker time. |
| Worker start to terminal | 08:01:51.124–08:03:21.416, ~90.3 s | Durable execution log. |
| Source task | 08:01:51.296–08:02:43.613, ~52.3 s | 12 search calls; 8 attempted HTTP URLs, 2 HTTP errors. |
| Evidence task | 08:02:43.656–08:03:16.616, ~33.0 s | 8 logical OpenAI calls, 2,130 returned output tokens; 32,748 ms summed provider-call time. |
| Readiness task | 08:03:16.655–08:03:21.388, ~4.7 s | 1 logical OpenAI call, 187 returned output tokens; 4,644 ms provider-call time. |

Run usage summary: **9 logical LLM calls**, 2,317 returned output tokens, 0 app-level retries, 37,392 ms summed provider-call time; `input_tokens=0` is **UNAVAILABLE**, not zero use; `estimated_cost_usd=null`. Planner usage is separate/unavailable. SDK-internal retries and actual provider charges are UNAVAILABLE. Search count 12; Tavily plan/free-credit treatment unknown.

At the preregistered conservative 60,000 input-token allowance per observed logical call, assuming **1–3** planner attempts (10–12 total LLM calls), max 8,192 output tokens per unknown planner attempt, observed 2,317 run output tokens and 12 basic Tavily credits at $0.008: approximate **$0.95–$1.27**, or **$1.19–$1.59 with 25% contingency**. This is an **ESTIMATE**, not actual spend; true input tokens, planner output and internal retries are not independently measured. It is below the owner operational USD 5 ceiling under the stated conservative assumptions. No additional paid operation is planned after this terminal NOT_READY result.

Failure ledger: two source HTTP fetch failures; 16 candidate URLs unattempted because of source cap; four acquired pages without Evidence; six valid-empty extraction calls; two grounding rejections; Evidence cap exhausted; five INs missing; search-query contamination and unrelated selected/acquired sources. No OpenAI/Tavily provider failure was observed. Internal transport retries remain NOT VERIFIED. The safety gate recovered by refusing downstream synthesis; research coverage did not recover. No second run or bounded repeatability search was authorized/executed after the failed first result; repeatability **NOT VERIFIED**.

### Acceptance matrix and defects

| Dimension | Verdict and reason |
| --- | --- |
| Pipeline completion | FAIL — technical status completed, but no Analysis/Report/Review. Correct NOT_READY refusal is a safety success, not a full vertical pass. |
| Research design | PASS — five aligned RQs, six bounded INs, scope/exclusions/uncertainty retained. |
| Search quality | FAIL — observed ROI query contamination; irrelevant domains selected for IN2/IN5; 12 calls did not yield material coverage. |
| Source quality | FAIL — four of six acquired pages are irrelevant or unverified UK applicability; only DfT and Zapmap materially relevant to IN1. |
| Source independence | FAIL — shared-feed DfT/Zapmap were counted as `independent_source_count=2` for IN1. |
| Evidence grounding | NOT VERIFIED end-to-end (no report); source/excerpt mechanical checks worked on sampled items, with two bad excerpts rejected. |
| Citation integrity | NOT VERIFIED — no report or citations. |
| Scope fidelity | FAIL at Evidence stage — end-Aug 2026 facts were persisted under a 1 Jul 2026 observation cutoff; no final-report scope was tested. |
| Contradiction handling | NOT VERIFIED — no report/credible comparable conflict tested; do not manufacture one. |
| Sufficiency | PASS for safe refusal; FAIL for achieving adequate coverage/vertical acceptance. Reviewer agrees with NOT_READY. |
| Unsupported-claim discipline | NOT VERIFIED downstream; refusal prevented unsupported final claims. |
| Findings/insights | NOT VERIFIED — correctly skipped. |
| Final-report usefulness | NOT VERIFIED — no report. |
| Provenance | PASS for persisted Source→Evidence IDs/checksums and available report-chain implementation; actual report claim chain NOT VERIFIED. |
| Latency observability | PASS — durable task/run UTC events allow coarse system durations. |
| Usage observability | PASS at implemented boundary for logical calls/search/output tokens; input/planner/internal retry UNAVAILABLE. |
| Cost observability | PASS for honestly labelled estimate; actual provider charge UNAVAILABLE. |
| Failure/retry behavior | PASS for visible HTTP/grounding/budget outcomes and safe NOT_READY; SDK retry count NOT VERIFIED. |
| Repeatability | NOT VERIFIED — no extra paid diagnostic after failed first run. |
| PDF and PPTX generation | NOT VERIFIED / not attempted — no legitimate approved report. |
| Human PDF / PowerPoint visual acceptance | NOT VERIFIED — no documents generated. |

No six-claim report citation sample is possible: there are **zero report claims**, citation IDs or saved Report revisions. The pre-registered unsupported-claim probes (operator market share; utilization inferred from capacity; announcements as current inventory; 2025 as July 2026; causality; forecasts as observations) are all **NOT VERIFIED in a final output**, rather than vacuously PASSED. No user-visible report approval occurred. PRF-07C document visual acceptance is not imported into this run.

Defects/observations to preserve for a *separate* remediation phase, not fix in this run:

1. **Research integrity / search quality, high:** irrelevant `presented observations unsupported roi` prefix in actual query text and acquisition of unrelated ROI/B2B content; can starve material INs under a bounded source budget. Investigate SearchQueryBuilder keyword extraction from negative brief constraints and source relevance ranking, using the frozen run as a regression fixture. Do not hand-select favorable sources in this run.
2. **Research integrity / source independence, high:** shared DfT/Zapmap feed counted as two independent sources by readiness. Underlying-dataset lineage is not represented as an authoritative Source field; any quality gate using URL-count independence must remain conservative.
3. **Research integrity / temporal scope, medium-high:** Zapmap's end-Aug 2026 observations persisted as IN1 Evidence despite fixed 1 Jul cutoff; validate observation date at evidence/readiness boundaries rather than trusting publication eligibility alone.
4. **Orchestration/budget design, medium:** an eight-call Evidence cap with zero remediation reserve ended with five missing INs; distinguish true scarce evidence from budget starvation, while respecting owner cost. Do not simply raise caps and rerun this acceptance attempt.
5. **Observability, medium:** every Source `published_at` was NULL; planner/input-token and SDK retry usage not reliably captured; zero-result search-arm text not fully persisted. Exact spending cannot be asserted.

Overall research acceptance **FAIL / completed with findings**. The smallest next phase is a scoped search-query/relevance and independence/freshness remediation with offline regression fixtures from this first run, plus a separately approved rerun under a new acceptance identifier and budget. Do not mutate or erase this run.
