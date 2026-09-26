# PRF-08X — Final Desk live E2E gate

## Final result

**DESK_ARCHITECTURAL_REWORK_REQUIRED**. Infrastructure was recovered and exactly
one authorized live run executed. It failed with zero Evidence before sufficiency;
the detailed final chronology and decision below supersede the intermediate
preflight status, without erasing it. PRF-08W live temporal/relevance cases remain
NOT VERIFIED, not failed or passed by inference from an empty result.

## First attempt: PREFLIGHT BLOCKED; no live attempt

2026-09-26. The authorized scenario has **not started**. No design request,
approval, activation, OpenAI call or Tavily call was made. This is an environment
preflight failure, not evidence of a Desk correctness regression or architectural
research failure. The final substantive Desk decision remains NOT VERIFIED.
Do not interpret this record as completion of the live acceptance scenario.

## Baseline and preserved test evidence

Repository `C:\AI_AGENTS\AI_RESEARCH_OS`, branch
`acceptance/live-desk-research-01`, HEAD
`5508fb1b64878bc0d4f92acdeeccf8cd66861c42`; recorded upstream ahead 26 / behind 0.
Tracked files and index were clean. Existing untracked artifacts were preserved.
V, W and the relevant A frozen-case/acceptance requirements were read.

No offline suite rerun and no product code changed. W's single canonical run
remains **2950 tests total: 2798 passed, 149 skipped, 3 errors**. The subsequent
affected-test corrections and passing selections remain as recorded in W; this
task does not convert that historical full-suite result into a green full run.

## Isolated environment preparation

Created only Compose project `ai_research_os_prf08x`, network
`ai_research_os_prf08x_acceptance`, volumes
`ai_research_os_prf08x_postgres_data` and
`ai_research_os_prf08x_protected_data`. Intended loopback API:
`http://127.0.0.1:18089`. The port was unused before preparation.

Production Dockerfile build from current checkout succeeded:
`ai-research-os-prf08x:5508fb1`, image config
`sha256:320f8bbc1c0070008d5c2ec27fb55e0537c4e58db07328b719f7563308ff0b22`,
manifest list `sha256:1c8595808c46d2c7e92d0ba70e77d57a7bec770c919da6862ca755099f4159d3`.
No product dependency or source change. Private non-secret override
`.env.prf08x-runtime/compose.yml` is ignored by Git and excluded from build context.
Existing dedicated acceptance credential configuration was referenced, not printed,
copied into the image or edited; root `.env` untouched.

Compose prefix used (only X):

```text
docker compose --project-name ai_research_os_prf08x --env-file .env.prf08l -f docker-compose.prf08l.yml -f .env.prf08x-runtime/compose.yml
```

Executed `build api`, `up -d --wait postgres`,
`run --rm --no-deps api python -m alembic upgrade head`,
`run --rm --no-deps owner`, then `up -d --wait --no-build api worker`.
Migrations succeeded through `016_prf06f_pptx` exclusively in the new instance;
owner registration succeeded. New database/user names `prf08l_acceptance` / `prf08l`
are local to that isolated PostgreSQL instance, not historical L's database.
Read-only queries confirmed migration head, **projects=0, workflow_runs=0**.
Provider/UI credential presence was confirmed as booleans only.

## Blocking observations

- Compose's final health wait failed with Docker Engine HTTP 500 on the
  `dockerDesktopLinuxEngine/v1.54/containers/.../json` endpoint.
- Docker read-only inspection/stats commands stalled before returning.
- An in-container HTTP health probe returned HTTP 503.
- Two separate host HTTP probes with explicit 10-second timeout timed out.
  A TCP connection to 18089 alone succeeded; that is not application readiness.
- Latest returned container snapshot showed X PostgreSQL healthy, API healthy,
  worker still `health: starting`. This partial Docker snapshot does not override
  failed host HTTP verification or prove the worker ready.

