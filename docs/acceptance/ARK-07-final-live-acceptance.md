# ARK-07 — final live acceptance gate

## Preflight NO-GO — 2026-09-27

**ARK_ACCEPTANCE_INCOMPLETE / ARK-07_ACCEPTANCE_INCOMPLETE.** Infrastructure
stability requirement failed before any provider call. No ARK product verdict
can be inferred. The single live authorization remains unused.

Baseline: branch acceptance/live-desk-research-01, HEAD
`b662526048801c7af3e2b16c02610835189fe08d`, clean tracked/index state,
ahead33/behind0 local tracking. No product changes or offline suite rerun.

## Isolated current-source environment

Built `ai-research-os-ark07:b662526` from accepted HEAD; manifest-list digest
`sha256:e431a229faf1733dffca298d34ea7d006a03f1f9375dd53f57d96f2aaa86d25c`.
Compose project `ai_research_os_ark07`, loopback API `http://127.0.0.1:18092`.
Existing acceptance template plus private ignored `.env.ark07-runtime/compose.yml`.
Dedicated network ai_research_os_ark07_acceptance and dedicated postgres_data /
protected_data volumes with that project prefix. No historical volumes reused.
Private established acceptance credentials referenced without printing/editing;
root .env untouched. ARK and funnel enabled; existing 6+2 budgets unchanged.

Initial migration command ran before the fresh PostgreSQL listener was ready and
received connection refused. After pg_isready and health confirmed readiness,
the migration succeeded through `016_prf06f_pptx`; only the new database migrated.
Established owner registration succeeded. API and worker started normally.
This startup race is separate from subsequent recurring healthcheck failures.

## Bounded stability checks and stop

Four probes started UTC 15:38:36.257, 15:39:15.875, 15:39:44.918,
15:40:15.124. Total observation 121.183 seconds. Docker 29.6.1 responded 4/4;
PostgreSQL/API/worker reported running/healthy, restart counts zero; API /ready
passed 4/4 and direct worker healthcheck returned exit0 4/4.

However retained automatic worker healthchecks demonstrate recurrence:

|UTC check start|Exit|
|---|---:|
|15:37:45.124|-1|
|15:37:58.491|0|
|15:38:17.366|0|
|15:38:36.113|-1|
|15:38:58.605|-1|
|15:39:18.765|-1|
|15:39:38.882|0|

Thus successful manual probes and Docker's aggregate healthy label do not satisfy
the explicit requirement of no recurring exit=-1. NO-GO was declared before any
design or research operation. Root cause of automatic-check failures is not
established; no claim of product regression, DNS failure or HTTP500 without
evidence. No host restart, worker restart or speculative recovery was attempted.
No live attempt in a partially healthy environment; no automatic retry scheduled.

## Authorization and unverified gates

Final read-only counts in new database: projects0, workflow_runs0, Evidence0.
Design requests0, approvals0, provider calls0, searches0, extraction0, cost USD0.
Frozen checksum required `7262e5080260e56109b7e95431ec481c`; not copied into a
new project before NO-GO. Execution pin, adaptive behavior, citations, readiness
Source integration, ledger/retries, funnel, sufficiency and downstream are all
NOT VERIFIED live. No synthetic result is substituted for live acceptance.

