# PRF-08V — Controlled live funnel validation

## Baseline and preflight

Initial HEAD `1d8ae8339d01ca486f86933f9e21fbd75d54537c`, branch
`acceptance/live-desk-research-01`, clean tracked/index, recorded upstream
ahead 24 / behind 0. Existing untracked artifacts preserved. No offline suites
rerun and no product code changed.

Isolated Compose project `ai_research_os_prf08v`, loopback API
`http://127.0.0.1:18088`, dedicated network `ai_research_os_prf08v_acceptance`
and volumes `ai_research_os_prf08v_postgres_data` / `ai_research_os_prf08v_protected_data`.
Database/user `prf08l_acceptance` / `prf08l` are names inside the new separate
PostgreSQL instance, not the historical PRF-08L instance. No historical DB copied.
Current-source image `ai-research-os-prf08v:1d8ae83`, image config
`sha256:df521ec935615501625f92bce9c3c61eb75962d4f0204528611d06c9dba445ce`.
New DB migrated through `016_prf06f_pptx`; API, worker, DB healthy; readiness 200.
Provider credentials verified present only, never printed. Root/provider env
unchanged. New non-secret private override is ignored by Git and image build.

Reproducible Compose prefix (only this project):

```text
docker compose --project-name ai_research_os_prf08v --env-file .env.prf08l -f docker-compose.prf08l.yml -f .env.prf08v-runtime/compose.yml
```

Runtime query-opportunity module SHA256 matches checkout:
`b474b5b37a3865c0eb231a311dae8ce28bf75360ea2c9fc9be60f7d061a5bbaa`.
Telemetry module SHA256 matches:
`c3d9001852b27cd4ca2a24a7a4e82e27cfd10f428c29bde8516d3de0a82d00b7`.
PRF-08S enabled by default; no telemetry override or policy manipulation.

## Authorization, design and sole activation

Owner explicitly authorized one complete scenario, including one design,
approval on normal validation, one activation and bounded provider calls, USD 5.
Project `e05794e5-a474-4626-96cd-9a22b9bff7a7` was created via normal UI forms.
Frozen brief read from original T project, persisted unchanged via normal brief
form: PostgreSQL `md5(brief::text)` = `7262e5080260e56109b7e95431ec481c`.
No history or research state was seeded.

Exactly one design-generation POST returned 200. Design
`ca1491a6-534d-4ce8-9f04-25a8262c709f` passed normal generation validation:
5 RQs, 6 INs. RQ1 has IN1 counts and IN2 changes; RQ2 IN3 regional/site types;
RQ3 IN4 announcements; RQ4 IN5 utilization; RQ5 IN6 definitions/gaps.
UK/50-kW scope, fixed brief period, no forecasts/investment advice and limitations
preserved. Some IN period wording is broad or referential; assess executed queries
rather than claiming all design wording is exact. This is a newly generated design,
so IN numbers are not directly equivalent to T's five-IN structure.

Approval of this exact design and one activation both returned 200.
Run `bf590dc0-e1b8-5e71-b620-6d14e182d345`.
No second generation/activation, retries by the acceptance client, or manual rescue.

## Operational budget

