# PRF-08O — Live targeted continuation on the existing design

**Verdict: PRF-08O_LIVE_COMPLETED_WITH_FINDINGS.** Exactly one research run completed with a conservative refusal. The 6+2 bound, zero-Evidence target selection, retained target identities and use of the second slot were observed. Both targeted attempts produced no Evidence. Cross-IN-only deferral and confirmed-lineage alias normalization did not occur naturally and are NOT VERIFIED live. No second run, rescue, product fix or push occurred.

## Baseline, authorization and preflight

Branch `acceptance/live-desk-research-01`, initial HEAD `6650b7a71c9ebaf1d7791f7e9b95c5045fb543a8`, ahead 17 / behind 0 against recorded upstream. Tracked/index state was clean; existing untracked artifacts were preserved. Only relevant acceptance metadata/diagnostic serialization was inspected; PRF-08K logic was not re-audited or changed.

The owner approved existing design **`0f333dd1-54bc-49a0-b758-0e308e61c336`** and authorized one normal bounded OpenAI/Tavily research run, research-only operational budget **USD 5.00**. No new planner/design-generation request was made. Project `f8b634b0-dae6-44a1-86ed-cc1c00726e9f` retained frozen brief MD5 **`7262e5080260e56109b7e95431ec481c`** and the existing 5-RQ/6-IN design. Preflight run count was zero.

The existing isolated `ai_research_os_prf08l` API/worker/PostgreSQL were healthy; `/ready` returned 200. No container, credentials, configuration, database schema or historical environment was recreated/reconfigured. Runtime controls: GPT-5; Evidence total 8, reserve 2, one call per targeted attempt; sufficiency 6; analysis 2; report 2; review 1; global stage-call cap 24; one gap round and one attempt/query/source per gap. Worker restart remains disabled. Structured retries consume existing stage caps.

The unchanged practical pre-run estimate, using the previously recorded official prices, up to 19 stage calls, assumed 60k input tokens per call, conservatively 8192 output tokens per call and 18 basic searches, was **USD 3.12548 base / USD 3.90685 with 25% contingency**. This is an operational estimate, not a hard input bound or provider billing cutoff. PRF-08N design cost is excluded from this new research estimate.

## Normal approval and sole activation

The existing UI helper submitted normal approval with the exact existing design ID. Approval persisted at `2026-09-26T09:20:21.433005+00:00`; run count remained zero. Exactly one subsequent `methods/DESK/activate` request returned the normal overview URL and created:

**Run `966141f8-b07f-510c-8e41-66795ab65227`**

Local result: `http://127.0.0.1:18086/ui/research/966141f8-b07f-510c-8e41-66795ab65227/overview`.

Workflow event timestamps: started `09:20:40.517692`, completed `09:21:55.852355 UTC`, 26 September 2026 — **75.334663 seconds**. The task-row creation-to-final-update span is 77.421091 seconds; these are different clocks, not provider time. Workflow status is `completed`, business outcome **`insufficient_research`**, readiness **false**, termination **`evidence_remediation_budget_exhausted`**.

## Source key and collection

| Key | Source ID | Source |
| --- | --- | --- |
| S1 | `734d4287-2801-4029-98d5-ebd6bedede74` | `https://www.zapmap.com/news/new-ev-charging-infrastructure-reporting-metrics-2026` |
| S2 | `ef5bc7f9-afa0-44e8-8b9f-03ffac1c0d7f` | GOV.UK public charging infrastructure statistics, 1 July 2026 |
| S3 | `8033da88-b642-4247-add1-7b4909f0aaf0` | ONS electric-vehicle public charging devices indicator |
| S4 | `02fd8154-65ec-4b95-9437-4d594cfbbe61` | US eCFR title 23, part 680 |
| S5 | `940c37ea-ad66-4dcb-8707-2eef7c24de9b` | `http://www.zap-map.com/news/new-ev-charging-infrastructure-reporting-metrics-2026` |
| S6 | `d436e155-87a0-484a-9544-df1e324ffb1c` | GOV.UK public charging infrastructure statistics, January 2026 |

Initial collection: **11 logical Tavily searches, 27 raw candidates, 18 unique URL groups, 4 recorded acquisition attempts, 4 acquired sources, 0 recorded failures**. It stopped at formal source coverage of all six INs, not Evidence sufficiency. Each continuation recorded one additional search and one acquired source. Totals: **13 logical searches, 6 acquired source records**. Targeted acquisition failure/attempt totals are not retained in the serialized history; there are at least six demonstrated successful acquisitions overall, but a precise count including any unsuccessful targeted fetches is NOT VERIFIED. No failed source row is present.

