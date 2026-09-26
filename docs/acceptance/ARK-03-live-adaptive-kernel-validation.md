# ARK-03 — controlled live adaptive-kernel validation

## Verdict and scope

**ARK_LIVE_FAILED**: adaptive continuation and bounded accounting were observed,
but a persisted source-locator integrity defect was demonstrated. This is not
a budget overrun or fabricated Evidence finding. Three continuation Evidence
records have chunk-relative locator offsets that do not address their excerpts
in the stored full source. One of these records is qualifying. No remediation,
second design, second run, manual rescue, threshold change or push occurred.

Desk research independently ended in `insufficient_research`. No downstream
report or deliverable was manufactured. Successful workflow status means that
the refusal completed, not that research or this acceptance gate passed.

## Baseline, isolation and preflight

- Branch: `acceptance/live-desk-research-01`.
- Initial/source HEAD: `7705f5b68fdba9ac2674a3680ff1956b9d0bfe0b`.
- Initial tracked/index clean; local tracking divergence 29 ahead / 0 behind.
- Separate Compose project `ai_research_os_ark03`; loopback API
  `http://127.0.0.1:18090`; no PostgreSQL host port.
- Network `ai_research_os_ark03_acceptance`; new project-scoped
  `postgres_data` and `protected_data` volumes. Database `prf08l_acceptance`
  is in the **new** `ai_research_os_ark03-postgres-1`, not the historical L DB.
- Current-source image `ai-research-os-ark03:7705f5b`, shared by API/worker:
  `sha256:91741a5439162d97f541c86aeac81b8eeb02bde8091603e38817b38f9e050087`.
- Migration head `016_prf06f_pptx`, applied only to the new empty database.
- Existing Compose template and scoped environment file reused without editing;
  private ignored `.env.ark03-runtime/compose.yml` overrides image, port and
  enables ARK. It contains no credentials and is excluded from build context.
  Root `.env`, historical environments and unrelated artifacts unchanged.
- Docker 29.6.1; PostgreSQL/API/worker healthy. Three checks at
  19:11:07–19:11:23 UTC returned `/ready` ready; later readiness also passed.
  Credential presence checked as booleans only. No values logged.
- ARK enabled for new runs. PRF-08S telemetry emitted by normal production
  instrumentation; the redundant `RESEARCH_FUNNEL_ENABLED` environment setting
  is not itself proof of telemetry activation.
- Frozen brief copied read-only from X into the new project through the normal
  UI form; saved PostgreSQL `md5(brief::text)` exactly
  `7262e5080260e56109b7e95431ec481c`. No brief editing or historical DB cloning.
- No offline suite rerun; no product, test, schema or research-policy changes.

## Single authorized scenario and chronology (UTC, 2026-09-26)

Project `971026ee-41ca-47ed-afe6-54d1f003db9b`:
`ARK-03 Controlled Live Adaptive Kernel Validation`.

| Event | Observable result |
| --- | --- |
| Design request 19:13:49.519713 | Exactly one normal UI POST using PRF-08M diagnostic client; no client retry |
| Design return 19:14:59.361212 | HTTP 200 after redirect; design `83d5db4a-1e0f-4046-a0e5-c8a3e55d3b73` persisted |
| Design inspection | Five RQs, five linked INs; all material RQs covered; fixed UK/50 kW+/time scope and no-investment/no-forecast restrictions retained |
| Approval 19:15:23.702211 | Exact design approved through normal product validation; HTTP 200 after redirect |
| Activation 19:15:23.849224 | Exactly one normal activation; HTTP 200 after redirect |
| Run | `b2aeac54-dd01-5908-a208-b096e03ca38c` |
| Execution logs | First 19:15:23.959309; last 19:16:58.625001; 9 lifecycle events; approximately 94.666 seconds |
| Terminal | `completed`; kernel `insufficient_opportunities`; canonical `ready_for_analysis=false`, `insufficient_research` |

Persisted execution version is **1**, method `desk-v1`, observed both during
execution and at completion. Final kernel revision 97; no pending action or
reservation. Canonical JSON SHA256 of the execution pin:
`e1b0edbe514facdf6ebcb69591cbcaa758248875593cbd55516d0514a23e4838`.
Kernel input fingerprint:
`76b8aabf7b0d4df5bc40b3a74a9d4c915d46abff9dc8af7ad05e1d383ee1738a`.
No restart/reclaim occurred; restart-version stability is not a live-tested claim.

## Actual adaptive decision trail and ledger

The authoritative trail is the run's `_research_kernel_v1.decisions`; the
retained PRF-08S journal has 523 events, including 49 kernel decision/outcome/stop
events. Repeated snapshots/qualification events were not summed as new work.

