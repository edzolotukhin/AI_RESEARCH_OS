# PRF-08T — Diagnostic live research funnel

**Final: PRF-08T_DIAGNOSIS_COMPLETE. Primary diagnosis: MIXED.** One run
`168e19c2-e779-5ccc-a965-11f38054b1bf` completed with insufficient research,
not a successful report. No rerun, rescue, query/Evidence edit or product fix.
The preflight checkpoint below records the earlier pause; the owner subsequently
explicitly approved this exact design and one activation, as recorded below.

## Preflight checkpoint — awaiting specific design approval

Initial HEAD `cb4a28c62bd826085de390cb3c74ceab73608e6c`, branch
`acceptance/live-desk-research-01`, tracked/index clean, recorded upstream
ahead 22 / behind 0. No offline suite repeated and no product code changed.

Exactly one design-generation HTTP request succeeded (200). No approval or
research activation has been submitted. Do not create a second design/project
when continuing. PRF-08A requires owner confirmation of the specific DRAFT design
before approval/activation; this checkpoint is not a failed research result.

- Project: `8d342396-dc6d-4cab-a18e-1dd2e4625d87`.
- Design: `f7389c0e-4200-498b-99df-3960cfe4b137`.
- UI: http://127.0.0.1:18087/ui/projects/8d342396-dc6d-4cab-a18e-1dd2e4625d87/design
- Persisted frozen brief MD5: `7262e5080260e56109b7e95431ec481c`.
- Five RQs / five INs: scale/change; regional/site-type distribution; operator
  disclosures; utilization distinct from capacity; definitions/dependencies/gaps.
  Each material RQ has IN coverage. UK, 50 kW+ and fixed observation period remain
  explicit. Normal generation validation passed. Owner confirmation is pending.

## Isolated environment

New Compose project `ai_research_os_prf08t`, network
`ai_research_os_prf08t_acceptance`, dedicated volumes
`ai_research_os_prf08t_postgres_data` and `ai_research_os_prf08t_protected_data`.
No historical database copied. New PostgreSQL instance retains the established
database/user names `prf08l_acceptance`/`prf08l` within its separate container;
these names do not denote the historical instance.

Current-source image `ai-research-os-prf08t:cb4a28c`, image config identity
`sha256:12b9c1228cf623da87204f122e4f9ff948a812a69387a734ec919a5421b2f0e9`.
API, worker and PostgreSQL healthy; readiness HTTP 200. New database migrated
through `016_prf06f_pptx`. API telemetry module SHA256 matches the worktree:
`c3d9001852b27cd4ca2a24a7a4e82e27cfd10f428c29bde8516d3de0a82d00b7`.
Journal enabled by default. Credentials checked for presence only.

Startup used the established non-secret Compose recipe with a private ignored
override (image and loopback port only), existing local credential file read
without changing it, and explicit new project name:

```text
docker compose --project-name ai_research_os_prf08t --env-file .env.prf08l -f docker-compose.prf08l.yml -f .env.prf08t-runtime/compose.yml
```

Build/API/worker never replaced PRF-08L or other historical services. The override
is excluded from Git/build context by `.env.*`. No credentials are in this record.
The existing historical project's activation is idempotent and returns its
existing run, so it was not reused to manufacture a new attempt. A new project
was prepared through normal UI forms using the unchanged historical frozen brief.

## Operational budget

Owner authorization: USD 5 total. GPT-5, stage-call cap 24; Evidence 8 (existing
6 initial + 2 continuation), sufficiency 6, analysis 2, report 2, review 1;
one gap round, one attempt/query/source per gap; planner one semantic attempt
with existing bounded structured recovery. Worker automatic restart disabled.
No call-budget increase or model change.

