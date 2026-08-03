"""Serbia Microgreens objective-coverage semantic correction regression tests."""

from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import Mock

from agents.planner.planner_agent import PlannerAgent

from application.factories.research_design_factory import ResearchDesignFactory
from application.parsers.research_design_parser import ResearchDesignParser
from application.planner.design_service import PlannerDesignServiceImpl
from application.planner.objective_coverage import ObjectiveCoverageValidationError
from application.planner.planner_bounds import PlannerBounds
from application.planner.research_design_payload_contract import (
    ResearchDesignPayloadContract,
)
from application.planner.research_design_workflow_mapper import (
    ResearchDesignWorkflowMapper,
)
from application.research.design_validator import find_uncovered_objectives
from application.structured_output.correction_prompt import (
    StructuredOutputCorrectionPromptBuilder,
)
from application.structured_output.generator import StructuredOutputGenerator
from application.structured_output.parser import StructuredOutputParser

from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt
from domain.project import Project
from domain.workflow_run import WorkflowRun

from runtime.workflow_context import WorkflowContext

from tests.fixtures.serbia_bounded_research_design import (
    SERBIA_BOUNDED_RESEARCH_DESIGN,
    SERBIA_BOUNDED_RESEARCH_DESIGN_JSON,
)
from tests.fixtures.serbia_microgreens_brief import serbia_microgreens_brief
from tests.fixtures.serbia_missing_objective_design import (
    SERBIA_MISSING_ENTRY_OBJECTIVE_DESIGN_JSON,
    SERBIA_MISSING_ENTRY_OBJECTIVE_TEXT,
)


class SerbiaObjectiveCoverageCorrectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bounds = PlannerBounds()
        self.brief = serbia_microgreens_brief()
        self.project = Project(
            id="project-serbia",
            name="Serbia Microgreens",
            research_brief=self.brief,
        )
        self.prompt = Prompt(system="Planner system", user="Serbia brief prompt")
        self.design_service = PlannerDesignServiceImpl(
            response_parser=ResearchDesignParser(),
            design_factory=ResearchDesignFactory(),
        )
        self.payload_contract = ResearchDesignPayloadContract(bounds=self.bounds)
        self.correction_builder = StructuredOutputCorrectionPromptBuilder()

    def test_correction_prompt_contains_missing_objective_and_repair_instruction(
        self,
    ) -> None:
        failure = ObjectiveCoverageValidationError(
            "ResearchDesign does not cover brief objectives: "
            + SERBIA_MISSING_ENTRY_OBJECTIVE_TEXT,
            uncovered_objectives=(SERBIA_MISSING_ENTRY_OBJECTIVE_TEXT,),
        )
        correction = self.correction_builder.build_objective_coverage_correction(
            original_prompt=self.prompt,
            brief=self.brief,
            failure=failure,
            previous_design_json=SERBIA_MISSING_ENTRY_OBJECTIVE_DESIGN_JSON,
            planner_bounds=self.bounds,
        )

        self.assertIn("UNCOVERED BRIEF OBJECTIVES", correction.user)
        self.assertIn(SERBIA_MISSING_ENTRY_OBJECTIVE_TEXT, correction.user)
        self.assertIn("Repair objective_refs", correction.user)
        self.assertIn("exact brief objective text verbatim", correction.user)
        self.assertIn("CANONICAL BRIEF OBJECTIVES", correction.user)

    def test_second_synthetic_response_covers_all_ten_objectives_within_bounds(
        self,
    ) -> None:
        payload = json.loads(SERBIA_BOUNDED_RESEARCH_DESIGN_JSON)
        self.assertLessEqual(
            len(payload["research_questions"]),
            self.bounds.max_research_questions,
        )
        design = self.design_service.create_design(self.project, payload)
        uncovered = find_uncovered_objectives(self.brief, design)
        self.assertEqual(uncovered, ())
        self.assertEqual(len(self.brief.objectives), 10)

    def test_planner_agent_retries_semantic_correction_and_succeeds(self) -> None:
        llm_client = Mock()
        llm_client.generate.side_effect = [
            LLMResponse(content=SERBIA_MISSING_ENTRY_OBJECTIVE_DESIGN_JSON),
            LLMResponse(content=SERBIA_BOUNDED_RESEARCH_DESIGN_JSON),
        ]
        generator = StructuredOutputGenerator(
            llm_client=llm_client,
            parser=StructuredOutputParser(),
            max_attempts=1,
        )
        agent = PlannerAgent(
            planner_design_service=self.design_service,
            workflow_mapper=ResearchDesignWorkflowMapper(),
            prompt_builder=Mock(build=Mock(return_value=self.prompt)),
            structured_output_generator=generator,
            payload_contract=self.payload_contract,
            semantic_max_attempts=2,
        )
        context = WorkflowContext(
            project=self.project,
            workflow_run=WorkflowRun(id="planning-serbia"),
        )

        result = agent.run(context)

        self.assertIsNotNone(result.workflow_template)
        self.assertEqual(llm_client.generate.call_count, 2)
        diagnostics = result.execution_metadata["planner_semantic_correction"]
        self.assertEqual(diagnostics["uncovered_objective_count"], 0)
        self.assertTrue(diagnostics["correction_applied"])
        second_prompt = llm_client.generate.call_args_list[1].args[0]
        self.assertIn("OBJECTIVE COVERAGE CORRECTION", second_prompt.user)
        self.assertIn(SERBIA_MISSING_ENTRY_OBJECTIVE_TEXT, second_prompt.user)

    def test_invalid_objective_ref_rejected_and_not_accepted_as_phantom(self) -> None:
        payload = json.loads(SERBIA_BOUNDED_RESEARCH_DESIGN_JSON)
        payload["research_questions"][0]["objective_refs"] = [
            "Phantom objective not in brief.",
        ]
        with self.assertRaises(ObjectiveCoverageValidationError) as ctx:
            self.design_service.create_design(self.project, payload)
        self.assertEqual(ctx.exception.invalid_objective_refs[0][1], "Phantom objective not in brief.")

    def test_cardinality_bounds_remain_enforced_after_semantic_correction_path(
        self,
    ) -> None:
        payload = copy.deepcopy(SERBIA_BOUNDED_RESEARCH_DESIGN)
        payload["research_questions"].append(
            {
                "id": "rq-extra",
                "question": "Extra?",
                "objective_refs": [self.brief.objectives[0]],
                "priority": 5,
                "rationale": "Overflow.",
            },
        )
        contract = ResearchDesignPayloadContract(bounds=self.bounds)
        self.assertFalse(contract.accepts(payload))
        self.assertIn("research_questions count", contract.last_validation_error)

    def test_exhausted_semantic_retries_raise_validation_error(self) -> None:
        llm_client = Mock()
        llm_client.generate.return_value = LLMResponse(
            content=SERBIA_MISSING_ENTRY_OBJECTIVE_DESIGN_JSON,
        )
        generator = StructuredOutputGenerator(
            llm_client=llm_client,
            parser=StructuredOutputParser(),
            max_attempts=1,
        )
        agent = PlannerAgent(
            planner_design_service=self.design_service,
            workflow_mapper=ResearchDesignWorkflowMapper(),
            prompt_builder=Mock(build=Mock(return_value=self.prompt)),
            structured_output_generator=generator,
            payload_contract=self.payload_contract,
            semantic_max_attempts=2,
        )
        context = WorkflowContext(
            project=self.project,
            workflow_run=WorkflowRun(id="planning-serbia"),
        )

        with self.assertRaises(ObjectiveCoverageValidationError) as ctx:
            agent.run(context)

        self.assertIn(SERBIA_MISSING_ENTRY_OBJECTIVE_TEXT, str(ctx.exception))
        diagnostics = context.execution_metadata["planner_semantic_correction"]
        self.assertEqual(diagnostics["attempt"], 2)
        self.assertEqual(diagnostics["uncovered_objective_count"], 1)
        self.assertEqual(llm_client.generate.call_count, 2)


if __name__ == "__main__":
    unittest.main()