OpenAI Docs was consulted for eventual cost preflight: [GPT-5 pricing](https://developers.openai.com/api/docs/models/gpt-5)
USD1.25 input / USD10 output per million tokens; [Tavily pricing](https://www.tavily.com/pricing)
also retrieved. No completed budget GO or billed calls followed. USD5 remains
the operational limit for the unused scenario, not a newly consumed authorization.

## Fresh historical verification

All original databases read-only: ordered Evidence row_to_json aggregate MD5 and
full workflow row MD5. Exact matches with ARK-06 record; no outcome recomputation.

|History|Count|Evidence MD5|Workflow MD5|
|---|---:|---|---|
|B|13|076646d8ec25f2a7d682ec420896af95|00ef1aa66c3b6194ba39d1a01c066de7|
|D|33|84ce68280d94941b19414a46893f2868|01e242df696ac51050788442c6249471|
|F|22|7937d0745c8c03a67ffc045c9fbbb6f5|3eedf9afcfbd4b61b1eaa672bc36f3f8|
|H|24|3866b66b19d3ec31ff6210fafa297922|60fd6bb7a92d1c36f0bb04073d567e47|
|J|27|299e88abe27b9363fd623f5f9e034eac|2e66c4ab0dbf4365877c97e61e053576|
|O|1|135c9ec526cdd2672bd61b52e7902f7d|9dcb9c3b7526dd0eeb2a625876460c28|
|T|5|3c15be644e3a45f47955bc1da2bfd412|eab5db1fd4860e5011a91c6fefed1e53|
|V|21|7f9ca2da74d75c5bae0107a425108309|0efe638f7ce58baa6dc785d499f340ce|
|X|0|NULL|cc468d87e5efe063634cfbd4b75afd31|
|ARK03|16|e93284678aa04afd32cee577a1601093|b6dfb8368131bc7ab75d201dd8ae0917|
|ARK05|9|b561fd1f26f08a9086683686ff14bf41|25a78ae449ae0cccc04ef1a3af42ae6d|

## Handoff

Environment retained for diagnosis, no cleanup. Historical services/data/artifacts
untouched. Only this preliminary acceptance record is new and untracked; private
runtime override/build logs ignored. No commit because live gate did not complete;
no push. Resume this record after stable infrastructure, not another acceptance
phase. Do not interpret the preflight failure as an ARK correctness failure.

ARK-07_ACCEPTANCE_INCOMPLETE

## Resumed final live gate — 2026-09-27

The initial NO-GO above is preserved chronology, not the final verdict.
**Final decision: ARK_ACCEPTED / ARK-07_ACCEPTED. ARK architecture phase CLOSED.**
Research remains genuinely insufficient; no coverage optimization or ARK-08.

### Infrastructure transition and baseline

INFRA-01 established automatic Engine probe timeout5s, not worker-process failure.
INFRA-02 applied acceptance-only15s timeout and verified6/6 automatic probes,
no restart/OOM, healthy API/PG. Commit21d475a9c863c0bf483774747b94843614015771.
Owner then explicitly requested resumption without another separate preflight.
HEAD matched, tracked/index clean. Runtime image remains the accepted ARK06
b662526 product build (digest recorded above); the subsequent INFRA02 commit
changes only acceptance configuration/reporting/tests, not product or ARK code.
Both API/worker inspect Image equals the recorded manifest digest. Worker restart0.

### Exactly one normal scenario

- Project a3004bbc-a4aa-4a8b-bfe6-550cd8659315, ARK-07 Final Live Acceptance.
- Persisted frozen brief MD5:7262e5080260e56109b7e95431ec481c, exact match.
- One design request started16:09:32.657UTC, HTTP200 at16:10:15.043 (42.386s).
- Design533448a7-1fe4-4f60-b825-182c61fa0931: five RQs/INs, explicit expectations,
  frozen temporal/geography scope, comparable definitions and limitations inspected.
  Normal product validation passed; no design edits or second request.
- Exact design approved16:11:03.746; activated16:11:04.192.
- Run cb1aa16a-4c1e-5891-a007-887746f77dd7, completed16:12:31.570UTC (~87.4s).
- Exactly one persisted run. No rescue, manual query/candidate/Evidence changes,
  recomputation or second activation. Provider execution stopped naturally.
- Pin version1, method desk-v1; final kernel revision85, pending null,
  reservations empty, input fingerprint
  0ba8d0fc0a2835466df883295417007c86f30dc64daba941a5e36eb43b151780.

### Adaptive sequence, ledger and funnel

21 logical actions: search5, acquisition6, extraction8, assessment2.
Decision records contain observed gaps, eligible actions, chosen action/reason,
reservation, provider attempt, outcome and subsequent observation.
An in-flight snapshot captured a pending acquisition with reservation before its
return; final records show all attempts returned, ordinal1, retryfalse.
Provider records: search5, retriever6, OpenAI10 (extraction8 + assessment2).
No ambiguous terminal calls or capacity resurrection. No worker restart occurred.

Searches returned3,0,3,0,0 candidates:6 candidate events total. Acquisitions6
attempted,5 acquired plus1 truncated response;0 failed retrievals. Initial
extractions6:2 valid-empty,3 rejected,1 productive (2 raw Evidence,1 qualifies).
Continuation2: first IN2 rejected/no qualifying gain; then IN1 productive
(5 raw Evidence,1 additional qualifying gain). Both justified opportunities used;
no early stop after the unproductive attempt. Final extraction budget8/8.
Total2 valid-empty,4 rejected and2 productive extraction actions,7 Evidence.
Telemetry extraction status success means parsed output, not necessarily accepted
Evidence: rejected actions have raw extraction success but persisted_count0.

Assessment followed each changed qualifying Evidence set, first1 then2 items.
Final stop insufficient_opportunities, ready_for_analysis=false. All candidates
had been acquired and extraction capacity exhausted; remaining acquisition/LLM
allowance alone is not permission to invent additional extraction capacity.
Budgets unchanged: initial6/6, continuation2/2, assessment2/6, search5/5,
acquisition6/13, decisions21/84, kernel conservative LLM10/19.

### Every Evidence citation audited against full persisted Source

All seven use Source86e0ece1-cadb-4099-92eb-4e33de87a3e5, full raw Source SHA256
2258a2cc7a558306416ff912b781b869cda59498b5b4b1f1e32e66bf4bbeeecd.
Read-only audit verified Source/project identity, full-content checksum against
stored Source/Evidence values, canonical HTML-unescape/NFC/whitespace-normalized
full Source, integer Unicode half-open coordinates, resolved exact excerpt and
excerpt hash. No alternative-span search or repair. Five later-chunk records
resolve correctly against full Source, not local offsets.

|Evidence ID|Unicode span|Citation|Final qualification|
|---|---|---|---|
|348cd6f3-3c27-4148-b2c7-062b3e863e93|[8118,8171)|VALID|no|
|4a989b65-eec8-4d0b-8e4d-5a9774919751|[6353,6796)|VALID|yes|
|5a3cb86e-1678-45ae-b5e4-26eec38bf513|[3512,3799)|VALID|no|
|5c15f17c-0805-40b9-be64-2bcfaf7420ea|[8702,8814)|VALID|no|
|c23394ca-a4fd-4795-9854-6f190c2c51b0|[12441,12547)|VALID|no|
|e2cf9db5-17d9-4788-b7ae-c7afe005b870|[9582,9715)|VALID|yes|
|f7856e62-5649-41b5-8dea-99cf2cfb906b|[9058,9275)|VALID|no|

VALID7 / INVALID0 / UNRESOLVABLE0. No invalid/unresolvable item qualified.
Citation validity alone is not temporal/sufficiency qualification.

### ARK-06 readiness Source integration — PASS

The running ARK06 code injects self.sources into authoritative readiness.
Both actual semantic assessments ran (unlike ARK05); no invalid_citation or
missing-Source operational diagnostic. Initial two raw Evidence become one
qualifying; final seven raw become two qualifying. Qualification-stage events
across both snapshots:3 applicable_satisfied,3 applicable_failed,3 unresolved.
These are repeated observations, not nine distinct Evidence.

Read-only canonical qualified IDs:
4a989b65-eec8-4d0b-8e4d-5a9774919751 and e2cf9db5-17d9-4788-b7ae-c7afe005b870.
Canonical per-IN fingerprint comparison against persisted terminal AND semantic
assessment fingerprints passed5/5; final counts [2,0,0,0,0]. IN1 fingerprint:
c0e290f2bfff4c5ec5ad3e6f643f3f5acc5c9ae5efec81d8522623250d8f6493.
Comparison computed identities from current immutable Evidence only; did not
rerun an assessor/provider or write readiness. IN1 assessment current=true,
partial, one independent source; IN2–IN5 genuinely missing. No valid Evidence
disappears due to unavailable Source access.

### Research limitation, telemetry and downstream

IN1 lacks precise metric definitions/cut-offs and comparable2026 figures;
IN2–IN5 have no Evidence. Remaining limitation is bounded research coverage/
candidate yield/extraction qualification, not demonstrated ARK correctness failure.
This is a safe insufficiency result, not a complete Desk E2E acceptance.
Initial/continuation phase labels match6/2; search5 and acquisition6 correctly
labelled initial. Two readiness snapshots; observer_errors0/dropped_events0.
Telemetry observational behavior is supported by records and prior offline
on/off tests, not by a second live run. No second run was performed for comparison.
Analysis/report/review skipped normally. SQL counts Findings/Insights/Reports/
Reviews/PDF/presentation_jobs all0. No artifacts fabricated to force exports.

### Cost and observability limits

Pre-GO reused unchanged configured-envelope estimate USD4.92131 with15% reserve
from ARK05: bounded design retries,14 research units, bounded downstream,
30k input-token allowance/attempt and configured output caps. Rates verified in
the initial ARK07 record. Operational estimate, not provider-side hard monetary cap.
Actual path:1 design request,10 research OpenAI attempts,5 Tavily searches,
6 acquisitions,8 extractions,2 semantic assessments; research retries0.
Recorded output3916 tokens (3593 extraction +323 sufficiency); elapsed LLM51071ms.
Recorded input0 denotes unavailable telemetry, NOT zero input consumption.
Design transport-attempt count is not durably metered; exactly one HTTP request.
Conservative completed-path estimate retaining9 maximum design attempts,30k input
per attempt, full output caps and5 searches: USD2.02130 before contingency /
USD2.324495 including15%. Exact invoice/balance NOT VERIFIED; no claim of measured
spend. No further paid operations after completion.

### Fresh integrity, infrastructure limitation and closure

All eleven original historical databases rechecked read-only during this resumed
turn using the canonical count/ordered Evidence-row MD5/full workflow-row MD5.
Every value exactly matches the historical table above and ARK06. No historical
outcome recomputed, edited or reinterpreted; ARK03/05 failures remain failures.
New run Evidence7/hash d4b8d9ca51f0dad3dca7c539498973b9;
workflow row hash b0906e3a442a040ce0865ffd08682e99.

After terminal completion and successful SQL output/COMMIT for downstream counts,
Docker CLI emitted one HTTP500 reading /exec/.../json status. Subsequent inspect
showed worker running/restart0/OOMfalse. This is a residual Docker management
limitation, not evidence of a failed research action; all critical persisted
records and fingerprint comparisons were already available. No recovery attempted.

Live crash/retry recovery, malformed/unresolvable live citation rejection,
missing-Source outage behavior, downstream deliverables and exact billing remain
NOT VERIFIED naturally. No defect inferred merely from genuine insufficiency.
No product changes/offline-suite rerun/manual rescue/new phase/push. One local
acceptance-evidence commit only: ARK-07 final live acceptance. Private runtime
audit output and existing INFRA01/historical artifacts excluded.

ARK-07_ACCEPTED
