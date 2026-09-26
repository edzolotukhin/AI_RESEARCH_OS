# PRF-08L — Controlled live targeted continuation rerun

## Final result — stopped at design generation

**PRF-08L_LIVE_STOPPED_SAFELY.** After explicit fresh owner authorization, exactly one normal design-generation request returned HTTP 422. No design was persisted and no research run was activated. There was no retry, manual rescue, product fix or push. PRF-08K live target/lineage behavior remains NOT VERIFIED.

Baseline branch `acceptance/live-desk-research-01`, HEAD `d813a5de063472910db070a26ad0747dae0cb02e`, ahead 14 / behind 0 against the locally recorded upstream. Initial tracked/index state was clean. Existing unrelated untracked acceptance artifacts were preserved. No product code was changed and the full offline suite was not rerun.

New isolated Compose project `ai_research_os_prf08l` serves `http://127.0.0.1:18086`. API and worker use image `ai-research-os-prf08l:d813a5d`, config identity `sha256:ac7b5f9e3d71b7fdc4d6a7239017079767bed3f3be3e11a8cb3019f110fc49b8`, built from the accepted current product source. Dedicated network `ai_research_os_prf08l_acceptance`, volumes `ai_research_os_prf08l_postgres_data` and `ai_research_os_prf08l_protected_data`; PostgreSQL has no published host port. Only the new database `prf08l_acceptance` was migrated through `016_prf06f_pptx`. All three services became healthy and `/health` and `/ready` returned 200. Historical services were not restarted, migrated or reconfigured.

Project `f8b634b0-dae6-44a1-86ed-cc1c00726e9f` was created through normal UI forms with the unchanged frozen brief read from PRF-08J. Persisted brief digest `md5(brief::text)` is `7262e5080260e56109b7e95431ec481c`, matching the accepted case. No generated design, approval or research activation has occurred. Run count was zero before the blocked request.

## Operational budget

Owner budget in attached task: USD 5.00. Provider-side monetary cutoff unavailable. Existing operational controls were verified in the new worker: stage total 24; extraction 8 split 6 initial + 2 reserve, one call per targeted attempt; sufficiency 6, analysis 2, report 2, review 1; one gap round, one attempt/query/source per gap. Worker restart is disabled. Keys were checked only for presence, never displayed; the dedicated environment file is Git-ignored and excluded by `.dockerignore`.

Inspection found planner semantic retries nested around three structured attempts. New acceptance configuration sets the existing `PLANNER_SEMANTIC_MAX_ATTEMPTS=1`, bounding planner generation to at most three logical calls. This only tightens operational controls; it does not change product code or design validation criteria. The change was applied before any paid request.

