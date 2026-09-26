# PRF-08P — Source diversity and content deduplication

**Verdict: PRF-08P_REMEDIATION_INCOMPLETE.** Targeted remediation and historical
integrity pass. The one canonical full-suite run exposes an unchanged baseline
architecture-test failure, documented below. This is not a green full-suite
claim; the requested local commit preserves the bounded remediation and evidence.

## Baseline and scope

Initial HEAD `61598d62b2e096cb5ac075fedc5f2c25d478e9f7`, branch
`acceptance/live-desk-research-01`, ahead 18 / behind 0 against recorded upstream.
Tracked files/index were initially clean. Existing untracked acceptance/runtime
artifacts were preserved. This is offline remediation, not a live acceptance:
no OpenAI, Tavily, research activation, historical recomputation, or push.

## Persisted PRF-08O capacity-loss evidence

Run `966141f8-b07f-510c-8e41-66795ab65227`, existing design
`0f333dd1-54bc-49a0-b758-0e308e61c336`. The committed PRF-08O record is the
source for the ordered trace below; historical rows are checked read-only, not
reclassified by the new product code.

13 logical searches (11 initial + two targeted), 27 initial raw candidates,
18 initial canonical URL groups, six successful acquired source records, five
distinct stored content checksums. Initial collection recorded four attempts
and zero failures; targeted failure/attempt totals are not retained. Therefore
an exact total including unsuccessful targeted fetches is NOT VERIFIED.

| Extraction | Source from PRF-08O | Target/scope | Persisted outcome |
| --- | --- | --- | --- |
| 1 | S1: Zapmap metrics page | IN1 | Valid empty, zero Evidence |
| 2 | S2: GOV.UK July 2026 | IN2, discovery refs IN2/4/5 | Valid empty |
| 3 | S3: ONS indicator | IN3, discovery refs IN3/4/5 | Valid empty |
| 4 | S4: US eCFR part 680 | IN6 | Valid empty; geographically poor candidate for the UK case |
| 5 | S2, depth | IN2/4/5 | One persisted and qualifying Evidence, IN2 only |
| 6 | S3, depth | IN3/4/5 | Valid empty |
| 7 | S5: alternate Zapmap URL | IN1 continuation | Identical acquired content to S1; one call, zero Evidence, fully processed |
| 8 | S6: GOV.UK January 2026 | IN3 continuation | Valid empty; one of two chunks, remaining chunk correctly bounded out |

S1 `734d4287-2801-4029-98d5-ebd6bedede74` and S5
`940c37ea-ad66-4dcb-8707-2eef7c24de9b` share stored checksum
`32d8214233b548a56ea0fb0b96cd536df09e8251242e2de7a5acbe8f47977cef`.
Their URLs use `https://www.zapmap.com/...` versus `http://www.zap-map.com/...`.
URL canonicalization alone cannot safely infer that different hosts serve the
same document. Both Source IDs consequently received extraction opportunities.

The demonstrated avoidable loss is the seventh extraction of already seen
content. The other nonproductive calls are not proof of irrelevant content or
absence of public evidence: no such detailed causal classification was saved.
Continuation #1's detailed response shape was overwritten by the final
remediation snapshot; its history proves one call and zero Evidence but not
the exact empty-response classification. No demonstrated temporal/geographic/
lineage candidate rejection or useful-but-nonqualifying Evidence is recorded.
The US page's zero result does not establish why the extractor returned empty.

Five of six required INs remained zero. Both reserved slots were used, target
counts stayed 0→0, and readiness remained false with
`evidence_remediation_budget_exhausted`. PRF-08K scheduling was not broken:
there was no unused reserve to repair. Findings, Insights, Report, Review,
PDF and PPTX remained absent. Historical results are not rewritten.

## Old and new identity semantics

Previously acquisition grouped canonical URLs and persistence keyed sources by
project/canonical URL. Extraction scheduled source IDs; Evidence dedup also
included source identity. Equal full content under another URL was not enough
to prevent another extraction.

