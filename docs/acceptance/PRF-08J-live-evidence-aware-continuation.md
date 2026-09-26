# PRF-08J — Controlled live Evidence-aware continuation

**Verdict: PRF-08J_LIVE_COMPLETED_WITH_FINDINGS.** Exactly one research run was created and preserved. PRF-08I's initial/reserve partition and scheduler priority were observed live, but useful coverage of the zero-Evidence needs did not improve. There was no second run, rescue, query/Evidence edit, threshold change, product fix or push.

## Baseline, isolation and preflight

Branch `acceptance/live-desk-research-01`, initial HEAD `361eadb174641a51bcb104a3447f3c5d7c82dc61`, ahead 12 / behind 0 against the locally recorded upstream. Tracked files/index were clean; historical untracked artifacts remained untouched. The accepted 2862-test offline run (145 skipped, zero failures/errors) was reused, not rerun.

The new Compose project is `ai_research_os_prf08j`, with loopback API `http://127.0.0.1:18085`, separate API/worker, database `prf08j_acceptance`, network `ai_research_os_prf08j_acceptance`, and dedicated `postgres_data`/`protected_data` volumes under that project prefix. PostgreSQL has no host port. Image `ai-research-os-prf08j:361eadb` was built from current product code; image config identity `sha256:d352ff9b27b5a4654900da9e3610d1e8da0fb7dbe8b844c4f097f9f2a1f671bc`. Only the new database was migrated through `016_prf06f_pptx`. API, worker and PostgreSQL became healthy; `/health` and `/ready` returned 200. The empty database had zero projects and runs before preparation. Existing services and historical volumes were not restarted, reconfigured or migrated.

Provider credential presence was checked without exposing values. The ignored `.env.prf08j` is separate from root `.env`, and `.dockerignore` excludes `.env.*`. Worker database identity was verified as the new database. Runtime configuration confirmed **initial Evidence allowance 6, reserve 2, total 8, per-targeted-attempt cap 1**. Other limits remain: 24 run LLM calls, sufficiency 6, analysis 2, report 2, review 1, planner at most six INs, one gap round, one attempt/query/source per gap, initial eight source-fetch slots, 300-second initial acquisition limit, and worker restart disabled. No paid-call limit was enlarged.

Project `17fdec94-faf7-46b1-bec1-c09b74fdf1e5` received the same frozen brief via the normal UI form, read only from PRF-08H. `md5(brief::text)` remains **`7262e5080260e56109b7e95431ec481c`**. One normal design-generation request created `c94790c1-31c1-4522-91f6-e6f6ed594275`: RQ1→IN1/IN5, RQ2→IN2, RQ3→IN3, RQ4→IN4, RQ5→IN6. All material RQs retain coverage; the fixed observation/publication boundaries and exclusions were retained. Normal approval persisted `APPROVED` at `2026-09-26T07:05:43.643444+00:00`, input fingerprint `0bea46d612195b847247156b9f7aacaeb90160439faee48423225de26fb1e2d4`. Run count was still zero.

The acceptance helper initially used lowercase `desk` in the activation URL and received HTTP 409. Read-only inspection confirmed zero runs and showed the normal button uses uppercase `DESK`. Only this helper URL was corrected; no product code, brief or design changed. One subsequent normal `DESK` activation created the sole run. This was not a second research attempt.

## Sole run and primary trace

Run **`28b1b640-1ad0-5614-b1e0-4a01e9db3e19`** completed with `insufficient_research`, `ready_for_analysis=false`, final reason **`sufficiency_budget_exhausted`**. The task ledger spans `07:07:15.792948`–`07:09:20.501561 UTC` on 26 September 2026 (124.71 seconds). The authenticated product overview returned 200 and showed the refusal. Run count remained one. Final Evidence count/checksum: **27 / `299e88abe27b9363fd623f5f9e034eac`**. Findings, Insights, Reports, Reviews, PDFs and PPTX jobs all remain zero.

Source keys used below:

- **S1** `92e808f1-e37a-486b-88d9-c1050a0efcde`: GOV.UK January 2026 public charging infrastructure statistics.
- **S2** `458f8220-da4c-4f12-8b0b-12d1c00b80d0`: ONS electric-vehicle public charging devices indicator.
- **S3** `bcd5b4fe-9e14-4280-9826-d703f2243eef`: GOV.UK 1 July 2026 public charging infrastructure statistics.

All three were acquired successfully in the initial collection. There were 12 initial logical searches, 36 raw results, 19 unique URL groups, three fetch attempts and three acquired pages. The initial collector stopped at formal six-IN source coverage. The targeted attempt later reused S3, merging provenance without a new HTTP fetch; `sources_acquired=1` in its result is not an additional unique page.