| Decisions | Action/reason | Outcome and subsequent observation |
| --- | --- | --- |
| 1–5; revisions 0–16 | Five untried retrieval arms, targets IN2, IN5, IN3, IN4, IN1 | 3/3/3/3/0 candidates respectively; gaps remain missing; candidate opportunities expand |
| 6–13; revisions 20–48 | Eight untried eligible candidate acquisitions | Six acquired, two HTTP failures; finite content work queue becomes available |
| 14; revision 52 | Initial extraction, IN2/IN5 scoped source, chunk 0 | 3 stored; 1 qualifying cross-IN gain for IN5, **zero IN2 gain** |
| 15; revision 56 | Assessment, `changed_evidence` | IN5 partial, other four missing; new Evidence fingerprint |
| 16–18; revisions 60–68 | Three initial extractions | Valid-empty, rejected, valid-empty; no qualifying gains |
| 19; revision 72 | Initial extraction, IN5 source chunk 0 | 8 stored, 2 qualifying target gains |
| 20; revision 76 | Assessment, `changed_evidence` | IN5 still partial; other four missing |
| 21; revision 80 | Sixth initial extraction | 2 stored, no qualifying gain; initial 6 exhausted |
| 22; revision 84 | Reserve continuation + extraction + LLM + IN2 logical-gap slot; 15 eligible proposals | Existing scoped source chunk 1; valid-empty, target gain 0; gaps reassessed |
| 23; revision 88 | Reserve remaining continuation + extraction + LLM + IN5 logical-gap slot; 13 eligible proposals | IN5 source chunk 1; 3 stored, 1 qualifying target gain |
| 24; revision 92 | Assessment after changed Evidence; one eligible proposal | IN5 partial; other four missing; bounded refusal follows |

Continuation action IDs:
`extract:2535f060def21f67dce11b4cfe5a2abb3b82d27103db97ca18a044378d734460`
and `extract:f2f2bd109429e930020b1851f098fbe8c112e7eb62ad7b79c2460c30b7be9a8a`.
Each has the pre-dispatch reservation, ordinal-1 `openai/responses.create`
attempt and `returned` outcome. The first empty continuation did not discard
the second slot. Cross-IN gain did not masquerade as repair of IN2.

All 24 unique actions have exactly one recorded returned attempt: search 5,
retriever 8, OpenAI 11. No retry or ambiguous final attempt; no new capacity from
worker recovery. Read-only assertions checked unique actions, matching attempt
action/reservation, ordinal 1, all used counters within their saved ceilings,
and empty final pending/reservations. A transient in-flight `ambiguous` attempt
marker seen during monitoring finalized as returned; it was not a retry/failure.

Used/limit: extraction **8/8**, initial **6/6**, continuation **2/2**, research LLM
11/19, assessments 3/6, searches 5/5, acquisitions 8/13 (initial 8/8,
continuation 0/5), decisions 24/84, retries 0/14. Initial LLM 6/13; IN2 and IN5
logical-gap attempts each 1/1. No limits changed. `insufficient_opportunities`
is the actual kernel label: the adapter emits no extraction proposals once the
extraction envelope is exhausted. It is not proof that all public sources were exhausted.

The exact six-initial-valid-empty/zero-Evidence state did **not** naturally occur:
initial extraction already produced 13 stored / 3 qualifying records. That exact
edge case remains live NOT VERIFIED; offline ARK-02 evidence is not relabelled
as live evidence. Outcome-sensitive reassessment and both bounded continuation
slots were directly observed. No deliberate crash/recovery test or exactly-once
remote execution guarantee is claimed.

## Funnel, coverage and remaining bottleneck

| Metric | PRF-08X historical | ARK-03 observed |
| --- | ---: | ---: |
| Searches | 12 | 5, all returned, one zero-result |
| Candidate appearances | 24 | 12; 11 canonical identities |
| Acquisition attempts | 8 | 8; 6 acquired, 2 HTTP errors |
| Distinct acquired content | Not compared | 6 |
| Extraction initial + continuation | 6 + 0 | 6 + 2 |
| Valid-empty extractions | 6 | 3 (2 initial, 1 continuation) |
| Extractions persisting Evidence | 0 | 4 (3 initial, 1 continuation) |
| Extractions with qualifying gain | 0 | 3 (2 initial, 1 continuation) |
| Raw candidates / persisted Evidence | 0 / 0 | 32 / 16 |
| Qualifying Evidence | 0 | 4 |
| INs with any qualifying Evidence | 0/6 | 1/5 |
| Sufficient INs | 0/6 | 0/5 |
| Unused continuation slots | 2 | 0 |

