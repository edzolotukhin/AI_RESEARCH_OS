# PRF-08N — Controlled live design retry

**PRF-08N_DESIGN_READY_FOR_RESEARCH** means the saved design is valid and eligible for normal approval. It is still **DRAFT**, not approved or activated. Research requires a separate owner decision and authorization.

## Baseline and preflight

Branch `acceptance/live-desk-research-01`, initial HEAD `e912cacce59f3f33cb6d75f65f9ae7096aa631ec`, ahead 16 / behind 0 against locally recorded upstream. Tracked tree/index were clean. Existing PRF-08L isolated API, worker and PostgreSQL were healthy; `/health` and `/ready` returned 200. The existing environment/project was reused, not recreated or reconfigured.

Project `f8b634b0-dae6-44a1-86ed-cc1c00726e9f`, brief MD5 `7262e5080260e56109b7e95431ec481c`, matched the frozen case. Before the attempt there was no saved design and workflow runs were zero. The host acceptance helper imported the committed PRF-08M diagnostic client. Dedicated diagnostic destination `artifacts/acceptance/prf08n_http_errors.log` is Git-ignored. No offline suites were rerun and PRF-08K research logic was not revisited.

Runtime configuration remained GPT-5, planner output cap 8192, one semantic attempt with up to three internal structured attempts. Credential availability was checked as a boolean only. No root environment file, credential or runtime configuration was edited.

## Authorization and sole request

The owner explicitly authorized exactly one design-creation request with up to USD 1.00 operational spend, sending the frozen brief/minimum required data to OpenAI through the normal workflow. Tavily, evidence collection, approval and research activation were not authorized and were not performed.

Executed once:

```text
python tools/prf08l_ui.py generate --project f8b634b0-dae6-44a1-86ed-cc1c00726e9f --diagnostics artifacts/acceptance/prf08n_http_errors.log
```

This is the normal empty form POST to `/ui/projects/f8b634b0-dae6-44a1-86ed-cc1c00726e9f/design/generate`; the saved brief is read by the application. Request semantics, brief, thresholds and product code were not modified. Only the application's normal successful design save changed project state; no direct DB correction or seeding occurred.

Start: `2026-09-26T08:59:40.2141801Z`. Server access log at `2026-09-26T09:00:22.194233155Z`: **303 See Other** for that POST. The helper followed the normal redirect to the design page and returned **200**, exit code 0. Measured client elapsed time: **42.367418 seconds**. No second request was submitted.

## Saved result and validation

Design ID: **`0f333dd1-54bc-49a0-b758-0e308e61c336`**. Status **DRAFT**. Approval actor/time are both null. Persisted input fingerprint `0bea46d612195b847247156b9f7aacaeb90160439faee48423225de26fb1e2d4` matches the current brief/methods/profile fingerprint.

Read-only inspection and the existing pure `validate_research_design` and `validate_project_design_depth(..., methods=("DESK",))` checks passed. Every material RQ has IN coverage, objective references validate, and the design is eligible for normal approval. These checks do not approve the design and do not establish research sufficiency.

| Research question | Linked information need(s) | Scope |
| --- | --- | --- |
| `rq1_scale_change` | `in1_counts_definitions` | Documented UK public 50 kW+ counts/change, metrics, definitions and data feeds |
| `rq2_distribution` | `in2_regional_breakouts`, `in3_site_type_breakouts` | Comparable regional and retail/destination/en-route distribution |
| `rq3_operator_presence` | `in4_operator_announcements` | Dated primary operator/retailer disclosures treated as announcements, not verified inventory |
| `rq4_use_vs_capacity` | `in5_utilization_evidence` | Observed use with disclosed method/scope, distinct from installed capacity |
| `rq5_evidence_gaps` | `in6_definition_mappings` | Definition/cut-off differences, unsupported questions and public-data limitations |

There are **5 RQs and 6 INs**. Observation scope remains 2025 through 1 July 2026, with later publications restricted to the fixed observation window as specified in the brief. Geography remains UK, with regional detail explicitly scoped. Frozen brief MD5 is unchanged after generation.

## 422 diagnostics and historical interpretation

No 422 occurred; no error diagnostic log was created because the request succeeded. Consequently there is no error body or error correlation/request ID to report. The PRF-08M diagnostic path was active, but its failure branch was not exercised by this successful live request; no artificial error was introduced.

**Historical PRF-08L 422: not reproducible with the evidence currently available.** Success here does not identify or repair the unknown prior cause. The committed PRF-08L stopped record and PRF-08M diagnosis remain unchanged. This PRF-08N design save does not retroactively make PRF-08L successful.

Post-attempt read-only counts: **workflow runs=0, sources=0, Evidence=0**. No research run ID exists, no approval/activation request was submitted, and no Tavily call or downstream research step was initiated.

## Cost and limits

Exactly **one application design-generation request** was made. Internal logical model-call count, structured/transport retries, provider input/output token usage and measured bill are not exposed by the retained success diagnostics; they are **not reported as measured**. Runtime bounds remain one semantic pass / up to three structured logical attempts, output cap 8192, with the previously documented bounded SDK retries.

The prior recorded pricing-based planner-only estimate was reused for the unchanged configuration: USD **0.47076 base / 0.58845 including 25% contingency**, conditional on up to three planner calls, assumed 60k input tokens and 8192 output tokens per call. This is below the owner-authorized USD 1 operational limit but is not a provider-side monetary cutoff or an actual charge; duplicate transport billing is not fully observable. No extra paid diagnostic probe, search, second generation or research activation followed the result.

## Delivery and next gate

Only this acceptance record is a Git change. Existing product/helper code, frozen brief, historical acceptance records, credentials, configuration and unrelated artifacts were preserved. No tests were rerun as requested; only preflight, normal design creation and read-only inspection/validation occurred.

One local evidence commit uses `PRF-08N record controlled live design retry`; no push. Next gate: owner review and explicit authorization for normal approval and any separately budgeted research activation. Stop here; do not approve, activate or repeat design generation automatically.
