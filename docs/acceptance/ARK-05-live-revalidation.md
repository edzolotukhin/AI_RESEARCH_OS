# ARK-05 — controlled live revalidation

## Preflight chronology — 2026-09-27

**NO-GO before any provider call. ARK_LIVE_INCOMPLETE.** No product/kernel
correctness conclusion can be drawn from this infrastructure-only attempt.
Exactly one live scenario was authorized but has not been consumed: no design
request, approval, activation or research run was submitted; provider calls 0,
cost USD 0. Do not create a second acceptance phase when resuming this record.

Baseline verified: branch `acceptance/live-desk-research-01`, HEAD
`95b5d3a975d24620ce830cb0ccbbb23bdce2a0f2`, clean tracked files/index,
31 ahead / 0 behind local upstream tracking. Existing untracked artifacts retained.
No full offline suite was run. ARK-04's recorded full-suite result and subsequent
targeted fixes have not been rewritten as a green full run.

## Isolated current-source environment

- New Compose project `ai_research_os_ark05`, using the existing
  `docker-compose.prf08l.yml` and a private ignored
  `.env.ark05-runtime/compose.yml` image/port/ARK override.
- API loopback URL `http://127.0.0.1:18091`.
- New network `ai_research_os_ark05_acceptance`; new volumes
  `ai_research_os_ark05_postgres_data` and `ai_research_os_ark05_protected_data`.
  No PostgreSQL host port. Internal database/user names follow the existing
  acceptance template, but the container and data volume are distinct.
- Current-source image `ai-research-os-ark05:95b5d3a`; build manifest-list digest
  `sha256:867f4f1c6579a30f9ca02b4710e7eb791db818fce948a6e5aa4e356d9111c527`;
  image config digest
  `sha256:695860dcdeee83bcd1d5b4c54fa20adc74794fffddf672a66d10837bc899c0b7`.
- Verified project label and dedicated database volume before applying migrations.
  Migrations through `016_prf06f_pptx` applied only to this new empty database.
  Supported acceptance owner registration succeeded; no research fixtures seeded.
- Established private acceptance environment file reused without modification
  or credential output. Root `.env` not read/copied/modified. Credential presence
  was checked only as booleans, all true for the API's required keys.

## Readiness evidence and stop

Docker initially reported 29.6.1 and completed image build/container creation.
During the repeated preflight its management calls developed substantial delays.
Probe loop timestamps were 07:27:38, 07:28:22 and 07:28:59 Europe/Berlin;
each eventually returned Docker version 29.6.1 and HTTP `/ready` with
`status=ready`, PostgreSQL backend, `reason=null`. PostgreSQL was healthy.
These were not fast consistent whole-stack health confirmations.

Worker remained `running / health: starting`. Five consecutive retained health
checks had exit code -1, at UTC 05:27:07, 05:27:22, 05:28:11, 05:28:49 and
05:29:29. A direct worker-health command eventually returned exit 0, but only
after a prolonged delay and after NO-GO had been declared. This late successful
probe does not establish stable repeated health or negate the five failed checks.
The final read-only database-count/schema probe also remained pending at handoff.

The observed blocker is unstable/incomplete local Docker/worker readiness;
its underlying cause has not been established. No claim of a product regression,
Docker HTTP 500, internal DNS failure or `no route to host` is made without logs.
No host restart, historical-container restart or infrastructure deletion attempted.
The new environment remains available for later diagnosis. No automatic live
retry or paid request is scheduled.

## Authorization, version, frozen case and cost

Configured values verified without printing secrets: GPT-5, global logical LLM
limit 24, extraction limit 8 with 2 reserved continuation slots, assessment limit
6, planner output 8192, default output 4096, `ark_desk_enabled=True`.
No run exists to prove its persisted execution-version pin or actual 6+2 behavior.

Required frozen checksum remains `7262e5080260e56109b7e95431ec481c`.
It has not yet been copied/persisted into an ARK-05 project or freshly verified
there; no project/design was created before the infrastructure stop.