S1 and S5 have identical content checksum `32d8214233b548a56ea0fb0b96cd536df09e8251242e2de7a5acbe8f47977cef`, despite separate URL/source identities. Thus six source records represent only **five distinct acquired content checksums**. Targeted #1 revisited the same content under another URL. This is a candidate-diversity observation, not evidence of double-counted independent Evidence lineage; neither source produced Evidence. S4 is a US regulatory source in a UK case and yielded no Evidence. No candidate was manually replaced.

## Ordered 6+2 extraction trace

IN shorthand below follows this run's existing design, not PRF-08J's numbering:
IN1 counts/definitions; IN2 regional breakouts; IN3 site-type breakouts; IN4 operator announcements; IN5 utilization; IN6 definition mappings.

| Order | Phase / primary or intended target | Source and acquisition | Extraction outcome | Actual supported INs | Persisted / qualifying | Output tokens |
| --- | --- | --- | --- | --- | ---: | ---: |
| 1 | Initial first opportunity, IN1 | S1 acquired | Valid empty | None | 0 / 0 | 22 |
| 2 | Initial first opportunity, IN2; refs IN2/4/5 | S2 acquired | Valid empty | None | 0 / 0 | 22 |
| 3 | Initial first opportunity, IN3; refs IN3/4/5 | S3 acquired | Valid empty | None | 0 / 0 | 22 |
| 4 | Initial first opportunity, IN6 | S4 acquired | Valid empty | None | 0 / 0 | 22 |
| 5 | Initial depth, IN2; refs IN2/4/5 | S2 existing acquired content | One valid persisted candidate | IN2 only | 1 / 1 | 467 |
| 6 | Initial depth, IN3; refs IN3/4/5 | S3 existing acquired content | Valid empty | None | 0 / 0 | 22 |
| 7 | Continuation #1, IN1 | S5 acquired; same content checksum as S1 | One call, fully processed, no persisted Evidence; detailed response shape not retained | None | 0 / 0 | 22 inferred from aggregate reconciliation |
| 8 | Continuation #2, IN3 | S6 acquired | Valid empty; first of two planned chunks processed, second bounded out | None | 0 / 0 | 22 |

The initial work-item array supplies execution order; persisted Evidence IDs reconcile to each work item's persisted count and source. History supplies targeted ordering and source IDs. The shared `remediation_extraction` snapshot retains only the **last** attempt's detailed work items; #1's history retains target, consumed call, source, processing state and zero Evidence delta, but not its response classification. We do not invent a detailed snapshot for it. Its 22 output tokens follow from Evidence aggregate 621 minus initial 577 and final continuation 22, not a retained per-response field.

Initial extraction used exactly **6 calls**, stopped with `evidence_initial_partition_exhausted`, and produced one raw/qualifying Evidence. **IN1/3/4/5/6 remained zero**. The first scheduler selected IN1 with two reserve calls remaining; covered IN2 ranked behind zero-Evidence needs. Continuation #1 retained IN1 in recorded request/attempt diagnostics, source scope remained IN1-only, target qualifying count stayed **0→0**, `improved=false`, and one reserve remained.

The next decision selected zero-Evidence **IN3**, not covered IN2 and not stalled IN1. Its extraction work item explicitly had `primary_need_id=in3_site_type_breakouts` and the matching scope. It consumed the final call; target qualifying count stayed **0→0**, `improved=false`. **No reserve slot was discarded or left unused.** Its second planned chunk was correctly skipped after the total bound was reached. Total **6 initial + 2 continuation = 8**; no unbounded search-until-success occurred.

No continuation produced cross-IN Evidence. Consequently preservation of useful cross-IN Evidence and the PRF-08K cross-only reassessment-deferral branch are **NOT VERIFIED live**. `cross_need_reassessment_deferred=false` for both attempts is consistent with zero new Evidence, not a failed deferral case.

## Coverage, sufficiency and classification

| IN | Initial raw / qualifying | Final raw / qualifying |
| --- | ---: | ---: |
| `in1_counts_definitions` | 0 / 0 | 0 / 0 |
| `in2_regional_breakouts` | 1 / 1 | 1 / 1 |
| `in3_site_type_breakouts` | 0 / 0 | 0 / 0 |
| `in4_operator_announcements` | 0 / 0 | 0 / 0 |
| `in5_utilization_evidence` | 0 / 0 | 0 / 0 |
| `in6_definition_mappings` | 0 / 0 | 0 / 0 |

The sole Evidence concerns UK regional rapid-or-above chargers per population at the fixed July 2026 date; temporal classification is `applicable_satisfied`. It supports only IN2, not all initial source-discovery refs. It does not make IN2 or the entire research sufficient. There are **five zero-Evidence required INs** after the run. The single semantic sufficiency assessment was reused unchanged through both empty continuations; no false target closure or forced readiness occurred.

