from __future__ import annotations

import json
from dataclasses import replace
from unittest import TestCase

from application.factories.research_design_factory import ResearchDesignFactory
from application.parsers.research_design_parser import ResearchDesignParser
from application.planner.deterministic_design_response import (
    build_deterministic_design_response,
)
from application.planner.design_service import PlannerDesignServiceImpl
from application.planner.objective_coverage import (
    ObjectiveCoverageValidationError,
    evaluate_objective_coverage,
)
from application.prompts.builders.planner_prompt_builder import PlannerPromptBuilder
from application.prompts.file_template_loader import FileTemplateLoader
from application.prompts.python_format_prompt_renderer import PythonFormatPromptRenderer
from domain.planning.research_design import (
    OBJECTIVE_REFERENCE_CONTRACT_IDS_V1,
)
from domain.project import Project
from domain.research_brief import ResearchBrief
from domain.workflow_run import WorkflowRun
from runtime.workflow_context import WorkflowContext
from tests.helpers.executor_catalog import make_test_executor_catalog


class ObjectiveIdsV1Tests(TestCase):
    def _project(self, objectives=("Measure population", "Compare change")) -> Project:
        brief = ResearchBrief(
            title="Population",
            business_question="How did population change?",
            objectives=objectives,
        ).materialize_objective_registry()
        project = Project(id="objective-ids", name="Objective IDs", selected_methods=("DESK",))
        project.research_brief = brief
        return project

    def _payload(self, project: Project) -> dict:
        prompt = PlannerPromptBuilder(
            template_loader=FileTemplateLoader(),
            prompt_renderer=PythonFormatPromptRenderer(),
            executor_catalog=make_test_executor_catalog(),
        ).build(WorkflowContext(workflow_run=WorkflowRun(id="planner"), project=project))
        return json.loads(build_deterministic_design_response(prompt))

    def _design(self, project: Project):
        return PlannerDesignServiceImpl(
            response_parser=ResearchDesignParser(),
            design_factory=ResearchDesignFactory(),
        ).create_design(project, self._payload(project))

    def test_planner_response_and_domain_design_use_registry_ids(self):
        project = self._project()
        payload = self._payload(project)

        self.assertEqual(payload["objective_reference_contract"], OBJECTIVE_REFERENCE_CONTRACT_IDS_V1)
        refs = {
            ref
            for question in payload["research_questions"]
            for ref in question["objective_refs"]
        }
        self.assertEqual(refs, {"obj-001", "obj-002"})

        design = self._design(project)
        self.assertEqual(design.objective_reference_contract, OBJECTIVE_REFERENCE_CONTRACT_IDS_V1)
        self.assertEqual(design.brief_fingerprint[:3], "v2:")
        self.assertEqual(design.objective_registry_identity, project.research_brief.objective_registry_identity)
        self.assertIsNone(evaluate_objective_coverage(project.research_brief, design))

    def test_unknown_foreign_and_duplicate_ids_fail_closed(self):
        project = self._project()
        valid = self._payload(project)

        unknown = json.loads(json.dumps(valid))
        unknown["research_questions"][0]["objective_refs"] = ["obj-999"]
        with self.assertRaises(ObjectiveCoverageValidationError):
            self._design_from_payload(project, unknown)

        foreign = self._project(("Other objective", "Another objective"))
        valid_design = self._design(project)
        foreign_failure = evaluate_objective_coverage(foreign.research_brief, valid_design)
        self.assertIsNotNone(foreign_failure)
        self.assertEqual(len(foreign_failure.invalid_objective_refs), 2)

        duplicate = json.loads(json.dumps(valid))
        duplicate["research_questions"][1]["objective_refs"] = ["obj-001"]
        with self.assertRaises(ObjectiveCoverageValidationError):
            self._design_from_payload(project, duplicate)

    def test_stale_v2_fingerprint_fails_even_with_same_registry(self):
        project = self._project()
        design = self._design(project)
        failure = evaluate_objective_coverage(
            project.research_brief,
            replace(design, brief_fingerprint="v2:stale"),
            expected_brief_fingerprint="v2:current",
        )
        self.assertIsNotNone(failure)
        self.assertTrue(failure.brief_fingerprint_mismatch)

    def test_missing_v2_registry_identity_fails_closed(self):
        project = self._project()
        design = replace(self._design(project), objective_registry_identity="")
        failure = evaluate_objective_coverage(project.research_brief, design)
        self.assertIsNotNone(failure)
        self.assertTrue(failure.registry_identity_mismatch)

    def test_incomplete_id_coverage_fails_closed(self):
        project = self._project()
        design = self._design(project)
        first = replace(design.research_questions[0], objective_refs=("obj-001",))
        incomplete = replace(design, research_questions=(first,))
        failure = evaluate_objective_coverage(project.research_brief, incomplete)
        self.assertIsNotNone(failure)
        self.assertEqual(failure.uncovered_objectives, ("Compare change",))

    def test_legacy_text_contract_remains_supported(self):
        project = self._project()
        payload = self._payload(project)
        payload["objective_reference_contract"] = "legacy_text_v1"
        for question in payload["research_questions"]:
            question["objective_refs"] = [
                project.research_brief.objectives[
                    min(int(ref.removeprefix("obj-")) - 1, len(project.research_brief.objectives) - 1)
                ]
                for ref in question["objective_refs"]
            ]
        design = self._design_from_payload(project, payload)
        self.assertEqual(design.objective_reference_contract, "legacy_text_v1")
        self.assertIsNone(evaluate_objective_coverage(project.research_brief, design))

    def _design_from_payload(self, project: Project, payload: dict):
        return PlannerDesignServiceImpl(
            response_parser=ResearchDesignParser(),
            design_factory=ResearchDesignFactory(),
        ).create_design(project, payload)
