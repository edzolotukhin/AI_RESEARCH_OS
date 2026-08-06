from __future__ import annotations

from typing import Any

from application.contracts.base_executor import BaseExecutor
from application.research_quality.research_readiness_service import SHARED_STATE_KEY
from application.runtime.task_result_codec import capture_task_result
from domain.research_quality.research_outcome import ResearchOutcome

from runtime.workflow_context import WorkflowContext


class DeterministicResearchReadinessExecutor(BaseExecutor):
    """
    Smoke/test readiness executor that always reports ready_for_analysis.

    Used when ApplicationConfig.deterministic_stage_executors is enabled.
    """

    def run(self, context: WorkflowContext) -> WorkflowContext:
        payload: dict[str, Any] = {
            "research_outcome": ResearchOutcome.READY_FOR_ANALYSIS.value,
            "ready_for_analysis": True,
            "research_question_assessments": [],
            "blocking_research_question_ids": [],
            "blocking_information_need_ids": [],
            "targeted_research_required": False,
            "termination_reason": "",
        }
        context.write_shared(SHARED_STATE_KEY, payload)

        completed = list(context.read_shared("_deterministic_stages_completed") or [])
        completed.append("assess_research_readiness")
        context.write_shared("_deterministic_stages_completed", completed)

        task = context.current_task
        if task is not None:
            context.intermediate_results[task.id] = capture_task_result(
                context,
                task.id,
            )
        return context