For the observed execution, this is **A: bounded research remained insufficient with the tested target/budget controls working**. There is no demonstrated B-style orchestration violation preventing use of the remaining reserve. This is not proof that public evidence does not exist, or that every PRF-08K branch is validated. Low yield, source-content repetition and missing live cross-IN/alias cases limit acceptance; therefore the final verdict is qualified findings, not full live/E2E acceptance. No corrective change or second run was made.

## Lineage and observable integrity

The sole Evidence has no established `data_lineage` metadata. `canonical_lineage_identity` returns an empty identity. The deterministic signal reports one **provisional unknown stream**, the pre-existing conservative behavior, not an established independent provenance. It did not create corroboration or readiness. No established-origin pair occurred naturally: **NOT VERIFIED — no live naming-variant pair encountered**. The S1/S5 URL/content repetition is not such an Evidence provenance pair.

Persisted discovery-linked query texts stayed within the frozen UK public charging needs; no unrelated B2B/marketing query contamination was observed. Not every search without a saved result has retained query text, so those texts are NOT VERIFIED. RQ→IN mapping remained the accepted design. Unknown/post-cutoff measurements, undated static qualification and malformed extraction recovery were not encountered and are NOT VERIFIED rather than assumed PASS.

## Downstream and cost

Readiness was false, so normal analysis/report/review tasks were skipped. Findings, Insights, Reports, Review results, PDFs and presentation jobs all remain **0**. Claim-audit and PDF/PPTX acceptance were not applicable and were not manufactured.

Persisted `_run_usage_summary`: **9 logical LLM calls = 8 Evidence + 1 sufficiency**, **0 recorded structured retries**, **785 output tokens = 621 Evidence + 164 sufficiency**, zero recorded reasoning tokens. Model elapsed total is 25.065 seconds, distinct from workflow elapsed 75.334663 seconds. Input-token fields are zero because this path does not populate them; they are **unavailable, not free/zero input**. SDK transport retries and actual provider billing are not fully observable. `estimated_cost_usd` is null.

Research-only conditional estimate using nine logical calls at assumed 60k input each, observed 785 output tokens, 13 basic searches and the prior verified prices: **USD 0.78685 base / 0.9835625 with contingency**. Conservatively allowing 8192 output tokens for every call instead gives **USD 1.51628 / 1.89535**. Neither is a measured charge. Both are below the USD 5 operational envelope; no further calls followed completion.

Historical PRF-08N design generation is separate: one HTTP request with conditional prior envelope USD 0.47076 / 0.58845, actual bill unavailable. It was not regenerated or counted again as a PRF-08O LLM call.

## Historical integrity and final fingerprints

Pre/post SELECT-only checks used canonical `md5(string_agg(row_to_json(e)::text, chr(10) ORDER BY id))` for the recorded historical run IDs. All counts, Evidence digests and workflow digests matched; statuses remain completed:

| Run | Evidence | Evidence MD5 | Workflow MD5 |
| --- | ---: | --- | --- |
| PRF-08B | 13 | `076646d8ec25f2a7d682ec420896af95` | `00ef1aa66c3b6194ba39d1a01c066de7` |
| PRF-08D | 33 | `84ce68280d94941b19414a46893f2868` | `01e242df696ac51050788442c6249471` |
| PRF-08F | 22 | `7937d0745c8c03a67ffc045c9fbbb6f5` | `3eedf9afcfbd4b61b1eaa672bc36f3f8` |
| PRF-08H | 24 | `3866b66b19d3ec31ff6210fafa297922` | `60fd6bb7a92d1c36f0bb04073d567e47` |
| PRF-08J | 27 | `299e88abe27b9363fd623f5f9e034eac` | `2e66c4ab0dbf4365877c97e61e053576` |

PRF-08O final Evidence: **1**, MD5 **`135c9ec526cdd2672bd61b52e7902f7d`**. Workflow-row MD5 **`9dcb9c3b7526dd0eeb2a625876460c28`**. These establish this new run's preservation baseline. No historical outcome was recomputed. PRF-08L/08N committed records remain byte-for-byte unchanged: their runs=0 checkpoints describe those historical attempts; the newly authorized PRF-08O run on the same project does not rewrite their results.

## Delivery

Only this record and `tools/prf08o_readonly_audit.py` are acceptance deliverables. The auditor uses read-only transactions, reconstructs counts from persisted metadata and never calls providers. Its syntax check and execution against the completed run passed. No offline suites or unrelated integration tests were repeated; no application/test/schema/rendering changes were made. No secrets, `.env`, raw provider payloads or runtime dumps belong in the commit. Existing artifacts, active deployment and historical services were preserved. The isolated environment remains available for inspection; no cleanup occurred.

Local commit subject: `PRF-08O record live targeted continuation`. No push, no next phase, no further activation.