| Extraction order | Phase / intended target | Source / acquisition | Extraction result | Persisted / qualifying Evidence | Output tokens |
| --- | --- | --- | --- | ---: | ---: |
| 1 | Initial, primary IN1; refs IN1/4/5/6 | S1, acquired | Valid empty | 0 / 0 | 22 |
| 2 | Initial, primary IN2; refs IN2/5 | S2, acquired | 3 candidates, 1 grounding rejection | 2 / 1 | 552 |
| 3 | Initial, primary IN1; refs IN1/2/3/5 | S3, acquired | Valid candidates | 7 / 6 | 1064 |
| 4 | Initial depth, primary IN1 | S3, existing acquired page | Valid candidates | 5 / 4 | 1296 |
| 5 | Initial depth, primary IN1 | S1, existing acquired page | Valid candidates | 11 / 4 | 1360 |
| 6 | Initial depth, primary IN2 | S2, existing acquired page | Valid empty | 0 / 0 | 22 |
| 7 | Targeted IN3; extraction work item primary IN1 | S3 reused; no new fetch | Valid candidates, one-call attempt cap | 2 / 2, mapped only to IN1/IN5 | 473 |

The six initial work items preserve execution order in diagnostics. The Evidence ID list is appended in work-item order; the read-only audit reconciles each persisted candidate count and source ID against this list before calculating per-attempt qualification. Initial pass: **25 raw / 15 qualifying**, six calls, stop `evidence_initial_partition_exhausted`. IN3 (operator deployments) and IN4 (utilization) both had **0/0**. Their ranks were 0; IN1/2/6 had rank 2. Scheduler order was `[IN3, IN4, IN1, IN2, IN6]`, with two remediation calls available. IN3 was selected first; no already-covered IN was selected ahead of it.

The targeted attempt used one logical search and one extraction call, producing two additional qualifying items for **IN1 and IN5**, none for IN3. Its extraction context still carried S3's broad refs IN1/2/3/5 and `primary_need_id=IN1`. The attempt was `bounded_partial`, one of two planned chunks processed, one skipped, with **one reserved call remaining**. Sufficiency reassessed the changed IN1/IN5 fingerprints, reused IN2/IN6, retained missing IN3/IN4, reached six semantic calls, and terminated before an IN4 attempt. The total extraction limit was respected: **7 of 8**, split **6+1**, not 6+2 actually consumed.

## PRF-08H comparison

The designs were independently generated; IN numbers must not be equated across runs without semantic mapping.

| Metric | PRF-08H | PRF-08J |
| --- | ---: | ---: |
| Logical searches | 12 | 13 (12 initial + 1 targeted) |
| New page-fetch attempts | 6 | 3; plus one targeted existing-source resolution |
| Unique acquired pages | 5 | 3 |
| Extraction calls | 8 initial, 0 targeted | 6 initial, 1 targeted |
| Raw / qualifying Evidence | 24 / 13 | 27 / 17 |
| Required INs with zero raw Evidence | 3 | 2, unchanged by continuation |
| Readiness | false | false |
| Final stop | Evidence remediation budget exhausted | Sufficiency budget exhausted |

| Semantic need | H IN: raw / qualifying | J IN: initial → final raw / qualifying |
| --- | --- | --- |
| 50 kW+ scale/change | IN1: 13 / 7 | IN1: 4/3 → 5/4 |
| Definitions | IN2: 7 / 5 | No standalone IN; incorporated in other requirements, not a direct numerical comparison |
| Regional/site type | IN3: 0 / 0 | IN2: 5/4 → 5/4 |
| Operator deployments | IN4: 0 / 0 | IN3: 0/0 → 0/0 |
| Utilization | IN5: 0 / 0 | IN4: 0/0 → 0/0 |
| All-public versus 50 kW+ context | No standalone IN | IN5: 9/5 → 10/6 |
| Gaps/limitations | IN6: 4 / 1 | IN6: 7/3 → 7/3 |

The regional improvement occurred in the initial pass, not as a consequence of targeted continuation. The two previously uncovered semantic needs still had no Evidence after continuation. A larger total count is not proof of useful remediation.

## Sufficiency and findings

This is **not** an unqualified A verdict that only external data scarcity remains. The refusal is safe, but **B: a demonstrated orchestration-quality finding** remains: the correct zero-Evidence target did not constrain the extraction work to that target, so its reserved call produced already-covered-need Evidence. Reassessment of those changes consumed the remaining sufficiency capacity and blocked the other zero-Evidence need despite an unused extraction reserve. The record establishes this sequence; it does not prove that a different page would satisfy IN3/IN4 or authorize a fix, higher limit or rerun.

PRF-08I partitioning and first-target scheduling are **validated live**. Productive remediation of uncovered needs and useful Desk E2E are **not validated**. The normal refusal was preserved; no downstream artifact was manufactured.

## Observable integrity

