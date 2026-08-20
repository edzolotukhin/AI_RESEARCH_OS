# P1-31B — Terminal Reconciliation Path Completeness

## Verdict

PROPERTY AJ passes offline. The systematic finalization gap is closed without
changing PROPERTY AI semantics, budgets, persistence, retrieval, grounding, or
Sufficiency criteria.

## Root cause

Terminal Evidence reconciliation was owned by one `ResearchLoopService`
`BudgetExhaustedError` branch. Legitimate results returned by other loop exits,
including the P1-31 Evidence-remediation capacity pre-check, could proceed to
gating and persistence without terminal per-InformationNeed fingerprints.

## Old topology

`ResearchLoopService` conditionally reconciled one mid-Sufficiency budget-stop
path. Other READY and controlled-NOT_READY candidates flowed directly into
`ResearchReadinessService._persist()`.

## New topology

`ResearchReadinessService.assess_and_apply()` now has one common terminal
authority boundary:

1. produce a candidate readiness result;
2. complete any bounded remediation loop or controlled budget fallback;
3. call `_finalize_terminal_readiness()`;
4. apply the readiness gate;
5. persist and expose the reconciled result.

The boundary always calls `reconcile_terminal_readiness()` against the final
durable Evidence set. The prior path-specific reconciliation is therefore
idempotently verified again at the authoritative boundary, preventing either
incomplete aggregates or post-reconciliation Evidence changes from being
trusted silently.

The deterministic production Sufficiency evaluator now records the same
completed-assessment fingerprint continuity as the hybrid evaluator. This is
metadata continuity only; it makes no extra model or provider call.

## PROPERTY AI semantics preserved

- Matching completed-assessment and terminal Evidence fingerprints remain
  current and authoritative.
- Changed Evidence preserves the prior verdict only as explicitly stale and
  non-current.
- Zero terminal Evidence remains current `MISSING/0`.
- A stale `SUFFICIENT` assessment cannot unlock analysis.
- A newer per-IN cache cannot be replaced by an older complete aggregate.
- Reconciliation does not rerun Sufficiency.

## Terminal path matrix

| Terminal class | Result |
| --- | --- |
| Initial READY | Reconciled before READY authority and persistence |
| Normal NOT_READY / no actionable gaps | Reconciled at common boundary |
| No material improvement | Reconciled at common boundary |
| Maximum rounds | Reconciled at common boundary |
| Evidence-remediation budget exhausted pre-check | Reconciled at common boundary |
| Evidence-remediation zero-Evidence early return | Reconciled at common boundary |
| Downstream reserve exhausted mid-Sufficiency | Existing partial reconciliation remains idempotent at common boundary |
| Downstream reserve exhausted Evidence pre-check | Reconciled without requiring an exception |
| Initial Sufficiency budget fallback | Reconciled; zero Evidence is `MISSING/0` |
| Outer readiness-service controlled catch | Reconciled before gating/persistence |
| Post-assessment Evidence mutation | Explicitly stale/non-current |
| Stale SUFFICIENT | READY denied |
| Zero Evidence | Current `MISSING/0` |

Controlled NOT_READY reasons and remediation history remain product outcomes,
not execution failures. Pending remediation markers and completed history retain
their existing loop semantics.

## P1-31 replay

The offline replay follows the live failure shape: a cached assessment is
reused, no new Evidence is added, no model exception occurs, and the next-loop
capacity pre-check returns `downstream_reserve_exhausted`. The common boundary
populates terminal count and both fingerprints before persistence. Exactly one
initial evaluator call is observed.

## READY and serialization safety

Initial READY is reconciled before downstream gating. A post-assessment Evidence
mutation makes an otherwise SUFFICIENT result stale and keeps analysis locked.
The persisted raw readiness payload retains `assessment_current`, assessed and
terminal fingerprints, and `terminal_evidence_count`.

## Offline acceptance

- PROPERTY AJ focused path matrix: 8/8 pass.
- PROPERTY AJ + PROPERTY AI + targeted loop: 49/49 pass.
- Application research-quality: 431/431 pass.
- Domain research-quality: 138/138 pass.
- PROPERTY AG/AF/AE, P1-17.1, P1-14, P1-21–P1-26, P1-19/P1-20 focused
  regression group: 447/447 pass.
- Production deterministic full-pipeline regression: pass.
- Full suite: 1,960 tests, 0 failures, 0 errors, 91 skipped.

Forty-two pre-existing untracked scanner-interfering helpers were parked
narrowly. All 42 were restored and verified by SHA-256 and byte size; mismatch
count was zero.

## Changed scope

Production:

- `application/research_quality/research_readiness_service.py`
- `application/research_quality/deterministic_research_sufficiency_evaluator.py`

Tests and fixtures:

- `tests/application/research_quality/test_p1_31b_terminal_reconciliation_path_completeness.py`
- existing readiness/loop/acceptance fixtures updated to represent completed
  assessments with durable Evidence and fingerprints

Documentation:

- this acceptance document

## Non-goals and impact

No schema, migration, dependency, budget, provider, prompt, retrieval,
grounding, acquisition-coverage, Source-to-IN, or PROPERTY AH change was made.
Provider calls, live LLM calls, paid/live Research, new Research, and existing
run mutation were all zero.

## Remaining risk and recommendation

The common boundary is behaviorally covered across recognized terminal classes.
Future readiness-producing entry points outside `ResearchReadinessService` must
continue to use this service boundary. The separate P1-31 acquisition-coverage
finding remains out of scope.

Commit recommendation: `READY_TO_COMMIT` through a separately authorized gate.
Do not rerun New Zealand automatically. The next action is the offline commit
gate, followed by push/runtime refresh if separately authorized; then decide
between PROPERTY AJ live re-acceptance and the acquisition-coverage forensic.