Official [GPT-5 pricing](https://developers.openai.com/api/docs/models/gpt-5)
and [Tavily pricing](https://www.tavily.com/pricing) were re-opened during
preflight using OpenAI Docs guidance for the model. Practical envelope retains
the prior conservative assumptions: 19 stage calls plus up to 3 planner calls,
60k input tokens and 8192 output tokens per call, 18 basic searches at USD 0.008.
GPT-5 input/output rates: USD 1.25/10 per million. Base USD 3.59624, with 25%
contingency USD 4.49530. This is an operational estimate, not a hard input cap,
measured bill or mathematical monetary cutoff; bounded SDK retries may affect
billing. Reassess before activation if observed errors/usage change the envelope.

One successful design HTTP request does not prove one underlying LLM call.
Actual design billing/input/output totals are not established by the HTTP result.
No Tavily request or research extraction was requested at this checkpoint.

## Historical integrity

Fresh read-only checks of original PRF-08B/D/F/H/J/O matched their recorded
Evidence counts and ordered-row MD5, plus workflow-row MD5. No historical
outcome was recomputed or mutated. All six remain completed.

| History | Evidence | Evidence MD5 | Workflow MD5 |
| --- | ---: | --- | --- |
| B | 13 | 076646d8ec25f2a7d682ec420896af95 | 00ef1aa66c3b6194ba39d1a01c066de7 |
| D | 33 | 84ce68280d94941b19414a46893f2868 | 01e242df696ac51050788442c6249471 |
| F | 22 | 7937d0745c8c03a67ffc045c9fbbb6f5 | 3eedf9afcfbd4b61b1eaa672bc36f3f8 |
| H | 24 | 3866b66b19d3ec31ff6210fafa297922 | 60fd6bb7a92d1c36f0bb04073d567e47 |
| J | 27 | 299e88abe27b9363fd623f5f9e034eac | 2e66c4ab0dbf4365877c97e61e053576 |
| O | 1 | 135c9ec526cdd2672bd61b52e7902f7d | 9dcb9c3b7526dd0eeb2a625876460c28 |

## Gates unperformed at the earlier approval checkpoint

Research funnel/query/candidate/extraction/qualification diagnosis, natural
deduplication/lineage, research sufficiency and downstream documents: NOT TESTED.
No dominant bottleneck is assigned without a research run. Resume this exact
project/design after owner confirmation; do not generate again. No push.

## Sole activation and natural result

After explicit owner confirmation, normal `/design/approve` with the existing
design ID and exactly one `/methods/DESK/activate` both returned HTTP 200.
Final database run count is 1. Result UI:
http://127.0.0.1:18087/ui/research/168e19c2-e779-5ccc-a965-11f38054b1bf/overview

Workflow completed; readiness false, termination
`evidence_remediation_budget_exhausted`. Task creation 12:40:49.697704 to final
readiness update 12:42:18.382385 UTC, 26 September 2026: 88.684681 seconds
(task-record span, not provider duration). Analysis/report/review were skipped.
Findings, insights, reports, reviews and presentation jobs: all zero. No downstream
generation requested. No second design, activation or manual rescue occurred.

The final existing checkpoint contains 175 journal events, sequence 175,
zero dropped events and zero observer errors. Eleven search events reconcile
to eleven successful provider-result events (three empty arrays), 22 returned
candidate observations and 22 decisions. Nine acquisition attempts/results,
eight extraction starts/results, five produced Evidence IDs. Forty-six
qualification observations include repeated assessments: they are not 46 facts.
Per-IN counts below use the final outcome for each unique Evidence ID.

## Per-IN accounting

IN1 scale/change; IN2 regional/site types; IN3 operator disclosures;
IN4 utilization; IN5 definitions/dependencies. Discovery counts include repeated
URLs across searches, not independent sources. Extraction attribution is the
actual primary target; all eight scopes were single-IN. No cross-IN yield.

| IN | Searches | Returned | Selected | Skipped reasons | Fetches / successes | Extraction attempts / valid-empty / invalid-failure | Produced target / cross | Qualifying / temporal rejected |
| --- | ---: | ---: | ---: | --- | ---: | --- | ---: | ---: |
| IN1 | 2 | 3 | 1 | coverage-complete 2 | 1 / 1 | 1 / 0 / 0 | 2 / 0 | 1 / 1 |
| IN2 | 2 | 6 | 2 | coverage-complete 2; acquisition-budget 2 | 2 / 2 | 3 / 2 / 0 | 3 / 0 | 1 / 2 |
| IN3 | 3 | 7 | 3 | coverage-complete 2; exhausted 1; acquisition-budget 1 | 3 / 2 | 2 / 2 / 0 | 0 / 0 | 0 / 0 |
| IN4 | 2 | 3 | 1 | coverage-complete 2 | 1 / 1 | 1 / 1 / 0 | 0 / 0 | 0 / 0 |
| IN5 | 2 | 3 | 2 | coverage-complete 1 | 2 / 1 | 1 / 1 / 0 | 0 / 0 | 0 / 0 |
| Total | 11 | 22 | 9 | 13 skips | 9 / 7 | 8 / 6 / 0 | 5 / 0 | 2 / 3 |

Nine fetches comprise seven initial plus one per continuation. No configuration
increase was made; the configured source budget is applied by the existing
initial/targeted acquisition paths, not asserted to be eight cumulative fetches.
The paid extraction partition is exactly six initial plus two continuation.
Two fetch failures have safe category `http_error`: TCPalm US press release
and StackOverflow. Seven acquired sources have seven distinct normalized content
identities. Duplicate-content skips: zero for every IN. One repeated URL was
skipped as already exhausted (IN3), not counted as a successful content-dedup case.
Four planned chunks were skipped due to extraction budget: IN1 chunk 1,
IN2 original chunk 2, IN2 continuation chunk 1, IN3 continuation chunk 1.

## Query diagnosis

All eleven recorded queries have `query_exact=true`, no redaction/truncation.
Baseline/localized pairs repeat identical text for IN1/3/4/5; arm differences
are intentional configuration, not proof of identical provider parameters.
Localized IN1/4/5 returned zero; localized IN3 returned one GOV.UK candidate.
IN2 continuation exactly repeats its initial text/hash despite different results.
IN3 continuation adds only `operator name` to the existing query.

| IN | Semantics / entity / geography | Temporal preservation |
| --- | --- | --- |
| IN1 | UK, 50 kW+, counts and metric definitions explicit, but long concatenated question/aspects | Explicit Jan 2025–July 2026 plus publication allowance retained |
| IN2 | UK regions/site types and 50 kW+ explicit; long concatenation | Only `Same observation periods as IN1` — not a self-contained date window |
| IN3 | UK, deployments/operator/retail, 50 kW+ retained; compressed market phrase lacks clear EV context | Explicit through-1-July-2026 constraint lost in both initial and targeted provider text |
| IN4 | UK, 50 kW+, utilization metrics and method explicit; long capacity/aspect wording | Explicit 2025–July-2026 window retained |
| IN5 | UK and charger/device terms retained, but no explicit EV/50-kW anchor in projection; generic unsupported/definitions vocabulary | Only `As referenced by sources used in IN1–IN4`; static definitions do not always need a date, but feed/cutoff intent is not self-contained |

Thus PRF-08R's repeated-query and missing-explicit-window observations recur for
specific INs, not universally. No query was edited, and this single run cannot
prove a shorter/alternative query would have succeeded.

## Candidate diagnosis and primary classification

**MIXED**, with demonstrated query-fidelity weaknesses, poor/off-topic candidate
returns, source-coverage early stopping and temporal-metadata qualification loss.
No single-stage counterfactual is proven. In particular, six empty extractions
are not sufficient evidence of an extractor defect: much selected material is
not appropriate UK factual evidence for the target IN.

- IN1 selected the official July statistics. Unselected IEA 2026 looks topically
  relevant by URL but was not acquired, so its UK 50-kW period coverage is unknown.
- IN2 initially selected regional funding material, which yielded two empty
  chunks; other initial URLs included commercial charger costs and butterfly
  abundance. Continuation selected the official January report and produced
  Evidence. Zest/IEA alternatives were budget-skipped; usefulness unverified.
- A **demonstrated delayed opportunity** exists: the exact January GOV.UK URL
  was already returned under IN3 localized search and skipped for
  `lower_priority_coverage_complete`; later it was acquired under IN2 and
  produced three facts, one temporally qualifying. This proves opportunity
  presence/delay, not that it could close IN3 or all regional/site-type gaps.
- IN3 selected a failed US-market press release, its acquired US-market
  publication on another site, then a Tesla/Biden-plan article. No target
  Evidence emerged. These URLs visibly misalign with UK operator coverage;
  the acquired texts' empty results are consistent with conservative extraction.
- IN4 returned general capacity-utilization pages; a legal dictionary was
  selected and yielded empty, not a measured UK charger-utilization dataset.
- IN5 returned software support/database pages. The acquired Dremio release
  notes yielded empty. No observed viable charging-definitions candidate in that
  returned set; this is not evidence that such sources do not exist publicly.

The candidate ledger below records all decisions; URLs alone are not proof of
unacquired content usefulness. Acquisition failures (2/9) and duplicate content
are not dominant. Selection stopped at formal source coverage while Evidence
coverage was absent; the preserved observation does not license changing it here.

## Qualification, lineage and sufficiency

Five persisted facts: two for IN1, three for IN2. Final temporal results:

- `e7a29c65-e7e8-476e-a01e-3433ceb4fb50`: IN1 rapid-charger count;
  `applicable_unresolved`. Its canonical excerpt explicitly says 1 July 2026,
  but metadata `observation_period` is absent. Existing `observation_eligibility`
  requires that field before checking grounded dates. This is a demonstrated
  metadata/qualification loss, not proof that the source lacked a date.
- `f1da3769-9d59-467c-b3b3-ebbc5b0e6af0`: IN1 feed/method statement;
  `applicable_satisfied`, period 1 July 2026.
- `ca703b63-baac-4cea-8c8c-e4c1569b82c4`: IN2 total chargers/devices ratio;
  `applicable_satisfied`, period 1 January 2026. Not a regional/site-type breakdown:
  temporal qualification is not complete substantive IN coverage.
- `aeaafe1c-577b-4a81-937d-c2a73be28f62`: power-band labels; and
  `c9b56836-034a-4790-a359-661debf0f0e1`: pre-2025 estimates/feed caveat;
  both IN2 `applicable_unresolved`, missing observation-period metadata.
  A static-methodology exception is need/claim dependent, not automatically
  applied to every descriptive statement assigned to a quantitative IN.

No `applicable_failed` post-cutoff rejection occurred. One additional candidate
was rejected for grounding during initial IN1 extraction before persistence.
No invalid-output/failure extraction or structured retry occurred. Final states:
IN1 partial (one qualifying stream), IN2 insufficient (one), IN3/4/5 missing (zero).
The product did not mistake these facts for full sufficiency.

Four Evidence rows declare established origin `Zapmap`; one has no lineage.
There are no harmless naming variants here: PRF-08K normalization variant case
NOT VERIFIED live. Seven successful sources have distinct content identities;
TCPalm failed before content comparison with the similar Aberdeen press release.
PRF-08P same-content alias prevention is therefore NOT VERIFIED live, not a
manufactured PASS. No historical outcomes were recomputed.

## Usage and cost reconciliation

Research: 10 logical LLM calls = 8 Evidence + 2 sufficiency; 0 recorded retries;
1628 output tokens (1340 + 288), 30.715 seconds summed model time. Eleven
logical Tavily searches; nine acquisition attempts. Input/reasoning token zeros
in this usage path are not proof of zero billed input; actual bill is unavailable.
SDK transport retry billing is not independently observable.

Using the same preflight assumptions/prices, observed research output plus assumed
60k input/call and eleven searches gives USD 0.85428 base / 1.06785 with contingency.
Adding the conservative design allowance USD 0.58845 gives **USD 1.65630 estimated
whole scenario**. Using the full 8192 output allowance for each research call
instead gives **USD 2.65995 including design and contingency**. Neither is a
measured provider charge; both remain below the USD 5 operational envelope.
No further paid calls followed terminal refusal.

## Final preservation and delivery

New-run Evidence: 5, ordered-row MD5 `3c15be644e3a45f47955bc1da2bfd412`;
workflow-row MD5 `eab5db1fd4860e5011a91c6fefed1e53`.
The historical table above matched fresh read-only checks; no historical DB or
record changed. Existing untracked artifacts preserved; root environment file
unchanged. Only this acceptance document is a Git deliverable. Private local
Compose/audit helpers remain ignored and are not product fixes. No tests rerun,
no schema/product edit, no live retry, no push. Diagnostic completeness is not
research-quality or PDF/PPTX acceptance.

## Exact executed-query ledger

### Call 1: IN1, initial_search, baseline

What is the documented scale of the UK public 50 kW+ charging network at 2025 and latest 2026 cut-offs, and how has it changed while preserving each source’s metric and definition? publicly accessible chargers rated least Count of public 50 kW+ chargers at documented 2025 and latest 2026 observation cut-offs by source, with the exact metric (chargers/devices/sites), inclusion rules, data feed, and cut-off date. count value metric definition inclusion exclusion rules data feed reference observation cutoff date United Kingdom Observations dated between 1 Jan 2025 and 1 Jul 2026; publications up to 25 Sep 2026 if reporting fixed period

Event 168e19c2-e779-5ccc-a965-11f38054b1bf:f1; query SHA256 cec170477dc701847b20daa8c786ea2e8d6a40502bfe60760c8ed38d348ae70b.

### Call 2: IN1, initial_search, localized

What is the documented scale of the UK public 50 kW+ charging network at 2025 and latest 2026 cut-offs, and how has it changed while preserving each source’s metric and definition? publicly accessible chargers rated least Count of public 50 kW+ chargers at documented 2025 and latest 2026 observation cut-offs by source, with the exact metric (chargers/devices/sites), inclusion rules, data feed, and cut-off date. count value metric definition inclusion exclusion rules data feed reference observation cutoff date United Kingdom Observations dated between 1 Jan 2025 and 1 Jul 2026; publications up to 25 Sep 2026 if reporting fixed period

Event 168e19c2-e779-5ccc-a965-11f38054b1bf:f6; query SHA256 cec170477dc701847b20daa8c786ea2e8d6a40502bfe60760c8ed38d348ae70b.

### Call 3: IN2, initial_search, baseline

How is the 50 kW+ network distributed across UK regions and retail/destination/en-route site types where comparable public evidence exists? publicly accessible chargers rated least Regional breakdowns and site-type distributions (retail/destination/en-route) of 50 kW+ chargers where the same source provides comparable definitions across periods. regional counts regional share site type classification scheme comparability notes period alignment UK national and devolved/regional units Same observation periods as IN1 or clearly stated if different

Event 168e19c2-e779-5ccc-a965-11f38054b1bf:f8; query SHA256 cf12125e31ce8a69c35bc21a727ab2612d661423b95c929cb4bc12011ba9a424.

### Call 4: IN3, initial_search, baseline

publicly accessible chargers rated least United Kingdom Dated operator disclosures naming 50 kW+ deployments or retail partnerships, tagged as announcement, opening, under construction, or operational claim

Event 168e19c2-e779-5ccc-a965-11f38054b1bf:f13; query SHA256 29a741e740dcf576beae06c284283b8c68e5351cc2edaf145e959130229b301d.

### Call 5: IN3, initial_search, localized

publicly accessible chargers rated least United Kingdom Dated operator disclosures naming 50 kW+ deployments or retail partnerships, tagged as announcement, opening, under construction, or operational claim

Event 168e19c2-e779-5ccc-a965-11f38054b1bf:f18; query SHA256 29a741e740dcf576beae06c284283b8c68e5351cc2edaf145e959130229b301d.

### Call 6: IN4, initial_search, baseline

What publicly observable utilization or use signals exist for 50 kW+ chargers, with disclosed method and scope, and how are these distinct from installed capacity? publicly accessible chargers rated least Publicly reported utilization metrics for 50 kW+ (e.g., session counts, dwell, occupancy, kWh throughput) with clear method, scope, sampling, and period distinct from capacity figures. utilization metric definition numerator denominator sample scope observation period data collection method separation from capacity United Kingdom; accept UK-wide or regional samples with scope noted Observations within 2025–1 Jul 2026; publications allowed to 25 Sep 2026 if fixed period is explicit

Event 168e19c2-e779-5ccc-a965-11f38054b1bf:f21; query SHA256 58c4040492849d10ef1aceea4bdddda724402e8307c51754830e2316036f589b.

### Call 7: IN4, initial_search, localized

What publicly observable utilization or use signals exist for 50 kW+ chargers, with disclosed method and scope, and how are these distinct from installed capacity? publicly accessible chargers rated least Publicly reported utilization metrics for 50 kW+ (e.g., session counts, dwell, occupancy, kWh throughput) with clear method, scope, sampling, and period distinct from capacity figures. utilization metric definition numerator denominator sample scope observation period data collection method separation from capacity United Kingdom; accept UK-wide or regional samples with scope noted Observations within 2025–1 Jul 2026; publications allowed to 25 Sep 2026 if fixed period is explicit

Event 168e19c2-e779-5ccc-a965-11f38054b1bf:f26; query SHA256 58c4040492849d10ef1aceea4bdddda724402e8307c51754830e2316036f589b.

### Call 8: IN5, initial_search, baseline

Which commercially relevant questions remain unsupported or are definition-dependent given differing charger/device/connector/site terms, data feeds, and cut-off dates? publicly accessible chargers rated least Documentation of divergent definitions (charger/device/connector/site), data feed dependencies, and cut-off misalignments that constrain comparability or leave questions unsupported. term definitions dependency on feeds cutoff alignment comparability risks unsupported question catalog United Kingdom As referenced by sources used in IN1–IN4

Event 168e19c2-e779-5ccc-a965-11f38054b1bf:f28; query SHA256 34c10c498c09067275006bcd6c94cfa4fcd0e5f7fd93bac7a51d546bdeba2008.

### Call 9: IN5, initial_search, localized

Which commercially relevant questions remain unsupported or are definition-dependent given differing charger/device/connector/site terms, data feeds, and cut-off dates? publicly accessible chargers rated least Documentation of divergent definitions (charger/device/connector/site), data feed dependencies, and cut-off misalignments that constrain comparability or leave questions unsupported. term definitions dependency on feeds cutoff alignment comparability risks unsupported question catalog United Kingdom As referenced by sources used in IN1–IN4

Event 168e19c2-e779-5ccc-a965-11f38054b1bf:f33; query SHA256 34c10c498c09067275006bcd6c94cfa4fcd0e5f7fd93bac7a51d546bdeba2008.

### Call 10: IN2, continuation_search, baseline

How is the 50 kW+ network distributed across UK regions and retail/destination/en-route site types where comparable public evidence exists? publicly accessible chargers rated least Regional breakdowns and site-type distributions (retail/destination/en-route) of 50 kW+ chargers where the same source provides comparable definitions across periods. regional counts regional share site type classification scheme comparability notes period alignment UK national and devolved/regional units Same observation periods as IN1 or clearly stated if different

Event 168e19c2-e779-5ccc-a965-11f38054b1bf:f99; query SHA256 cf12125e31ce8a69c35bc21a727ab2612d661423b95c929cb4bc12011ba9a424.

### Call 11: IN3, continuation_search, baseline

publicly accessible chargers rated least United Kingdom Dated operator disclosures naming 50 kW+ deployments or retail partnerships, tagged as announcement, opening, under construction, or operational claim operator name

Event 168e19c2-e779-5ccc-a965-11f38054b1bf:f136; query SHA256 0b818d52cbc00577a64299b6bda478cb4f2a1af4cb1f982fb5898075aa89dbda.

## Candidate ledger

IDs below omit the common run UUID prefix. All URLs are telemetry-safe retained values.

| Candidate | IN | URL | Decision |
| --- | --- | --- | --- |
| f1:c1 | IN1 | https://www.gov.uk/government/statistics/electric-vehicle-charging-infrastructure-statistics-1-july-2026/public-electric-vehicle-charging-infrastructure-statistics-1-july-2026 | selected |
| f1:c2 | IN1 | https://www.youtube.com/watch?v=-2SWgVznryI | lower_priority_coverage_complete |
| f1:c3 | IN1 | https://www.iea.org/reports/global-ev-outlook-2026/electric-vehicle-charging-chap-6-and-10 | lower_priority_coverage_complete |
| f8:c1 | IN2 | https://klitv.com/blog/regional-ev-charger-funding | selected |
| f8:c2 | IN2 | https://commercialevcharger.co.uk/commercial-ev-charger-cost | lower_priority_coverage_complete |
| f8:c3 | IN2 | https://www.academia.edu/121341907/A_new_method_for_calculating_butterfly_abundance_trends_for_small_regional_areas | lower_priority_coverage_complete |
| f13:c1 | IN3 | https://www.tcpalm.com/press-release/story/15446/universal-ev-chargers-scales-driver-first-dc-fast-charging-in-2025-commissioning-320-live-ports-across-key-us-markets | selected |
| f13:c2 | IN3 | https://www.cbtnews.com/tesla-commits-to-opening-up-7500-chargers-to-other-evs-under-biden-plan | lower_priority_coverage_complete |
| f13:c3 | IN3 | https://www.aberdeennews.com/press-release/story/127645/universal-ev-chargers-scales-driver-first-dc-fast-charging-in-2025-commissioning-320-live-ports-across-key-us-markets | selected |
| f18:c1 | IN3 | https://www.gov.uk/government/statistics/electric-vehicle-public-charging-infrastructure-statistics-january-2026/electric-vehicle-public-charging-infrastructure-statistics-january-2026 | lower_priority_coverage_complete |
| f21:c1 | IN4 | https://zenboxinfinity.com/capacity-utilization-analysis | lower_priority_coverage_complete |
| f21:c2 | IN4 | https://financedictionarypro.com/corporate-finance/working-capital-and-operations/capacity-management/capacity-levels-and-utilization/capacity-utilization | lower_priority_coverage_complete |
| f21:c3 | IN4 | https://www.lawinsider.com/dictionary/capacity-utilization-factor | selected |
| f28:c1 | IN5 | https://help.mews.com/s/article/data-json-incorrect-or-unsupported-device | lower_priority_coverage_complete |
| f28:c2 | IN5 | https://stackoverflow.com/questions/72711770/flyway-unsupported-database-mysql-8-0 | selected |
| f28:c3 | IN5 | https://docs.dremio.com/current/release-notes/unsupported-releases | selected |
| f99:c1 | IN2 | https://www.gov.uk/government/statistics/electric-vehicle-public-charging-infrastructure-statistics-january-2026/electric-vehicle-public-charging-infrastructure-statistics-january-2026 | selected |
| f99:c2 | IN2 | https://www.zest.uk.com/news/how-many-ev-charging-stations-are-in-the-uk | acquisition_budget_unavailable |
| f99:c3 | IN2 | https://www.iea.org/reports/global-ev-outlook-2025/electric-vehicle-charging | acquisition_budget_unavailable |
| f136:c1 | IN3 | https://www.aberdeennews.com/press-release/story/127645/universal-ev-chargers-scales-driver-first-dc-fast-charging-in-2025-commissioning-320-live-ports-across-key-us-markets | already_exhausted |
| f136:c2 | IN3 | https://www.cbtnews.com/tesla-commits-to-opening-up-7500-chargers-to-other-evs-under-biden-plan | selected |
| f136:c3 | IN3 | https://sarvada.ai/startups-new-economy-insurance/ev-charging-network-operator-insurance-india-2026 | acquisition_budget_unavailable |

## Exact ordered extraction ledger

| Ordinal | Phase | Target | Source ID | Content identity | Chunk | Result | Target / cross Evidence |
| ---: | --- | --- | --- | --- | ---: | --- | --- |
| 1 | initial_extraction | IN1 | ea4dc5c5-1de5-492b-ad25-5d4bb73b94e9 | content-v1:22e538e5c320c493795df609356ed0c4e37d1ea6d80222436f9d745502e308dc | 0 | success | 2 / 0 |
| 2 | initial_extraction | IN2 | 4e35200c-f3c3-4a5d-ae5c-570bf830de29 | content-v1:ff3fac97b981281ae75dc3fa847ceb5ce6487b8b2b12e78289db557c202bf51c | 0 | valid_empty | 0 / 0 |
| 3 | initial_extraction | IN3 | 3315abb9-3749-4d6d-ab14-1594aa109ee8 | content-v1:9c5814e506885e2ff083f0b3b1d5c143061be65077b3b8f5d22f2732a645d516 | 0 | valid_empty | 0 / 0 |
| 4 | initial_extraction | IN4 | 32b6c2f0-77bb-424c-96d8-ac16384797db | content-v1:37ec9e558a30af7900d4acc374bb26750bc76d7ca3a50a493a7c1da6ad33d094 | 0 | valid_empty | 0 / 0 |
| 5 | initial_extraction | IN5 | 8fdc40e3-f50d-4ea8-80a1-850f0dae65ef | content-v1:322edf9f797e298583e2bb00768bd36c252f4e0928efec2b0991d7e15795b6c8 | 0 | valid_empty | 0 / 0 |
| 6 | initial_extraction | IN2 | 4e35200c-f3c3-4a5d-ae5c-570bf830de29 | content-v1:ff3fac97b981281ae75dc3fa847ceb5ce6487b8b2b12e78289db557c202bf51c | 1 | valid_empty | 0 / 0 |
| 7 | continuation_extraction | IN2 | e3dc6f9c-bc85-45b0-96b0-18d85454aa5a | content-v1:298334c9270e498d57e844970f4dd008edeaed328c81b388263199c7a9bba072 | 0 | success | 3 / 0 |
| 8 | continuation_extraction | IN3 | fa37ed52-9ad1-4054-8892-0c696f6ca3d5 | content-v1:41cce8cec3a177663a6d51d3b01aae5a4940d5b51773eb0e489a67f03eecf72b | 0 | valid_empty | 0 / 0 |