- RQ→IN coverage and normal approval: PASS.
- Persisted result-linked initial and targeted queries remained on the frozen UK charging topic; no unrelated B2B/marketing contamination was found. Texts of searches without saved result links are NOT VERIFIED.
- Temporal qualification remained conservative: IN1 and IN2 each exclude one unresolved item; IN5 excludes one out-of-period and three unresolved items; IN6 has two dated qualifying items, one static `not_applicable` item, and four unresolved exclusions. No admission of an unknown measurement was observed. Unencountered malformed-output recovery remains NOT VERIFIED.
- Extraction responses were five valid candidate-bearing and two valid empty responses; all have `structured_attempts=1`, zero observed structured retries. One ungrounded candidate was rejected. SDK transport retries are not fully observable.
- **Lineage finding:** the deterministic audit reports IN1/2/6 one independent lineage each, IN3/4 zero, and IN5 two. The established IN5 origins include `Department for Transport, sourced from Zapmap` and `Zapmap`, with excerpts explicitly describing the same upstream feed. These textual aliases can be counted separately despite shared provenance. Thus source independence is **not marked PASS**; the evidence supports an alias-normalization overcount finding, not two independent charging inventories. No historical outcomes were recalculated.
- Readiness was not forced. With no legitimate report, claim-audit/PDF/PPTX acceptance was not applicable and was not executed.

## Cost and bounds

Owner budget **USD 5.00**, operational rather than provider-side monetary cap. Official [GPT-5 pricing](https://developers.openai.com/api/docs/models/gpt-5) was fetched ($1.25/M input, $10/M output); [Tavily pricing](https://www.tavily.com/pricing) was fetched ($0.008/credit pay-as-you-go). The existing basic-search configuration was retained. OpenAI Docs was used to recheck current prices; no model substitution or billing subsystem was introduced.

Pre-run estimate used at most 19 stage calls from the configured stage allowances plus up to three planner structured attempts, 60k input tokens/call as a conservative **assumption**, up to 8192 output tokens/call, and 18 searches: **USD 3.59624 base / USD 4.49530 with 25% contingency**. This is not a hard input-token bound or proof against every SDK transport-retry billing scenario. SDK retries remain bounded by the existing client; complete retry billing/account balance is unavailable. No uncontrolled loop or worker restart was introduced.

Observed: **13 stage logical calls = 7 extraction + 6 sufficiency**, one successful planner-generation request (internal planner attempt count not fully exposed), 13 logical searches, three fetched pages, one reused-source targeted attempt, 124.71-second research task span. Seven extraction responses report **4789 output tokens**, zero reasoning tokens, 4096 output-token cap each. Complete planner/sufficiency input/output token totals and provider bill are unavailable. With up to three planner attempts, 60k input/call and the observed extraction output, estimated post-run envelope is **USD 2.08917 base / USD 2.61146 with contingency**; using 8192 output for every logical call instead gives **USD 2.61472 / USD 3.26840**. These are conditional estimates, not measured charges. No additional paid probes or second run were made.

## Historical integrity

Pre/post read-only checks used `md5(string_agg(row_to_json(e)::text, chr(10) ORDER BY e.id))` on the original isolated databases, scoped to each historical run. All counts/checksums match their accepted records:

| Run | Evidence count | Evidence checksum | Pre/post workflow-row checksum |
| --- | ---: | --- | --- |
| PRF-08B | 13 | `076646d8ec25f2a7d682ec420896af95` | `00ef1aa66c3b6194ba39d1a01c066de7` |
| PRF-08D | 33 | `84ce68280d94941b19414a46893f2868` | `01e242df696ac51050788442c6249471` |
| PRF-08F | 22 | `7937d0745c8c03a67ffc045c9fbbb6f5` | `3eedf9afcfbd4b61b1eaa672bc36f3f8` |
| PRF-08H | 24 | `3866b66b19d3ec31ff6210fafa297922` | `60fd6bb7a92d1c36f0bb04073d567e47` |

All retain `completed` status. PRF-08D's workflow fingerprint also matches the previously published fingerprint; the other workflow fingerprints are additional unchanged pre/post evidence from this task. No historical run was recomputed, repaired or mutated.

## Delivery

Acceptance-only files: dedicated Compose configuration, startup/owner helpers, explicit-action UI driver, read-only metadata auditor, and this report. No application, test, renderer, schema or production deployment file changed. The helper-only lowercase route correction is documented above. Python compile validation of the three helpers, PowerShell parser validation (zero errors), and Compose `config --quiet` passed. Secrets remain ignored, provider-response previews and runtime dumps are not Git deliverables. Existing untracked acceptance artifacts remain preserved. The sole completed run remains available at `http://127.0.0.1:18085/ui/research/28b1b640-1ad0-5614-b1e0-4a01e9db3e19/overview`; no cleanup was performed.

Reuse `scripts/prf08j_start.ps1` only to restore this same environment; it does not launch research. The UI helper's paid `generate`/`activate` actions must not be repeated for this accepted single-run task. No new live run or product remediation is authorized by this record. One reviewed local acceptance-record commit is appropriate; no push.