Extraction guard rejections: 13 relevance and 3 grounding; no dedup hits. Kernel
extraction outcomes: three valid-empty, two rejected, one productive cross-only,
two productive-target. Raw extraction `success` is not the same as qualifying
success (one successful structured response persisted nothing).

All 16 stored Evidence map to `in5_definition_mapping`; qualifying count 4,
independent lineage count 1. IN1 scale, IN2 distribution, IN3 operator disclosures,
IN4 utilization each have stored/qualifying counts 0/0. IN5 remains partial for
missing feed origin, inclusion/exclusion rules and unsupported-question coverage,
plus insufficient diversity. All five canonical assessments are current; final
assessment and terminal Evidence fingerprints match for each IN. No unqualified
record counted toward readiness.

Remaining research limitation: **MIXED** — query/provider candidate quality,
acquisition/extraction and qualification. The scale query returned zero results;
operator candidates included US/out-of-window material and one selected page
failed retrieval; utilization produced two valid-empty extractions. The July
government distribution page's three extracted candidates failed relevance.
Two acquisitions failed HTTP. Most persisted material concerns methodology,
not the missing decision questions. These facts do not prove genuine public-data
scarcity. Provider/design variability (five English INs versus X's six and
different retrieval arms) prevents attributing the Evidence increase to ARK alone.
The ledger does prove outcome-driven continuation, not superior research quality.

### Telemetry limitations observed, not repaired

Legacy primitive decorators label all eight extractions `continuation_extraction`
and all acquisitions `continuation_search`. The 12 search-only candidate-decision
events say `acquisition_budget_unavailable`; acquisition events have empty
`candidate_ids`. These are not a faithful phase/selection summary under ARK.
The persisted kernel reservations and usage partition provide the actual 6+2
split; canonical identities connect candidates to the eight acquisition attempts.
No fabricated selection events or repaired telemetry were written. Search/acquire
kernel outcome `valid_empty` denotes no Evidence gain, **not** zero search results.

## Integrity: preserved checks and demonstrated failure

Canonical temporal events for the final 16 records: two applicable-satisfied,
two not-applicable (definitions), two applicable-failed and ten unresolved.
Only the first four qualify. May/February 2026 methodological changes qualify;
explicit 2023 and January-to-July-2026 interval records do not. Unknown/relative
times remain unresolved. No natural quarter-expression case: NOT VERIFIED.
All stored statements were inspected for IN relevance; legitimate cross-IN
methodology survived for IN5, not IN2. The canonical lineage assessment counts
only one independent lineage despite ONS/Zapmap source URLs. No duplicate content
identity acquired; no manufactured evidence or unsupported readiness.

All 16 source checksums match their referenced stored sources; all excerpts
exist in canonically normalized source text. An initial whitespace-only diagnostic
misidentified three HTML-entity differences; the production HTML/NFC normalization
resolved those. This does **not** resolve the following persisted locator defect:

| Evidence ID | Stored start:end | Actual full-source start:end | Qualifying |
| --- | --- | --- | --- |
| `5e193ca2-e967-4d86-9ab5-ce2a46415825` | 2251:2421 | 9752:9922 | Yes |
| `b3024cb7-3618-43e4-8e8c-a9313fcf821f` | 2986:3286 | 10487:10787 | No |
| `ab9746ca-9ca1-434b-ae2c-720910c77de4` | 2422:2910 | 9923:10411 | No |

Source `1b538b34-822f-4add-910c-21c80e62450d`, content checksum
`3db24a4c07c05d2fb483327b983d77b76644b2d79f21bb5339b7a54ab7de6061`.
All three came from continuation chunk 1 (metadata range 7500:13862).
The stored source slices at the saved offsets do not match the excerpts; actual
full-source offsets do. Excerpt hashes themselves match. Thirteen other locators
match the full source.

Supported mechanism: `_extract_work_item` replaces source content with chunk
text while keeping original-range metadata; `_persist_candidate` invokes
`verify_grounding` on that chunk text. The original range is outside the shortened
text, triggering its full-input fallback, which returns local coordinates. Those
coordinates are persisted against the original source/checksum. The affected
service is unchanged between pre-ARK-02 HEAD `152995f3...` and this source HEAD:
do not claim ARK introduced this code or that the cited facts were hallucinated.
It is nevertheless a demonstrated live source-location integrity defect, so
ARK-03 cannot claim integrity-preserved acceptance. No fix or data repair here.

## Downstream and observation limits

Analysis, Report and Review tasks were skipped. Findings, Insights, Reports,
Review results, PDF deliverables and presentation jobs are each **0**. Full Desk
E2E, report usefulness, citation rendering, PDF/PPTX and owner visual acceptance
were not reached. Run remains available at
`http://127.0.0.1:18090/ui/research/b2aeac54-dd01-5908-a208-b096e03ca38c/overview`.
No browser screenshot/visual-quality acceptance is claimed.