`acquired_content_identity` now computes `content-v1:` plus SHA-256 of the
complete successfully acquired text using the existing exact grounding
representation: one HTML-entity decoding pass, Unicode NFC and collapsed
whitespace. Case, punctuation and all substantive text remain significant.
It does not trust a claimed checksum, use fuzzy similarity, strip boilerplate,
equate domains, or contain topic/vendor rules. Empty, failed and truncated
documents have no asserted content identity: equal prefixes are not proof of
equal full documents. Shared navigation/footer with different bodies remains
distinct.

Source rows and original URLs/checksums/discovery records remain separate for
audit. Acquisition decisions identify observed content aliases and whether a
fetch occurred. Its existing success count still describes acquired URL rows;
early coverage completion requires the existing minimum against distinct
content, so aliases cannot alone satisfy that early-stop condition.

Before initial and targeted extraction, content aliases collapse to one
representative source's chunk queue. Existing depth opportunities remain;
another URL does not add a parallel queue. Only already resolved current
run/design semantic references are unioned, not historical aggregate refs.
Evidence still requires normal grounding and supported IN checks. The
application owns the full-document identity and alias audit metadata; extractor
metadata cannot override these fields. Chunk Evidence records the full
document fingerprint, not a hash of its individual chunk.

For targeted extraction, an alias chunk already successfully processed under
the same/full semantic scope is skipped using persisted work-item boundaries.
Technical failure is not semantic exhaustion, and unprocessed depth/new scope
is not silently discarded. Same-source retry/depth policy is unchanged.
No lineage is inferred from a content hash. Unknown provenance remains
provisional; duplicate queues do not produce extra independent source rows.
Existing PRF-08K origin normalization and sufficiency rules remain unchanged.

## Candidate diversity and bounds

Known exhausted content is excluded per IN, not globally. A candidate already
known to duplicate content selected in this acquisition is ranked after a
viable distinct candidate; existing need-coverage priority and stable rank are
retained among equally nonduplicate candidates. A mirror first discovered by
fetch still costs an acquisition attempt: no refund, extra search, or hidden
retry is introduced. Its persisted alias is deduplicated downstream.

The original `considered`/`max_source_groups`, acquisition deadline,
per-IN search candidate limits and extraction budget checks remain in place.
No configuration limit was raised. The total Evidence bound remains 6+2=8,
and retry/continuation/LLM-stage caps are unchanged. Tests cover a known mirror
before a viable alternative with one slot remaining and multiple uncovered
needs, and actual extraction of the distinct alternative rather than the
already processed mirror. Unknown pre-fetch duplicates cannot be predicted;
this remediation does not promise another search when an acquisition envelope
has already been consumed.

## Regression evidence

Two older test fixtures modeled independent documents using identical text.
The fair-coverage fixture now gives IN3 a distinct body; mixed-outcome
forensic fixtures have distinct document text while retaining the grounded
excerpt and every original outcome assertion. This preserves their original
purpose under the new exact-content invariant; no expectation was weakened.
Initial source-suite failures were corrected in product accounting without
changing those source test fixtures.

- New deterministic `tests.application.evidence.test_prf08p_content_identity`:
  16 passed. Covers identity, tracking URLs, shared boilerplate, partial/failed
  content, audit retention, full-document versus chunk identity, depth,
  same-run reference union, foreign-run isolation, known alternative selection,
  actual single extraction, conservative unknown lineage and technical failure.
- New PRF-08P + existing PRF-08K target/lineage selection: 27 passed.
- Source suite: 210 collected, 208 passed, two expected skipped.
- Evidence suite before the final five added regressions: 148 passed.
- Research-quality suite: 477 passed, no skips.
- Disposable PostgreSQL/API-worker selection: 20 passed, zero skipped.
  Modules: `test_prf08p_content_identity`, `test_prf08k_lineage_identity`,
  `test_prf08c_evidence_integrity`, `test_source_provenance_concurrency`,
  `test_research_loop_progress_checkpoint_recovery`, `test_worker_execution`,
  `test_worker_api_claim_integration`, `test_worker_execution_service`,
  `test_worker_loop_failure_isolation`, `test_worker_loop_defaults`.