No Docker restart, historical service stop, replacement database, or product fix
was attempted to force readiness. New X resources remain in place; do not recreate
them or duplicate a project/run on continuation. Inspect existing X state first.
Host memory pressure or another Docker runtime problem is a possibility, not a
proven root cause; no causal diagnosis is asserted from delayed commands alone.

## Budget and remaining preflight

Owner authorization: one scenario, operational limit USD 5.00. Actual task provider
spend: USD 0 (no paid operation dispatched). No provider-side hard monetary cap
claimed. Existing configuration retains extraction 6+2=8, sufficiency 6, analysis 2,
report 2, review 1, total stage cap 24; no search/acquisition/retry increase.
PRF-08S telemetry defaults enabled in current source; live event emission is not
yet verified. Frozen expected brief MD5 remains
`7262e5080260e56109b7e95431ec481c`; no new project exists, so persistence/readback
of that brief in X is **NOT VERIFIED**.

OpenAI Docs was used to fetch the official configured-model pricing page
[GPT-5](https://developers.openai.com/api/docs/models/gpt-5); the
[Tavily pricing page](https://www.tavily.com/pricing) was also fetched.
No GO decision or freshly approved cost envelope was reached. The prior V practical
estimate of USD 4.49530 is historical planning evidence, not an observed X charge
or a guarantee. Runtime health, brief readback and final budget checks must pass
before any future authorized dispatch in this same task.

## Fresh historical integrity

Original containers queried using `BEGIN READ ONLY`; canonical ordered Evidence
row checksum is `md5(string_agg(row_to_json(e)::text,chr(10) ORDER BY id))`;
workflow checksum is `md5(row_to_json(w)::text)`. All eight match W's recorded
counts and both fingerprints; all statuses remain completed. O resides in the
L environment. No outcome was recomputed or historical state changed.

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

## Live acceptance and delivery status

Run ID: none. Funnel, temporal natural cases, relevance, coverage/sufficiency,
analysis/findings/insights/report/review and PDF/PPTX: **NOT VERIFIED / NOT REACHED**.
No refusal or research bottleneck classification can be inferred without a run.
No final Desk product verdict is supported; operational gate failed at preflight.
No PRF-08Y proposed, no second scenario, no rescue, no push.

This partial acceptance record is left uncommitted for continuation; no misleading
"complete final gate" commit is created. Existing source, fixtures, historical
acceptance records and untracked artifacts remain unchanged.

## Resume: infrastructure diagnosis and recovery attempt

2026-09-26. Same HEAD/branch, clean tracked/index, existing artifacts preserved.
Both `desktop-linux` (active) and `default` contexts were inspected. Engine
29.6.1/API 1.55 returned through Docker Desktop 4.80.0; the generic HTTP-500
version-compatibility advice does not establish a version mismatch.

Concrete root-cause layer: Docker Desktop monitor at 15:29:55–15:29:56 UTC
repeatedly reports `main.apiproxy` connecting to internal Engine
`192.168.65.7:2376`: **no route to host**. Worker logs additionally show
`failed to resolve host 'postgres': [Errno -3] Temporary failure in name resolution`.
Worker health checks repeatedly exceed 5 seconds or cannot even start. Worker
was running, OOMKilled=false, subsequently unhealthy. These support classification
**A: local Docker/environment failure**, not a demonstrated product regression
or acceptance configuration defect. The initiating host failure is not proven.
Free Windows physical memory was 243496 KiB of 6127988 KiB (later 480424 KiB);
resource pressure is observed, but not proven causal.

PostgreSQL reported healthy. API reported healthy and one host `/ready` probe
returned 200. However subsequent X network inspection failed with Docker HTTP
500 on `/v1.55/networks/ai_research_os_prf08x_acceptance`; isolated successful
probes are not proof of stable overall readiness.

Recovery used the existing X Compose prefix with `restart api worker`, targeting
only those two containers. API restart acknowledged; worker restart completion
and canonical worker health were not confirmed at this checkpoint. Read-only
X count/worker-health checks were requested but had not completed successfully.
No database/volume removal, reseed, migration, configuration/product change,
historical lifecycle operation or global Docker/WSL restart was performed.
Global backend recovery would interrupt other environments and needs separate
authorization if isolated recovery cannot complete. Inspect existing X state and
pending restart outcome before any further lifecycle action; do not recreate the
acceptance phase or infer successful recovery from an outstanding Docker client.

No new project/design/run or paid request was submitted. Last successful X counts
remain projects=0/runs=0; no fresh count is invented. Cost remains USD 0.
Earlier historical checksum verification is retained, not claimed freshly repeated
during this recovery. No product-code change is shown to be required. No offline
suite rerun, commit or push. Record remains partial and uncommitted.
**PRF-08X_INFRASTRUCTURE_BLOCKED**; Desk product readiness is unclassified.

### Later recovery results in the same continuation

The pending restart then completed successfully for both API and worker (exit 0).
The read-only database query freshly confirmed projects=0 and runs=0, and the
canonical `python -m worker.healthcheck` completed with exit 0. These supersede
the earlier pending-result descriptions, not the original failure chronology.
However, the next Docker container-list and API-container inspection again
returned HTTP 500 through `dockerDesktopLinuxEngine` API 1.55. Runtime source
checksum verification could not complete. Stable overall preflight is therefore
still not established; isolated restart did not resolve the host/backend problem.
No provider calls followed the transient successful worker check. Host-level
Docker recovery is required before continuing; no product-readiness verdict.

## Authorized host recovery and stable GO

The owner subsequently authorized minimum host Docker recovery. Executed exactly
one `docker desktop restart --timeout 120`; it completed with exit 0. No resource
was deleted/recreated and no Docker/WSL configuration was edited. Global restart
temporarily interrupted containers; it did not reset projects or mutate historical
research records. The X worker's `restart: no` left it exited after Engine restart;
the existing X Compose `start worker` restored it. No additional host restart.
An approval-review usage-limit interruption delayed diagnostics; no action or paid
call was dispatched by that rejected request.

Then three spaced checks (10 seconds apart) each returned Engine 29.6.1,
`/health=200`, `/ready=200`, and successful worker-side DNS resolution of `postgres`.
Canonical `python -m worker.healthcheck` exited 0. All X services healthy. Recent
monitor-log tail contained no repeated routing/DNS/500 matches; subsequent Docker
operations and final `/ready` remained successful throughout live execution.
This is observed stability over this window, not a guarantee against future faults.
Infrastructure classification remains local Docker/backend routing/DNS failure;
the initiating host cause is not proven. No evidence warrants a product fix.

Runtime SHA256 matches the checkout:

- temporal_scope.py: `499fe05f460df4b170375051dd28764a530f281e5f089503742a99ce8ab1d68c`
- relevance_validation.py: `252a5b4b3775a6cb3a75131f62ebf849be8f6402762c112d8a5cf84aa22e7276`
- research_funnel_telemetry.py: `c3d9001852b27cd4ca2a24a7a4e82e27cfd10f428c29bde8516d3de0a82d00b7`

HEAD and tracked/index remained unchanged. Source configuration retained live
GPT-5/Tavily, existing stage/search/acquisition/retry limits, 6 initial plus 2 reserve.
Credential presence checked only as booleans. The stable baseline again had
projects=0/runs=0; no duplicate project or activation from earlier attempts.

## Sole design and activation

Created project `ff965197-ad52-4758-b140-7c3526d51f8d` via normal UI forms, named
`PRF-08X - Final Desk Live Gate`. Read historical T brief without modification and
submitted it through the supported brief form. Persisted PostgreSQL
`md5(brief::text)` = `7262e5080260e56109b7e95431ec481c` exactly.

One design POST returned 200; no client retry. Design
`e0ee44ff-ff8c-4a31-bacb-787183fe56ba` passed generation validation, DRAFT,
6 RQs/6 INs: scale/change, regional distribution, site types, dated operator
announcements, utilization, and limitations/gaps respectively. Each RQ has its IN;
UK/50-kW scope and fixed observation/publication boundaries remain. Announcements
are not treated as inventory; comparability and utilization limits are explicit.
An assumption of two independent count sources is not proof they exist. IN6's
post-review synthesis wording is retained, not manually rewritten into a query.

Already-authorized approval of that exact design returned 200, then one activation
returned 200. Run **`c2500ca8-093d-5017-9d9b-994a0a410d1b`**. No second design/run,
manual rescue, recomputation, altered brief, queries, candidates, Evidence or gates.

## Terminal state and funnel

Task-record span 2026-09-26 17:10:21.154798–17:11:38.633329 UTC,
77.478531 seconds, excluding design. Source collection completed; Evidence
extraction failed; readiness, analysis, report and review skipped. Workflow status
**failed**, not a completed conservative sufficiency refusal.

Persisted extraction diagnostics: `failure_classification=no_candidates`,
`budget_stop_reason=evidence_initial_partition_exhausted`, raw candidates 0,
grounding/provenance rejections 0, six completed inner calls, zero exceptions,
six `valid_empty_result`, zero recorded retries. The aggregate
`extractor_successes=0` does not mean six transport failures: telemetry explicitly
classifies six valid-empty model responses.

The existing `EvidenceExtractionService` zero-result boundary raises
`EvidenceExtractionError: No grounded evidence extracted for workflow run ...`
when `extracted == 0 and allow_empty_failure`. This matches the persisted failure:
readiness is skipped, so the two reserved continuation slots are never entered.
No new code was applied to produce this diagnosis, and no bypass was attempted.

Journal: 188 events, zero drops/observer errors; 12 successful searches, four
empty lists, 24 candidate observations/decisions, 8 fetches (7 acquired, 1 truncated),
one content-alias dedup, 6 extraction attempts, zero Evidence/qualification events.
24 decisions: 8 selected, 12 acquisition-cap skips, 2 unsupported-URL skips,
2 duplicate-URL skips. Eight persisted Source rows include one duplicate-content
pair and one truncated YouTube page; row count is not independent useful sources.

| IN | Searches | Returned | Selected | Extraction / valid-empty | Evidence |
| --- | ---: | ---: | ---: | ---: | ---: |
| IN1 scale/change | 2 | 3 | 1 | 1 / 1 | 0 |
| IN2 regional | 2 | 3 | 1 | 1 / 1 | 0 |
| IN3 site types | 2 | 3 | 2 | 1 / 1 | 0 |
| IN4 announcements | 2 | 6 | 1 | 1 / 1 | 0 |
| IN5 utilization | 2 | 6 | 3 | 2 / 2 | 0 |
| IN6 gaps | 2 | 3 | 0 | 0 / 0 | 0 |
| Total | 12 | 24 | 8 | 6 / 6 | 0 |

Ordered attempts, all initial chunk 0 and valid-empty:

1. IN1: Zapmap reporting-metrics article (`ed8a98c5`).
2. IN2: Eco Experts regional-disparity article (`c3632295`).
3. IN3: Statista country/type page (`8aa1016a`). Its www alias was content-deduped;
   only one equivalent body was extracted, not two independent lineages.
4. IN4: US driveelectric.gov infrastructure playbook (`ad7e18cf`).
5. IN5: truncated YouTube source (`14a66f9f`).
6. IN5: official July network statistics (`6c69b6e3`), scoped to utilization.

ONS device statistics were acquired but never extracted. 84 planned work items,
78 budget-skipped; telemetry additionally contains three duplicate-content chunk
skips. These are work-item counts, not additional calls. Initial partition used
6/6; reserve used 0/2; total remains 6/8. No limit increased.

## Bottleneck and final Desk decision

Classification **MIXED**, dominated by QUERY_STRATEGY / PROVIDER_CANDIDATE_QUALITY /
CANDIDATE_SELECTION / EXTRACTION and the zero-Evidence continuation boundary.

All 12 exact query texts/hashes are stored, with six baseline/localized intent
pairs. They carry long concatenated RQ/IN/aspect text, including methodological
words. IN6 asks about unsupported/dependent questions and returned a general
dictionary, a dependency immigration-law page and a legal Evidence dictionary.
IN4 returned fuel-cell deployments, unrelated disclosures and Indian AI data-center
material; its selected fallback was a US playbook. IN3 spent two acquisitions on
identical Statista www/non-www content. IN5 acquired capacity/device statistics
and YouTube for a utilization need; July statistics were extracted only for IN5.
No counterfactual useful yield is claimed for another scope or unprocessed chunk.

This is not proof of genuine public-data scarcity. The recorded strategy spends
bounded opportunities on semantic/geographic mismatches, and all-empty extraction
prevents entry to already-reserved continuation. W did not cause the emptiness
through rejection: there were **zero raw candidates**, so its relevance boundary
had nothing to evaluate. There is no demonstrated W correctness regression.

Final decision: **DESK_ARCHITECTURAL_REWORK_REQUIRED**, not E2E accepted and not
research-integrity accepted by vacuous absence of Evidence. Evidence supports a
systemic discovery/selection/extraction/continuation problem; this final-series
task does not prescribe another PRF-08 patch or create PRF-08Y.

## PRF-08W natural cases and downstream

Pre-window rejection, in-window quarter normalization, post-cutoff exclusion,
publication-only/unknown temporal conservatism: **NOT VERIFIED** (no Evidence
or qualification events). Target-IN/cross-IN retention and unrelated-topic
rejection by W: **NOT VERIFIED** (no candidate reached the guard). Zero unrelated
stored facts is not credited as a live relevance-guard test.

No readiness verdict exists; do not fabricate `ready_for_analysis=false` as an
executed sufficiency result. Coverage zero for all six INs. One run in database;
Evidence, Findings, Insights, Reports, Review results, PDF deliverables and
presentation jobs all zero. Analysis/review/citation/source-binding/download
acceptance NOT REACHED. No deliverables manufactured. Run row MD5:
`cc468d87e5efe063634cfbd4b75afd31`. Empty Evidence aggregate MD5 is NULL, not a
fabricated checksum of nonexistent rows.

## Budget, integrity and delivery

Before design GO, retained practical estimate using previously checked tariffs
(GPT-5 USD 1.25/10 per million input/output tokens; Tavily basic USD .008/search):
19 stage calls plus up to 3 design calls, assuming 60k input/8192 output each,
18 searches: USD 3.59624 base, **USD 4.49530 with 25% contingency**. These are
conservative planning assumptions, not a hard cap or measured bill. Actual stage
output limits are no greater than the 8192 allowance; the default is 4096.

Observed research: 6 logical extraction LLM calls, 132 reported output tokens,
12543 ms aggregate model time, zero recorded retries, 12 basic searches.
One design HTTP request; underlying design call/token usage not independently
established. With up to 3 assumed design calls and the same allowance, revised
practical estimate is USD 1.50828 base / **USD 1.88535 with contingency**.
Actual charge, input tokens and SDK-internal billed retries are UNAVAILABLE.
Persisted zero input/reasoning counters are not proof of zero billed tokens.
No further paid operations after the terminal result; USD 5 authorization unchanged.

After host restart, all eight historical B/D/F/H/J/O/T/V counts and both checksum
columns above were freshly verified again, exactly matching. No outcomes recomputed
or repaired. No historical data/artifact deleted or changed. Root env and existing
acceptance credentials/configuration unchanged. No product-code/test changes or
offline-suite rerun. OpenAI Docs pricing verification supported the estimate only.

Only this reviewed acceptance record is intended for the local commit
`PRF-08X complete final Desk live E2E gate`. No secret/env/runtime dumps or provider
payloads included; private override remains ignored, previous untracked artifacts
preserved. No push. X remains available for read-only inspection at:
`http://127.0.0.1:18089/ui/research/c2500ca8-093d-5017-9d9b-994a0a410d1b/overview`.