## Operational cost and timing

OWNER BUDGET: **USD 5.00**. PROVIDER-SIDE HARD MONETARY CAP: **NOT AVAILABLE**.
OPERATIONAL COST CONTROLS: **PASS**, bounded calls/outputs/retries and monitored
execution; actual invoice amount unavailable. No limit increase or second run.

Pre-GO practical envelope: GPT-5 input USD 1.25 / output USD 10 per million tokens,
verified using the [official model page](https://developers.openai.com/api/docs/models/gpt-5).
[Tavily pricing](https://www.tavily.com/pricing) is USD .008/credit; conservatively
allow two credits/search although the normal request does not request advanced.
OpenAI Docs skill was used for tariff verification, not provider research calls.

Allowance: design up to 3 structured calls x 3 SDK attempts = 9; research up to
8 extraction + 6 assessment attempts within the durable envelope; downstream
2 analysis + 2 report + 1 review logical calls x 3 SDK attempts = 15. Total 38
possible attempts. Practical input assumption 30k tokens/attempt (not a hard
input cap), informed by 8000-character extraction chunks, compact bounded design,
10-item assessment subset and batch limits. Maximum outputs 4096 for extraction
and review, 8192 for design/assessment/analysis/report. Input USD 1.425 + output
USD 2.66240 + 12 search calls at USD .016 = USD 4.27940;
15% contingency gives **USD 4.92131**. This is a conservative operational estimate,
not a mathematical billing guarantee; unexpected large requests would invalidate it.

Observed: one design HTTP request (70 seconds; underlying design usage/retries
not independently persisted), research 8 extraction + 3 assessment OpenAI attempts,
5 search attempts, 8 retrieval attempts, **0 research retries**. Research output
tokens 5742 + 458 = **6200**; model time 47949 + 7997 = **55946 ms**. Input/reasoning
zeros in usage summaries mean unavailable measurement, not verified zero usage.
No analysis/report/review calls. Revised conservative estimate retaining all nine
design-attempt allowances, 30k input for each of 11 observed research attempts,
reported research output and five two-credit searches: USD 1.62928 base /
**USD 1.873672 including 15% contingency**. Actual provider bill: UNAVAILABLE.
No paid calls after the terminal run.

## Fresh historical integrity and preservation

All nine original databases were readable. Fresh `BEGIN READ ONLY` verification
used count and `md5(string_agg(row_to_json(e)::text,chr(10) ORDER BY id))` for
run Evidence, plus `md5(row_to_json(w)::text)` for the run row. Every value matched
the committed ARK-02 evidence. No historical outcome recomputed or mutated.

| History | Evidence | Evidence MD5 | Run row MD5 |
| --- | ---: | --- | --- |
| B | 13 | 076646d8ec25f2a7d682ec420896af95 | 00ef1aa66c3b6194ba39d1a01c066de7 |
| D | 33 | 84ce68280d94941b19414a46893f2868 | 01e242df696ac51050788442c6249471 |
| F | 22 | 7937d0745c8c03a67ffc045c9fbbb6f5 | 3eedf9afcfbd4b61b1eaa672bc36f3f8 |
| H | 24 | 3866b66b19d3ec31ff6210fafa297922 | 60fd6bb7a92d1c36f0bb04073d567e47 |
| J | 27 | 299e88abe27b9363fd623f5f9e034eac | 2e66c4ab0dbf4365877c97e61e053576 |
| O (L container) | 1 | 135c9ec526cdd2672bd61b52e7902f7d | 9dcb9c3b7526dd0eeb2a625876460c28 |
| T | 5 | 3c15be644e3a45f47955bc1da2bfd412 | eab5db1fd4860e5011a91c6fefed1e53 |
| V | 21 | 7f9ca2da74d75c5bae0107a425108309 | 0efe638f7ce58baa6dc785d499f340ce |
| X | 0 | NULL | cc468d87e5efe063634cfbd4b75afd31 |

ARK-03 terminal Evidence MD5 `e93284678aa04afd32cee577a1601093`;
run-row MD5 `b6dfb8368131bc7ab75d201dd8ae0917`, stable on subsequent read.
Exactly one run persists. Historical API/PostgreSQL/n8n, root environment and
unrelated untracked artifacts were preserved. Only this acceptance record is
intended for the local `ARK-03 validate adaptive research kernel live` commit.
Private runtime override, credentials, raw provider payloads and generated data
are not Git deliverables. No product changes, migration additions or push.

ARK-03_LIVE_FAILED
