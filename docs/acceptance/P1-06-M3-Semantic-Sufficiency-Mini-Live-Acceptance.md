# P1-06 M3 Semantic Sufficiency — Mini-Live Acceptance

## Status

**ACCEPTED — CONTROLLED MINI-LIVE 2/2 PASS**

Controlled real-provider mini-live acceptance completed after M3.4 (first-pass contract alignment) and M3.5 (resolvability boundary hardening).

## Scope

This acceptance validates the **Semantic Sufficiency boundary only** — the production path from evidence + deterministic signals through LLM `RawSemanticDecision` structured output to deterministic policy and compatibility assessment.

This run does **not** prove:

- Planner quality
- Search quality
- Evidence acquisition quality
- Analysis quality
- Report quality
- Review quality
- Complete Desk Research E2E success

## Configuration

| Setting | Value |
|---------|-------|
| Provider model | `gpt-5` |
| `reasoning_effort` | `minimal` |
| `max_output_tokens` | `8192` |
| `structured_output_max_attempts` | `3` |

Harness: opt-in mini-live (`SUFFICIENCY_MINI_LIVE=1`), two deliberately shaped legacy scenarios, sequential fail-fast execution.

## Scenario A — Obviously Sufficient

**Inputs**

- `evidence_count=3`
- `independent_source_count=2`
- `evidence_expectation=None` (legacy path)

**Observed `RawSemanticDecision`**

```json
{
  "supported_aspects": ["__legacy_need__"],
  "missing_aspects": [],
  "semantic_conflicts": []
}
```

**Observed policy / assessment**

| Field | Value |
|-------|-------|
| `coverage` | `1.0` |
| `gap_types` | `[]` |
| Final status | `SUFFICIENT` |
| `search_directives` | `[]` |

**Structured output:** `attempts=1`, `retries=0` — **PASS**

## Scenario B — Obviously Insufficient

**Inputs**

- `evidence_count=2`
- `independent_source_count=2`
- `evidence_expectation=None` (legacy path)

**Observed `RawSemanticDecision`**

```json
{
  "supported_aspects": [],
  "missing_aspects": ["__legacy_need__"],
  "semantic_conflicts": []
}
```

**Observed policy / assessment**

| Field | Value |
|-------|-------|
| `coverage` | `0.0` |
| `gap_types` | `["insufficient_depth"]` |
| Final status | `INSUFFICIENT` |
| `search_directives` | `["__legacy_need__"]` |

**Structured output:** `attempts=1`, `retries=0` — **PASS**

## Structured-Output Acceptance

| Criterion | Result |
|-----------|--------|
| First-pass success | **2/2** |
| `attempts` | `1` for both scenarios |
| `retries` | `0` |
| Contract failures | `0` |
| Parse failures | `0` |
| Truncations | `0` |
| Canonical legacy aspect | Handled correctly (`__legacy_need__`) |

## Semantic Acceptance

**Scenario A:** evidence supports the InformationNeed → `SUFFICIENT`

**Scenario B:** evidence exists but does not answer the InformationNeed → `INSUFFICIENT` → targeted research remains actionable via `search_directives=["__legacy_need__"]`

Explicit distinctions confirmed in the accepted run:

- **Current evidence insufficiency ≠ `UNRESOLVABLE`**
- **`INSUFFICIENT` ≠ `BLOCKED`**

## Deterministic Policy Acceptance

Final statuses were derived by **deterministic policy** (`apply_sufficiency_policy` → `derive_policy_sufficiency_status`), not selected by the LLM.

The LLM output remained bounded **semantic facts** (`RawSemanticDecision`: supported/missing aspects, semantic conflicts, confidence, reason). Policy fields (`status`, `gap_types`, `coverage`, `search_directives`) were not emitted by the model.

## M3.4 Validation

First-pass contract alignment eliminated the retry pattern observed in preceding controlled runs:

| Phase | Pattern |
|-------|---------|
| Pre-M3.4 controlled runs | Attempt #1 contract failure → attempt #2 correction success |
| Accepted run (M3.4 + M3.5) | Attempt #1 success for both scenarios |

This is evidence from two deliberately shaped scenarios only; it is **not** statistical proof of first-pass reliability across broader inputs.

## M3.5 Validation

Scenario B no longer incorrectly maps insufficient current evidence to `UNRESOLVABLE` → `BLOCKED`.

Earlier misclassification (third controlled mini-live, pre-M3.5):

```
missing_aspects=["__legacy_need__"]
semantic_conflicts=["unresolvable"]
→ BLOCKED
```

Accepted path after M3.5:

```
missing_aspects=["__legacy_need__"]
semantic_conflicts=[]
→ INSUFFICIENT_DEPTH
→ INSUFFICIENT
→ search_directives=["__legacy_need__"]
```

## Usage

| Metric | Value |
|--------|-------|
| `scenario_count` | `2` |
| `llm_calls` | `2` |
| `retries` | `0` |
| `reasoning_tokens` | `0` |

`estimated_cost_usd` was not exposed by telemetry for this run. No cost estimate is recorded here.

## Limitations

- Only **two deliberately shaped scenarios** were tested.
- Both exercised the **legacy** path (`evidence_expectation=None`).
- **Expectation-backed `EvidenceExpectation` live behavior** is not yet provider-validated in this acceptance.
- **Repeatability** across repeated identical provider calls is not yet established.
- **Complete Desk Research E2E** is not yet accepted.

## Next Gate

**P1-06 Semantic Sufficiency Repeatability Acceptance**

Recommended controlled matrix:

| Scenario | Runs |
|----------|------|
| A — obviously sufficient | × 3 |
| B — obviously insufficient | × 3 |

Acceptance target:

- **6/6** technical completion
- A → `SUFFICIENT` **3/3**
- B → `INSUFFICIENT` **3/3**
- No unexpected `MISSING` / `BLOCKED`
- No canonical-aspect violations
- No domain/policy invariant failures
- First-pass structured output should remain stable
- Retries must be reported explicitly
- `confidence` and `reason` wording may vary

Only after repeatability acceptance should the project proceed to a **single controlled Serbia Microgreens Desk Research E2E acceptance run**.

## Traceability

Repository milestones referenced by commit:

| Commit | Milestone |
|--------|-----------|
| `d0c69d3` | Semantic sufficiency boundary hardening (M3 production boundary) |
| `263df32` | Per-attempt sufficiency diagnostics (M3.2 observability) |
| `55d8b0f` | First-pass semantic contract alignment (M3.4) |
| `dfd2e16` | Resolvability boundary hardening (M3.5) |

Related architecture decisions: ADR-022 (M1/M2 foundation), ADR-023 (M3 production boundary). This document records runtime acceptance evidence; ADRs are not modified for acceptance recording.