GPT-5 and existing T limits retained: stage cap 24, extraction 6+2=8,
sufficiency 6, analysis 2, report 2, review 1; one gap round and one query/source
per gap attempt. Worker restart disabled. No budget/threshold changes.
OpenAI Docs used to check the configured model's current pricing, not change models:
[GPT-5](https://developers.openai.com/api/docs/models/gpt-5), USD 1.25/10 per
million input/output tokens; [Tavily](https://www.tavily.com/pricing).
Prior practical envelope: 19 stage calls + up to 3 planner calls, assumed 60k
input and 8192 output per call, 18 basic searches at USD 0.008. Base USD 3.59624;
25% contingency USD 4.49530. This is a conservative operational estimate using
input assumptions, not a hard monetary cutoff or observed bill. SDK retry billing
is not independently visible. Reassess on observable errors/usage; never treat
the account balance as authorization above USD 5.

## Historical integrity

Fresh original-container read-only transactions checked Evidence count and
`md5(string_agg(row_to_json(e)::text,chr(10) ORDER BY id))`, plus workflow-row MD5.
All completed workflow fingerprints match the PRF-08U baseline:

| History | Evidence | Evidence MD5 | Workflow MD5 |
| --- | ---: | --- | --- |
| B | 13 | 076646d8ec25f2a7d682ec420896af95 | 00ef1aa66c3b6194ba39d1a01c066de7 |
| D | 33 | 84ce68280d94941b19414a46893f2868 | 01e242df696ac51050788442c6249471 |
| F | 22 | 7937d0745c8c03a67ffc045c9fbbb6f5 | 3eedf9afcfbd4b61b1eaa672bc36f3f8 |
| H | 24 | 3866b66b19d3ec31ff6210fafa297922 | 60fd6bb7a92d1c36f0bb04073d567e47 |
| J | 27 | 299e88abe27b9363fd623f5f9e034eac | 2e66c4ab0dbf4365877c97e61e053576 |
| O | 1 | 135c9ec526cdd2672bd61b52e7902f7d | 9dcb9c3b7526dd0eeb2a625876460c28 |
| T | 5 | 3c15be644e3a45f47955bc1da2bfd412 | eab5db1fd4860e5011a91c6fefed1e53 |

No historical outcome recomputed, reinterpreted or mutated.

## Terminal result and telemetry reconciliation

**PRF-08V_LIVE_COMPLETED_WITH_FINDINGS.** Workflow completed, but
`ready_for_analysis=false`, `evidence_remediation_budget_exhausted`.
The database contains exactly one run. Analysis/report/review skipped naturally.
Findings, insights, reports, review_results, pdf_deliverables and presentation_jobs
all have zero rows in this isolated DB. No downstream exports manufactured.

Run task-record span: 2026-09-26 13:58:29.120944–14:00:27.652542 UTC,
118.531598 seconds, excluding design. Final journal: 393 events, zero drops,
zero observer errors. Fourteen successful search-result events, five empty lists,
27 candidate observations, 27 decisions, seven fetches/seven successes,
eight extraction attempts/results, 21 Evidence IDs. Repeated qualification
observations (231) are not separate facts; use the last event per Evidence/IN.
New Evidence ordered-row MD5: `7f9ca2da74d75c5bae0107a425108309` (21 rows).

### Per-IN funnel

Fetch attribution includes shared-source discovery refs and is deliberately
nonadditive: July source serves IN1/IN2, April source IN2/IN3, each fetched once.
Extraction attribution is its primary target. Target/cross counts describe
yield from attempts aimed at that IN, whereas stored counts describe final refs.

| IN | Queries | Returned | Selected / skipped | Attributed fetch / success | URL duplicate skips | Extraction / empty / productive | Target / cross yield | Stored / temporal-qualified |
| --- | ---: | ---: | --- | --- | ---: | --- | --- | --- |
| 1 counts | 2 | 3 | 1 / 2 | 1 / 1 | 0 | 2 / 0 / 2 | 8 / 2 | 8 / 3 |
| 2 change | 2 | 3 | 1 / 2 | 2 / 2 | 1 | 1 / 0 / 1 | 5 / 1 | 7 / 6 |
| 3 regional/sites | 2 | 3 | 0 / 3 | 1 / 1 | 1 | 0 / 0 / 0 | 0 / 0 | 1 / 1 |
| 4 disclosures | 3 | 6 | 2 / 4 | 2 / 2 | 0 | 2 / 2 / 0 | 0 / 0 | 0 / 0 |
| 5 utilization | 3 | 9 | 2 / 7 | 2 / 2 | 0 | 2 / 2 / 0 | 0 / 0 | 0 / 0 |
| 6 definitions/gaps | 2 | 3 | 1 / 2 | 1 / 1 | 0 | 1 / 0 / 1 | 5 / 0 | 5 / 0 |
| Unique totals | 14 | 27 | 7 / 20 | 7 / 7 | 2 | 8 / 4 / 4 | 18 / 3 | 21 / 10 |

Skip reasons: coverage-complete 12, duplicate URL 2, unsupported URL 3,
acquisition budget 2, already-exhausted 1. Content-alias duplicates zero.
Two INs have zero stored Evidence; three have zero temporal-qualified Evidence.
Readiness: IN1 partial (3 facts/1 independent source), IN2 partial (6/1),
IN3 insufficient (1/1), IN4/5/6 missing. Counts are not proof of completeness,
topic relevance, unique claims or genuinely independent datasets.

## PRF-08U checks and causal limits

### Query intent: PARTIAL

All 14 executed query texts were exact in telemetry (no truncation/redaction).
IN1 retains Jan-2025/1-Jul-2026; IN2 resolves `Same as in1` to the brief's
`1 January 2025 to 1 July 2026`; IN4 retains the explicit disclosure window;
IN5 and IN6 retain 1-Jul-2026. IN3 still says `2025–latest 2026 cut-offs`:
the generated design's year-bearing but imprecise period is preserved, not
resolved to the exact July boundary. Thus full temporal fidelity is not PASS.

Six initial baseline/localized pairs share text, as allowed by the existing
different retrieval arms. Both continuation queries are distinct from initial:
IN4 appends the grounded exact phrase `"operator name"` (event f188, hash
`247e5dea89c0916668ed575ed9f47f273a903e8f8897c595a0d6db69ca114b37`);
IN5 appends `"utilization metric"` (f285, hash
`3bd3198d424fc2447a92373a83529d3aaa73a8b54b8765210ba11b3903cf844d`).
The same full target/date context remains. Exact continuation repeats: T 1,
V 0. Semantic/result novelty is weaker: both still return previously seen URLs.
No claim that the quoted phrase alone solves broad/noisy retrieval.

### Candidate selection: PARTIAL, ongoing signal-quality limits

Initial selection acquired April and July official statistics before unrelated
fallback material. Shared source discovery gave IN3 a cross-IN fact without a
second fetch. However IN4 selected Dollar Tree disclosures; IN6 selected digital
gold methodology; existing decision code was `topic_aligned_geo_unknown`.
These are not legitimate EV evidence merely because they match generic words.
Continuation IN4 exhausted Dollar Tree and chose agentmodeai.com/disclosures
(`category_not_preserved`) as a bounded fallback. IN5 chose IEA with geographic
proxy status after a PDF was unsupported. No domain-specific override was used.

Initial January statistics, Zapmap and Skywell opportunities were coverage-skipped;
their counterfactual usefulness is NOT VERIFIED. The IEA URL initially skipped
for IN5 was later acquired but produced no target Evidence in its first chunk.
This differs from T's proven delayed productive January source: no demonstrated
missed productive candidate can be inferred for V from URLs alone. Unsupported
PDF candidates remain an acquisition capability limitation, not HTTP failures.

### Ordered extraction and valid-empty feedback: observed bounded redirection

| Call | Phase | Target | Source | Chunk | Result | Target / cross |
| ---: | --- | --- | --- | ---: | --- | --- |
| 1 | initial | IN1 (scope IN1/2) | July statistics | 0 | productive | 1 / 2 |
| 2 | initial | IN2 (scope IN2/3) | April statistics | 0 | productive | 5 / 1 |
| 3 | initial | IN4 | Dollar Tree disclosures | 0 | valid-empty | 0 / 0 |
| 4 | initial | IN5 | Paren utilization article | 0 | valid-empty | 0 / 0 |
| 5 | initial | IN6 | digitalgold.org | 0 | stored off-topic Evidence | 5 / 0 |
| 6 | initial | IN1 (scope IN1/2) | July statistics | 1 | productive | 7 / 0 |
| 7 | continuation | IN4 | agentmodeai.com | 0 | valid-empty | 0 / 0 |
| 8 | continuation | IN5 | IEA 2025 charging | 0 | valid-empty | 0 / 0 |

After empty call 3, Dollar Tree chunk 1 was not deepened; call 6 used already
productive July material. Empty Paren was not retried. Continuation moved to
new sources for zero-Evidence IN4 then IN5; call 7's empty result did not discard
call 8. No second extraction on either final empty source. Five IEA later chunks
and two initial chunks were budget-skipped. No invalid/failure extraction,
structured recovery retry or unbounded search. The observed order supports
PRF-08U feedback behavior, but provider/design variability prevents attributing
all extra facts to the patch.

### Temporal qualification: conservative unresolved state, additional findings

Ten stored facts pass the *existing temporal filter*, ten are unresolved, one
fails. This is not ten validated decision-support facts. Every unresolved/failed
item is accounted for below; short IDs uniquely identify this run's Evidence.

| Evidence IDs | Signal present | Final result / finding |
| --- | --- | --- |
| 0530ae87, 1bc9dfbb, 77943f9f, 7c073faa, a84e7b4f | Claim has July date; excerpt is only a numeric table row; no observation metadata | unresolved; missing row/header temporal grounding, not rescued from publication date |
| 05c6ebc7, 155c0d84, 89d83d20, e2b9c85c, e9deeae1 | Undated digital-gold statements, no applicable EV observation | unresolved; five off-topic extractions persisted but did not qualify |
| b1cf4b52 | Grounded metadata `first quarter of 2026`; excerpt supplies April-2026 reporting context | failed; existing parser recognizes Q1, not spelled-out quarter, then treats bare 2026 as whole year beyond cutoff |

Other explicit grounded dates qualify normally: July counts, April counts,
January series-definition changes, June removal of misreported private chargers,
April geographic commentary and dated methodological context. The same definition
change occurs in two sources; two rows are not independent novel facts.

Important lower-bound finding: `7e50448d-9d8c-44b7-8aa6-9ae9b4cfff7d`
reports 2024/2023 additions, metadata `2024`, but passes temporal qualification.
Code inspection confirms the existing evaluator checks the maximum observation
end against the upper cutoff, not the brief's 1-Jan-2025 lower bound. These older
counts do not satisfy the requested 2025–2026 change metric. No correction applied.

The new metadata-free as-of fallback was **NOT VERIFIED live**: the legitimate
leading as-of counts already carry explicit observation metadata. All missing-
metadata candidates lack the required matching grounded date shape. No actual
post-July measurement naturally occurred, so post-cutoff exclusion is NOT VERIFIED
in this run; the Q1 false rejection is not a successful post-cutoff test.
No publication date alone was used to qualify an unresolved item. No historical
Evidence was reevaluated and no new facts were manually repaired.

## Direct T → V comparison

| Metric | T | V |
| --- | ---: | ---: |
| Searches | 11 | 14 |
| Candidate observations | 22 | 27 |
| Fetch attempts | 9 | 7 |
| Successful acquisitions | 7 | 7 |
| Extraction calls | 8 | 8 |
| Valid-empty | 6 | 4 |
| Productive (nonempty) calls | 2 | 4 |
| Nonempty rate | 25% | 50% |
| Stored Evidence | 5 | 21 |
| Temporal-qualified Evidence | 2 | 10 |
| INs with zero stored Evidence | 3/5 | 2/6 |
| INs with qualifying Evidence | 2/5 | 3/6 |
| Exact continuation repeats | 1 | 0 |
| Sufficiency | false | false |

Different generated design: V splits scale/change into two INs. By substantive
topic, both runs cover scale/change and regional context; operator presence,
utilization and useful definitions remain unsupported. V has only three useful
nonempty extraction calls once digital-gold material is excluded (37.5%).
The apparent gains are not controlled causal estimates. More searches reflect
six versus five design INs, within unchanged limits, not a raised search budget.
Temporal recovery cannot be credited to the new fallback because it did not fire.

## Bottleneck, alias/lineage observations and downstream

Primary classification: **MIXED**, dominated by QUERY_STRATEGY /
PROVIDER_CANDIDATE_QUALITY for disclosures/definitions/use, imperfect selection
signals, off-topic EXTRACTION acceptance, and QUALIFICATION limitations above.
Not classified as proven genuine evidence scarcity: noisy returned material does
not establish that appropriate public evidence does not exist. Retrieval succeeded
for all selected sources, but PDFs were excluded before acquisition.

PRF-08P content aliases: NOT VERIFIED; all seven acquired content identities are
distinct. Two same-URL discovery duplicates are not a content-alias exercise.
PRF-08K harmless provenance naming variants: NOT VERIFIED; established lineage
values are consistently `Zapmap`, otherwise unknown. One independent source per
qualifying IN is preserved, but no natural spelling-variant case occurred.

Natural conservative refusal preserved. Report quality, review approval,
PDF/PPTX source binding/download/fidelity: NOT REACHED, not passed.

## Actual usage and remaining limitations

One design HTTP request; underlying design LLM count/tokens not separately
established. Research usage: 11 logical calls = 8 extraction + 3 sufficiency,
zero recorded stage retries; 3376 + 444 = 3820 output tokens, 49.656 seconds
summed model time. Initial/continuation extraction partition exactly 6/2.
Fourteen Tavily calls, seven acquisitions. Input/reasoning counters report zero
but are not proof of zero billed tokens; SDK transport retries unobserved.
Actual provider invoice/account debit is unavailable.

The preflight USD 4.49530 operational estimate remains the scenario planning
envelope, not actual cost. Using 11 observed calls plus up to 3 assumed design
calls at the same 60k/8192 allowance and 14 searches gives USD 2.30888 base,
USD 2.88610 with 25% contingency. This too is an estimate with input/retry
assumptions, not a measured upper bound. No second scenario was authorized or run.

Only this acceptance record is a Git deliverable. Private startup override remains
ignored; no product/tests/thresholds/query/DB corrections. Existing services,
root env and historical artifacts preserved. No push. The isolated result remains
available at http://127.0.0.1:18088/ui/research/bf590dc0-e1b8-5e71-b620-6d14e182d345/overview .
