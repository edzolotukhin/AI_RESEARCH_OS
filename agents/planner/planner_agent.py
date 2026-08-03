from __future__ import annotations

import json
import os

from agents.base_agent import BaseAgent

from application.planner.contracts import PlannerDesignService, ResearchDesignWorkflowMapperProtocol
from application.planner.objective_coverage import ObjectiveCoverageValidationError
from application.planner.research_design_payload_contract import (
    ResearchDesignPayloadContract,
)
from application.prompts.builders.planner_prompt_builder import (
    PlannerPromptBuilder,
)
from application.structured_output.correction_prompt import (
    StructuredOutputCorrectionPromptBuilder,
)
from application.structured_output.generator import StructuredOutputGenerator

from runtime.workflow_context import WorkflowContext

DEFAULT_PLANNER_SEMANTIC_MAX_ATTEMPTS = 3


class PlannerAgent(BaseAgent):
    """
    Single planning authority: transforms ResearchBrief into ResearchDesign
    and deterministically derives WorkflowTemplate.
    """

    def __init__(
        self,
        planner_design_service: PlannerDesignService,
        workflow_mapper: ResearchDesignWorkflowMapperProtocol,
        prompt_builder: PlannerPromptBuilder,
        structured_output_generator: StructuredOutputGenerator,
        payload_contract: ResearchDesignPayloadContract,
        *,
        semantic_max_attempts: int | None = None,
        correction_prompt_builder: StructuredOutputCorrectionPromptBuilder | None = None,
    ) -> None:
        super().__init__("planner")

        self._planner_design_service = planner_design_service
        self._workflow_mapper = workflow_mapper
        self._prompt_builder = prompt_builder
        self._structured_output_generator = structured_output_generator
        self._payload_contract = payload_contract
        self._semantic_max_attempts = (
            semantic_max_attempts
            if semantic_max_attempts is not None
            else int(os.environ.get(
                "PLANNER_SEMANTIC_MAX_ATTEMPTS",
                str(DEFAULT_PLANNER_SEMANTIC_MAX_ATTEMPTS),
            ))
        )
        self._correction_prompt_builder = (
            correction_prompt_builder or StructuredOutputCorrectionPromptBuilder()
        )

    def run(
        self,
        context: WorkflowContext,
    ) -> WorkflowContext:
        context.execution_metadata["agent"] = self.name
        context.execution_metadata["state"] = "running"

        original_prompt = self._prompt_builder.build(context)
        current_prompt = original_prompt
        brief = context.project.research_brief

        research_design = None
        last_coverage_error: ObjectiveCoverageValidationError | None = None

        for semantic_attempt in range(1, self._semantic_max_attempts + 1):
            design_data = self._structured_output_generator.generate(
                current_prompt,
                payload_contract=self._payload_contract,
            )

            try:
                research_design = self._planner_design_service.create_design(
                    context.project,
                    design_data,
                )
                self._record_semantic_diagnostics(
                    context,
                    attempt=semantic_attempt,
                    uncovered_objectives=(),
                    correction_applied=semantic_attempt > 1,
                )
                break
            except ObjectiveCoverageValidationError as exc:
                last_coverage_error = exc
                self._record_semantic_diagnostics(
                    context,
                    attempt=semantic_attempt,
                    uncovered_objectives=exc.uncovered_objectives,
                    invalid_objective_refs=exc.invalid_objective_refs,
                    correction_applied=False,
                )

                if semantic_attempt >= self._semantic_max_attempts:
                    raise

                current_prompt = self._correction_prompt_builder.build_objective_coverage_correction(
                    original_prompt=original_prompt,
                    brief=brief,
                    failure=exc,
                    previous_design_json=json.dumps(design_data, ensure_ascii=True),
                    planner_bounds=self._payload_contract.bounds,
                )
                context.execution_metadata["planner_semantic_correction"][
                    "correction_applied"
                ] = True

        if research_design is None:
            if last_coverage_error is not None:
                raise last_coverage_error
            raise RuntimeError("PlannerAgent completed without a research design.")

        context.workflow_template = (
            self._workflow_mapper.from_research_design(
                research_design,
                context.project,
            )
        )

        context.execution_metadata["state"] = "completed"

        return context

    @staticmethod
    def _record_semantic_diagnostics(
        context: WorkflowContext,
        *,
        attempt: int,
        uncovered_objectives: tuple[str, ...],
        invalid_objective_refs: tuple[tuple[str, str], ...] = (),
        correction_applied: bool,
    ) -> None:
        context.execution_metadata["planner_semantic_correction"] = {
            "attempt": attempt,
            "uncovered_objective_count": len(uncovered_objectives),
            "uncovered_objectives": list(uncovered_objectives),
            "invalid_objective_refs": [
                {"question_id": question_id, "ref": ref}
                for question_id, ref in invalid_objective_refs
            ],
            "correction_applied": correction_applied,
        }
