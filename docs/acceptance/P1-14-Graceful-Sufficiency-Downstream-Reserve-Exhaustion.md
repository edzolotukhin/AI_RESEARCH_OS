# P1-14 — Graceful Sufficiency Downstream-Reserve Exhaustion

**Date:** 2026-08-11
**Branch:** `acceptance/live-desk-research-01`
**Mode:** Implementation + offline acceptance
**Live / commit / push:** none

---

## A. Executive verdict

**PASS** — PROPERTY S satisfied offline.

`downstream_reserve_exhausted` during Sufficiency/readiness is now a **controlled NOT READY stop**: no extra LLM call, Analysis/Report/Review skipped, workflow can **complete** with `insufficient_research`, without converting legitimate fail-closed research into workflow **FAILED**.

Budgets and `ExecutionBudget` reserve math unchanged.

---

## B. Exact old failure path

```
ResearchLoopService.run_bounded_loop
→ sufficiency_budget_available()
→ ExecutionBudget.assert_can_call("sufficiency")
→ BudgetExhaustedError(downstream_reserve_exhausted)
→ is_sufficiency_graceful_budget_stop == False  (only stage-cap was graceful)
→ exception re-raised
→ ResearchReadinessService / ResearchReadinessExecutor
→ readiness task FAILED
→ WorkflowCompletionPolicy → workflow FAILED
```

Files:
`application/research_quality/budget_aware_readiness.py`
`application/execution/budget_utils.py`
`application/research_quality/research_loop_service.py`
`application/research_quality/research_readiness_service.py`
`application/execution/execution_budget.py` (unchanged math)

---

## C. Root cause

Sufficiency pre-check treated reserve exhaustion as a hard failure, while Evidence treated the same reason as graceful, and domain already listed `downstream_reserve_exhausted` in `BUDGET_CONTROLLED_TERMINATION_REASONS`. At global≥59 the loop hard-failed before Evidence-remediation graceful stop.

---

## D. Exact implementation

1. `is_sufficiency_graceful_budget_stop` — also true for `downstream_reserve_exhausted`.
2. `sufficiency_unavailable_reason()` — mirrors Evidence; returns graceful reason or raises unexpected budget errors.
3. `sufficiency_budget_available()` — delegates to that helper.
4. `apply_sufficiency_budget_termination(..., reason=)` — maps stage-cap → `sufficiency_budget_exhausted`; preserves `downstream_reserve_exhausted`.
5. Loop / readiness service pass through `reason=exc.reason` / unavailable reason.
6. Named `DOWNSTREAM_RESERVE_EXHAUSTED` in domain termination reasons (same string).

**Not changed:** `ExecutionBudget` reserve formula, stage caps, Search, ranking, Evidence extraction, Sufficiency judgement, entailment, Report, Review.

---

## E. Controlled termination semantics

When reserve blocks the next Sufficiency call:

- no LLM call issued;
- prior assessments preserved;
- `ready_for_analysis=false`;
- `targeted_research_required=false`;
- `research_outcome=insufficient_research`;
- gate skips Analysis/Report/Review;
- workflow completion path remains COMPLETED+SKIPPED.

---

## F. Termination-reason behavior

| Condition | Reason |
| --- | --- |
| Sufficiency stage cap | `sufficiency_budget_exhausted` (unchanged) |
| Downstream reserve blocks Sufficiency | **`downstream_reserve_exhausted`** (preserved) |
| Evidence remediation first at global=58 | `evidence_remediation_budget_exhausted` (unchanged) |

---

## G. Fail-closed proof

CASE 2/5/10: blocking INs remain non-sufficient; `ready_for_analysis=false`; Analysis skipped. No synthetic SUFFICIENT assessments.

---

## H. Downstream reserve proof

CASE 4/12: at total=59, stop consumes **zero** additional calls; Analysis/Report/Review stage calls remain 0. Reserve capacity not spent to “pretty-print” the terminal.

---

## I. CASE 1–12 results

All covered by `tests/application/research_quality/test_p1_14_graceful_sufficiency_downstream_reserve.py` — **13 OK**.

| Case | Result |
| --- | --- |
| 1 Stage cap | OK |
| 2 Reserve graceful + complete | OK |
| 3 Boundary 58 allows | OK |
| 4 Boundary 59 blocks, no extra call | OK |
| 5 Analysis skipped | OK |
| 6 Assessments unchanged | OK |
| 7 Both exhausted → reserve first causal | OK |
| 8 Unexpected budget still raises | OK |
| 9 Provider error still fails | OK |
| 10 P1-12-shaped completed | OK |
| 11 P1-10-shaped evidence stop | OK |
| 12 No downstream consumption | OK |

---

## J. P1-10 regression

CASE 11: global=58 + Evidence exhausted → `evidence_remediation_budget_exhausted`, ready=false, total stays 58.

---

## K. P1-12 regression

CASE 2/7/10: global=59 → controlled `downstream_reserve_exhausted`, workflow COMPLETED with downstream skipped (no FAILED).

---

## L. P1-07 / P1-08 / P1-09 regressions

Targeted packs exercised via full suite. Known pre-existing isolation test noise outside this change not repaired. Full suite green after parking untracked forensic scripts (restored).

---

## M. Full-suite exact result

```
Ran 1535 tests in 25.284s
OK (skipped=91)
```

---

## N. git diff --check

See final response.

---

## O. git status --short

See final response.

---

## P. Remaining risks

- Live organic re-acceptance still needed to confirm PROPERTY S under real LLM/remediation timing.
- Reserve still ignores READY (MODEL mix remains by design for `assert_can_call`); only classification/control-flow fixed.
- XLSX / primary workbook ingestion still open.

---

## Q. XLSX capability-gap status

**OUT OF SCOPE** for P1-14. Remains separate research-capability milestone candidate.

---

## R. Commit recommendation

**READY TO COMMIT when asked** — include production files + P1-14 tests + this acceptance doc. Do not auto-commit.

Suggested scope:

- `application/execution/budget_utils.py`
- `application/research_quality/budget_aware_readiness.py`
- `application/research_quality/research_loop_service.py`
- `application/research_quality/research_readiness_service.py`
- `domain/research_quality/research_termination_reason.py`
- `tests/application/research_quality/test_p1_14_graceful_sufficiency_downstream_reserve.py`
- `docs/acceptance/P1-14-Graceful-Sufficiency-Downstream-Reserve-Exhaustion.md`

---

## S. Future live re-acceptance

**GO** — separately authorize one organic Brief re-run after commit/deploy of P1-14 (and with P1-12 ranking present). Not authorized inside this milestone.

---

**STOP.** No live run. No commit. No push. No XLSX.