Owner operational budget USD 5.00; provider-side monetary cap not established.
OpenAI Docs was used solely to verify the configured GPT-5 tariff from the
[official model page](https://developers.openai.com/api/docs/models/gpt-5):
USD 1.25 input / USD 10 output per million tokens.
[Tavily pricing](https://www.tavily.com/pricing) was also consulted. No provider
research call was made. A complete current-run cost-envelope GO assessment is
still pending; previous ARK-03 estimates are not a substitute for that gate.
Actual paid-provider calls/searches/extractions/retries: **0**. Actual cost: **USD 0**.

## Unverified acceptance gates

Adaptive execution, persisted execution version, continuation, per-record citation
validation, qualifying citations, phase labels, ledger attempts, live retries,
funnel counts, sufficiency and downstream PDF/PPTX are **NOT VERIFIED**, because
no live research was attempted. No synthetic malformed live Evidence was inserted.

Historical B/D/F/H/J/O/T/V/X and ARK-03 were not modified. Their fresh ARK-05
checksum audit is still pending; the ARK-04 audit is prior evidence only and must
not be labelled a new ARK-05 verification. Existing historical stacks were merely
listed during preflight; all new lifecycle/migration commands named ARK-05.

## Git and continuation

Only this acceptance record is a proposed tracked change; private override/build
logs remain ignored. No product/test changes, commit, push, historical repair or
paid calls. Resume stable infrastructure preflight first, then frozen-case/version
and budget checks. Only after all gates pass may the already authorized single
design/research scenario proceed. No second design or run is authorized here.

ARK-05_LIVE_INCOMPLETE

## Resumption and final result — 2026-09-27

The preceding initial NO-GO chronology is preserved, not the final state.
Final verdict: **ARK-05_LIVE_FAILED**. One authorized scenario completed;
readiness dependency wiring falsely rejects valid citations. No fix or retry.

### Infrastructure recovery and GO (UTC)

Owner restarted Docker approximately 06:47:32. API/PG returned; worker remained
stopped exit255, restart policy `no`, no OOM/error. Evidence supports a worker
left stopped after Docker restart, not a demonstrated startup crash. Checks
07:00:32–07:01:04 still blocked GO. Only ARK05 worker started 07:03:18.932.
First automatic health 07:03:26 exit-1; from 07:03:47 healthy. Six manual checks
07:03:49–07:05:23 and latest five automatic checks passed, ~110 seconds stable.
No recurring 255/-1, restart loop, HTTP500/DNS/network error. Runs/calls/cost zero
until GO. No healthy or historical service restarted. Final all three services
healthy, restart counts zero, API /ready ready. Source HEAD unchanged.

### Single live scenario

- Project `5c3de2f1-6c39-47d3-b21c-245521b56c02`, ARK-05 Controlled Live Revalidation.
- Persisted frozen brief MD5 `7262e5080260e56109b7e95431ec481c`.
- One design request 07:21:34.465–07:22:32.339, HTTP200;
  design `8c27c691-6270-47a8-8866-114d2661fa37`. Five RQs/INs with explicit
  expectations, temporal boundaries, comparability and limitations inspected;
  canonical validation passed, no manual edits.
- Exact design approved 07:23:17.390, activated 07:23:17.503.
- Run `3ce5679a-ff45-564f-be97-12df68ed7643`, completed ~07:24:37.952.
  Exactly one run exists. No second request/activation or rescue.
- Execution pin version1, kernel desk-v1, final revision89, pending null,
  reservations empty; input fingerprint
  `0141626c3b8ca7f8a505a79207db4b7c84310d5f65c344a0fdf97139fafec00f`.

### Funnel, continuation, ledger and telemetry

Five searches returned 3,3,0,0,3 candidates (9 candidate events).
Eight acquisitions: 7 acquired, 1 timeout. Initial six extraction results
0,0,0,0,5,2 Evidence; two continuation results 0,2. Total9 Evidence, all IN1.
First continuation IN4 valid-empty; second IN1 produced two raw Evidence and
one qualifying gain. Capacity was not discarded after the empty result.
Grounding/relevance rejects were not rescued. Terminal insufficient_opportunities,
ready_for_analysis=false / insufficient_research, all five INs blocking.

23 actions: search5/acquire8/extract8/assess2. Durable attempts: search returned5,
retriever returned8, OpenAI returned8; each ordinal1/retryfalse with action and
reservation. Zero actual retries/terminal ambiguous attempts. LLM conservative
charge10 includes two assessment reservations with NO semantic provider call.
Legacy usage reports sufficiency retries2 because executor reconciliation charges
unused assessment reservations with retry=True; these are NOT two OpenAI retries.
Limits unchanged: extraction6+2=8, assessments2/6, search5/5, acquisition8/13,
decisions23/84. No live restart/crash/retry was induced.

Phase labels: initial_search5, initial_acquisition8, initial_extraction6,
continuation_extraction2; readiness/qualification2, adaptive_kernel decisions.
Observer errors0/dropped events0. Qualification observations repeat records and
must not be counted as distinct Evidence.

### Complete persisted citation audit

Read-only audit checked every Evidence Source ID/project, SHA256 raw full Source,
stored/Evidence checksum agreement, full canonical HTML-unescape/NFC/whitespace
normalization, integer Unicode [start,end), exact resolved excerpt and excerpt hash.
No substitute-span search, record mutation or historical requalification.
Source A `ce02e1b2-0a00-409b-8090-7621aa2c0456`, SHA256
`c3397ec5943c53bef4c89e2dbe51ea4b158bb75a2d0bbf631df0fb88915324b9`.
Source B `4176e111-6a7a-44f2-a9eb-f720e1d32a36`, SHA256
`3db24a4c07c05d2fb483327b983d77b76644b2d79f21bb5339b7a54ab7de6061`.

|Evidence ID|Source|Unicode span|Citation|Qualification with Source access|
|---|---|---|---|---|
|0172b7a3-16b2-4a58-b615-6c8a3d894619|A|[3482,3757)|VALID|yes|
|032a7bfd-0df1-41b6-8c32-7d78a70f3ebf|A|[11572,11989)|VALID|no|
|154103b2-436c-41c9-9524-77414ff6377f|A|[4653,4772)|VALID|yes|
|16c98b70-437e-43d6-9c88-a0abdf55a412|A|[4057,4202)|VALID|no|
|2067cacb-3caf-45ad-8757-65b9b58146b8|A|[5253,5543)|VALID|yes|
|257f9764-6f01-4b85-acbe-ad7aabf6f568|B|[9752,10411)|VALID|yes|
|320f442e-75e2-42fb-9e47-97d7a95623dc|B|[10487,10787)|VALID|no|
|39cb9b72-98f5-4f73-8058-94292ed30ed6|A|[9578,10346)|VALID|no|
|7a5610ce-0fe9-4c76-bbd5-1c4e6e80730c|A|[3758,3934)|VALID|yes|

VALID9 / INVALID0 / UNRESOLVABLE0; four citations from chunk offset7500 resolve
against full Source. Five pass correctly wired citation+temporal qualification.
No invalid/unresolvable Evidence qualified. No malformed live fixture manufactured.

### Demonstrated acceptance failure — unchanged product code

application/methods/desk/executor.py constructs ResearchReadinessService without
source_repository. research_readiness_service.py defaults it to None and forwards
it to qualifying_evidence. ARK04 fail-closed citation filtering then cannot resolve
ANY Source. DeskAdapter.qualified() DOES supply the Source repository.
Live qualification-stage telemetry has 14 invalid_citation false rejections
(5 then9 raw Evidence across two assessments), semantic_assessment_calls=0,
all five INs marked no Evidence. Correct read-only qualification yields five for
IN1; controller elsewhere recognizes productive gains4 then1. The false result
is cached against the qualified fingerprint. This proves a readiness integration
defect, not merely bounded insufficiency and not acceptance of invalid citations.
ARK live correctness FAILS despite valid stored spans and bounded continuation.
Four other INs genuinely have zero Evidence; no claim a fix guarantees sufficiency.

### Cost and observability

Owner operational budget USD5; provider-side hard cap not established.
Pre-GO practical estimate USD4.92131 including15% contingency: up to9 design
transport attempts,14 research units,15 downstream attempts,30k input-token
assumption per attempt, configured output caps and12 searches at USD0.016.
Subtotal USD4.2794. This is not a hard input-token/billing guarantee.
Actual path: one design request,8 recorded research OpenAI attempts,5 searches,
zero semantic-assessment/downstream calls. Research output tokens2799; input0
means missing telemetry, not zero consumption; stored estimated_cost_usd=null.
Observed-path conservative allowance retaining maximum9 design attempts and full
output caps: USD1.78246, or USD2.049829 with15%. Actual invoice/balance NOT VERIFIED.
No further provider calls after completion.

### Fresh historical read-only verification

Original databases queried read-only during this resumption. Canonical Evidence
hash is ordered row_to_json aggregate MD5; workflow hash is full row MD5.
All match ARK04 baselines. No historical outcomes recomputed or changed.

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

Final ARK05 Evidence count/hash9/b561fd1f26f08a9086683686ff14bf41;
workflow row25a78ae449ae0cccc04ef1a3af42ae6d.
Analysis/report/review tasks skipped. SQL counts Findings/Insights/Reports/Reviews/
PDF/presentation_jobs all0. Downstream exports, adversarial live citation rejection,
crash recovery and exact billing NOT VERIFIED. No offline suites rerun.
No product/test changes, second scenario, rescue, historical mutation or push.
Only this acceptance evidence is included in the local commit; ignored private
audit/runtime files and existing untracked artifacts remain excluded and preserved.

ARK-05_LIVE_FAILED