[Official GPT-5 pricing](https://developers.openai.com/api/docs/models/gpt-5) was fetched using OpenAI Docs: USD 1.25/M input and USD 10/M output. [Tavily pricing](https://www.tavily.com/pricing) was fetched; basic search pay-as-you-go envelope uses USD 0.008/credit. Practical pre-run estimate: 19 stage calls plus 3 planner calls, conservative assumed 60k input tokens per call, 8192 output tokens per call, 18 searches: USD 3.59624 base / USD 4.49530 with 25% contingency. This is an estimate, not a hard input bound or a measured provider charge. Existing SDK transport retries are bounded at two, with 600-second read timeout; contingency is not a mathematical guarantee against all duplicate-billing scenarios.

## Execution authorization gate

The first requested paid action was normal UI design generation. The execution approval reviewer rejected the command before process creation, stating that explicit trusted authorization for the new PRF-08L paid request and frozen-brief egress was required. No alternate path or retry was attempted. No OpenAI/Tavily call was made by this task. Explicit owner confirmation is required before continuing with generation. The prepared environment is left available; do not create another project or a replacement run when resuming.

The owner subsequently explicitly authorized sending the frozen brief/minimum research data to OpenAI and bounded OpenAI/Tavily calls for exactly one PRF-08L run with USD 5 total operational budget. The existing healthy environment/project was reused. A fresh read-only check confirmed zero runs and no design before the request.

Command `python tools/prf08l_ui.py generate --project f8b634b0-dae6-44a1-86ed-cc1c00726e9f` was executed exactly once after authorization. The API access log records HTTP 422 at `2026-09-26T08:11:34.680149902Z`. The helper exited with `urllib.error.HTTPError: HTTP Error 422: Unprocessable Entity`. There was no subsequent generate, approve or activate request.

### Failure evidence and observability limitation

`api/routers/ui_projects.py` renders this 422 response when normal design generation raises `ValueError`; its template receives `str(exc)`. The existing acceptance helper did not retain the HTTP error response body, and the server access log contains only the status, not that exception text. `ProjectPlanningService.generate_design` persists a design only after the planner succeeds; no design was saved. The available evidence establishes rejection of the design-generation request, but **does not establish the exact underlying validation error, malformed-output condition or provider failure**. It would be unsupported to label this an RQ-to-IN defect or a PRF-08K regression. The unavailable response body was not reconstructed by resending a paid request. No product or helper behavior was changed to rescue the attempt.

Final SELECT-only checks: workflow runs **0**, sources **0**, Evidence **0**, saved design absent, frozen brief digest unchanged. Consequently there is no run ID and no research elapsed time. Request latency and provider input/output tokens were not durably recorded; exact elapsed time is unavailable. One HTTP design-generation request is not evidence of exactly one LLM call: internal planner calls/retries are not observable from the retained logs. Configuration bounds them at three logical attempts (one semantic pass, up to three structured attempts), plus the already documented bounded SDK transport retries.

### Primary trace and comparison

No extraction attempt occurred. Initial extraction calls **0**, continuation calls **0**, searches **0**, acquisitions **0**. Thus initial <=6 and total <=8 hold numerically, but do not validate live scheduling, target fidelity or reserve use. No target was selected and no naturally occurring lineage pair was encountered. RQ-to-IN validation, normal approval, coverage, sufficiency and all observable research-integrity checks are NOT VERIFIED. No legitimate report exists; Findings, Insights, automated Review, PDF/PPTX and claim audit were not attempted or manufactured. This is a preflight stop, not an insufficient-research result in either A or B category.

| Metric | PRF-08J | PRF-08L |
| --- | ---: | --- |
| Research runs | 1 | 0; design request rejected |
| Searches | 13 | 0 |
| New page-fetch attempts | 3 | 0 |
| Extraction initial / continuation | 6 / 1 | 0 / 0; not exercised |
| Evidence / qualifying | 27 / 17 | 0 / not applicable |
| Per-IN coverage / zero-Evidence required INs | Recorded in PRF-08J | Not comparable: no accepted design |
| Lineage count | Recorded in PRF-08J | Not applicable |
| Sufficiency | false | Not evaluated |

No measured bill is available. The conditional planner-only envelope is **USD 0.47076 base / USD 0.58845 with 25% contingency**, using up to three planner calls, assumed 60k input tokens and 8192 output tokens per call at the verified prices. This is not an actual charge or proof of a specific call count; duplicate transport billing is not fully observable. No further paid calls were made after failure. The USD 5 operational authorization was not treated as permission for another design generation or research attempt.

## Historical integrity

Read-only transactions against the original databases matched accepted Evidence counts/digests and workflow-row digests both at preflight and after the rejected design request; all statuses remain completed. No historical outcome was recomputed.

| Run | Evidence | Evidence MD5 | Workflow-row MD5 |
| --- | ---: | --- | --- |
| PRF-08B | 13 | `076646d8ec25f2a7d682ec420896af95` | `00ef1aa66c3b6194ba39d1a01c066de7` |
| PRF-08D | 33 | `84ce68280d94941b19414a46893f2868` | `01e242df696ac51050788442c6249471` |
| PRF-08F | 22 | `7937d0745c8c03a67ffc045c9fbbb6f5` | `3eedf9afcfbd4b61b1eaa672bc36f3f8` |
| PRF-08H | 24 | `3866b66b19d3ec31ff6210fafa297922` | `60fd6bb7a92d1c36f0bb04073d567e47` |
| PRF-08J | 27 | `299e88abe27b9363fd623f5f9e034eac` | `2e66c4ab0dbf4365877c97e61e053576` |

Canonical query: `md5(string_agg(row_to_json(e)::text, chr(10) ORDER BY id))`, scoped to each recorded workflow run. No historical data, old acceptance record, root environment file or unrelated artifact was edited.

## Delivery checkpoint

Acceptance-only files: dedicated Compose configuration, startup script, owner registration helper, explicit-action UI helper, and this record. An unused metadata audit helper drafted while generation was pending was removed before delivery; no existing artifact was removed. Startup `./scripts/prf08l_start.ps1` restores only this environment and does not activate research. Do not repeat paid generation/activation as part of this completed attempt. The environment is left available; historical services and root `.env` were preserved.

The full offline suite was not rerun, as requested. Only acceptance helper syntax, PowerShell parsing, Compose configuration and diff/secret-scope checks are relevant; no product/schema/test changes were made. One local evidence commit uses `PRF-08L record live targeted continuation rerun`; no push. This commit records a genuine failed preflight, not successful live remediation validation.