- Canonical `python run_tests.py`, run exactly once: **2888 collected/run,
  2740 passed, 147 skipped, one failure, zero errors**, 108.244 seconds.
  The skips are not counted as passes.

The sole failure is
`StructuredOutputArchitectureTests.test_p_json_loads_only_in_validator`:
`tools/acceptance_http.py` contains `json.loads` but is not in that test's
allowlist. Its latest change is PRF-08M commit `e912cac`; neither file was
modified by PRF-08P. Git blob IDs for worktree and initial HEAD match exactly:
helper `ef2266a2088e1bea4196d82e9f9b579ab00138a2`, architecture test
`153b48a19cbc238eeb302933fb6d2bef553f7416`. Running just that test independently
reproduced the same sole offender. This is a demonstrated pre-existing
test/helper contract mismatch, not a content-dedup regression. It was not
silently repaired or excluded from the full run; resolving it requires a
separate scope decision. The full suite was not repeated.

Integration execution used production-compatible dependencies from
`ai-research-os-prf08l:d813a5d` with current application/domain/infrastructure/
runtime/API/tests/Alembic directories mounted read-only. No root `.env` was
mounted. New internal network `ai_research_os_prf08p_test`, new container
`ai_research_os_prf08p_test_postgres`, tmpfs database `prf08p_test`, no host port,
no historical volume, no provider credentials and no external route.
Existing migrations reached `016_prf06f_pptx` only on this disposable database.
No schema migration was added. No renderer or deployment implementation changed,
so unrelated production-image/rendering qualification was not repeated.

## Historical integrity

Fresh SELECT-only transactions against the original Docker Desktop containers
used `md5(string_agg(row_to_json(e)::text, chr(10) ORDER BY id))` and workflow
row MD5, not new dedup/sufficiency logic. All matched the recorded baselines:

| History | Evidence | Evidence MD5 | Workflow MD5 |
| --- | ---: | --- | --- |
| B | 13 | `076646d8ec25f2a7d682ec420896af95` | `00ef1aa66c3b6194ba39d1a01c066de7` |
| D | 33 | `84ce68280d94941b19414a46893f2868` | `01e242df696ac51050788442c6249471` |
| F | 22 | `7937d0745c8c03a67ffc045c9fbbb6f5` | `3eedf9afcfbd4b61b1eaa672bc36f3f8` |
| H | 24 | `3866b66b19d3ec31ff6210fafa297922` | `60fd6bb7a92d1c36f0bb04073d567e47` |
| J | 27 | `299e88abe27b9363fd623f5f9e034eac` | `2e66c4ab0dbf4365877c97e61e053576` |
| O | 1 | `135c9ec526cdd2672bd61b52e7902f7d` | `9dcb9c3b7526dd0eeb2a625876460c28` |

All workflow statuses remain completed. O was checked in the existing PRF-08L
PostgreSQL container; the other histories in their original respective
containers. PRF-08L/N committed acceptance records were not edited. Their
historical checkpoints are not reinterpreted as new runs.

## Limitations and delivery

Live yield improvement, retrieval-provider ranking, real mirror distributions,
and eventual sufficiency are NOT VERIFIED: no live calls were authorized or
made. Deterministic equality intentionally misses substantively similar pages
with materially different full text and does not infer provenance independence.
No new planner, threshold weakening, lineage rewrite or PRF-08K orchestration
change was introduced.

Final diff review covers only PRF-08P code, tests and this record; no `.env`,
credentials, provider payloads, generated documents, database files or runtime
dumps. The requested local commit is `PRF-08P deduplicate acquired content and
preserve source diversity`; it does not imply the unrelated full-suite gate is
green. No push. Existing acceptance/runtime artifacts and active/historical
services remain preserved. The temporary PRF-08P test container/internal
network are removed after testing; only their disposable synthetic tmpfs data
are discarded, with no historical resources attached.
