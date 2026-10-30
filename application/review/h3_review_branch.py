from __future__ import annotations

from typing import Any

from application.report.contract_selection import (
    DESK_REPORT_CONTRACT_PIN,
    H3_REPORT_CONTRACT,
)
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus


H3_REVIEW_BRANCH_KEY = "h3_review_branch"
H3_REVIEW_EXHAUSTED = "REPORT_REVIEW_EXHAUSTED"
H3_REVIEW_1_DEFINITION = "task-review-report-1"
H3_REVISION_DEFINITION = "task-revise-report"
H3_REVIEW_2_DEFINITION = "task-review-report-2"
H3_FINALIZATION_DEFINITION = "task-finalize-deliverables"


class H3ReviewBranchError(RuntimeError):
    pass


def h3_review_round(context) -> int | None:
    task = context.current_task
    definition_id = str(getattr(task, "definition_id", ""))
    if definition_id == H3_REVIEW_1_DEFINITION:
        return 1
    if definition_id == H3_REVIEW_2_DEFINITION:
        return 2
    return None


class H3ReviewBranchController:
    """Normalize the finite H3 Review branch from persisted decisions."""

    def apply_review_result(self, context, summary) -> dict[str, Any] | None:
        if context.read_shared(DESK_REPORT_CONTRACT_PIN) != H3_REPORT_CONTRACT:
            return None
        round_number = h3_review_round(context)
        if round_number is None:
            raise H3ReviewBranchError("h3_review_task_identity_invalid")
        decision = str(summary.verdict).lower()
        if decision not in {"approve", "revise", "reject"}:
            raise H3ReviewBranchError("h3_review_decision_invalid")
        if round_number == 1:
            return self._round_one(context, summary, decision)
        return self._round_two(context, summary, decision)

    def reconcile(self, context) -> dict[str, Any] | None:
        if context.read_shared(DESK_REPORT_CONTRACT_PIN) != H3_REPORT_CONTRACT:
            return None
        review_two = context.read_shared("review_2")
        if isinstance(review_two, dict):
            return self._round_two(context, _Summary(review_two), str(review_two.get("verdict", "")))
        review_one = context.read_shared("review_1")
        if isinstance(review_one, dict):
            return self._round_one(context, _Summary(review_one), str(review_one.get("verdict", "")))
        return context.read_shared(H3_REVIEW_BRANCH_KEY)

    def _round_one(self, context, summary, decision: str) -> dict[str, Any]:
        decision = decision.lower()
        state = self._state(round_number=1, decision=decision, revision_count=0)
        if decision == "approve":
            self._satisfied_skip(context, H3_REVISION_DEFINITION)
            self._satisfied_skip(context, H3_REVIEW_2_DEFINITION)
            state["finalization_eligible"] = True
            context.write_shared("review", summary.to_dict())
        elif decision == "revise":
            context.shared_state.pop("review", None)
        else:
            context.shared_state.pop("review", None)
            state["terminal_reason"] = "REPORT_REVIEW_REJECTED"
            self._block_finalization(context)
            self._fail_run(context)
        context.write_shared(H3_REVIEW_BRANCH_KEY, state)
        return state

    def _round_two(self, context, summary, decision: str) -> dict[str, Any]:
        decision = decision.lower()
        state = self._state(round_number=2, decision=decision, revision_count=1)
        if decision == "approve":
            state["finalization_eligible"] = True
            context.write_shared("review", summary.to_dict())
        else:
            context.shared_state.pop("review", None)
            state["terminal_reason"] = (
                H3_REVIEW_EXHAUSTED if decision == "revise" else "REPORT_REVIEW_REJECTED"
            )
            self._block_finalization(context)
            self._fail_run(context)
        context.write_shared(H3_REVIEW_BRANCH_KEY, state)
        return state

    @staticmethod
    def _state(*, round_number: int, decision: str, revision_count: int) -> dict[str, Any]:
        return {
            "contract": H3_REPORT_CONTRACT,
            "round": round_number,
            "decision": decision,
            "revision_count": revision_count,
            "finalization_eligible": False,
            "terminal_reason": None,
        }

    @staticmethod
    def _task(context, definition_id: str):
        task = next(
            (task for task in context.workflow_run.tasks if task.definition_id == definition_id),
            None,
        )
        if task is None and definition_id == H3_FINALIZATION_DEFINITION:
            task = next(
                (task for task in context.workflow_run.tasks if task.executor_id == "finalization"),
                None,
            )
        return task

    def _satisfied_skip(self, context, definition_id: str) -> None:
        task = self._task(context, definition_id)
        if task is None:
            raise H3ReviewBranchError(f"h3_branch_task_missing:{definition_id}")
        if task.status is not TaskStatus.SKIPPED:
            if task.is_terminal:
                raise H3ReviewBranchError(f"h3_branch_task_already_terminal:{definition_id}")
            task.skip()
        context.workflow_run.satisfied_skipped_task_ids.add(task.id)

    def _block_finalization(self, context) -> None:
        task = self._task(context, H3_FINALIZATION_DEFINITION)
        if task is not None and not task.is_terminal:
            task.skip()

    @staticmethod
    def _fail_run(context) -> None:
        if context.workflow_run.status is WorkflowStatus.RUNNING:
            context.workflow_run.fail()


class _Summary:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = dict(payload)
        self.verdict = str(payload.get("verdict", ""))

    def to_dict(self) -> dict[str, Any]:
        return dict(self._payload)
