"""Patch 6: real outcome resolution, read-only workspace and Ukrainian status."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from application.query.project_workspace_query_service import ProjectWorkspaceQueryService
from application.query.research_outcome_presentation import present_research_outcome
from application.query.research_run_result_query_service import ResearchRunResultQueryService
from application.query.desk_workbench_query_service import DeskWorkbenchQueryService
from application.query.research_status_query_service import ResearchStatusQueryService
from application.services.project_planning_service import ProjectPlanningService
from domain.workflow_status import WorkflowStatus
from infrastructure.persistence.memory.in_memory_workflow_run_repository import InMemoryWorkflowRunRepository
from infrastructure.persistence.memory.in_memory_finding_repository import InMemoryFindingRepository
from infrastructure.persistence.memory.in_memory_report_repository import InMemoryReportRepository
from infrastructure.persistence.memory.in_memory_review_repository import InMemoryReviewRepository
from infrastructure.persistence.memory.in_memory_artifact_repository import InMemoryArtifactRepository
from tests.application.analysis.test_executable_derivations import setup_memory
from tests.application.research_quality.test_classified_readiness import readiness
from tests.helpers.workflow_run_builder import make_workflow_run


class ResearchOutcomeUiTests(unittest.TestCase):
    def setup_projection(self, outcome="COMPLETED", *, findings=True, status="completed", missing=()):
        context, analysis, finding_repo, evidence, sources, provider = setup_memory()
        readiness(context, evidence, sources)
        analysis.analyze_for_context(context)
        if not findings:
            finding_repo = InMemoryFindingRepository()
        run = context.workflow_run
        run.ready()
        run.start()
        if status == "completed":
            run.complete()
        elif status == "failed":
            run.fail()
        self.run_repo = InMemoryWorkflowRunRepository()
        self.run_repo.create(run, project_id="project")
        self.shared = dict(context.shared_state)
        self.shared.pop("research_product_outcome", None)
        if outcome is not None:
            self.shared["research_product_outcome"] = dict(outcome=outcome, authoritative_post_analysis=True,
                unresolved_information_need_ids=list(missing))
        self.run_repo.save(run, expected_version=0, task_results={"analysis": {
            "definition_id": "task-analyze", "shared_state": self.shared}})
        self.reports = InMemoryReportRepository()
        self.results = ResearchRunResultQueryService(workflow_run_repository=self.run_repo, source_repository=sources,
            evidence_repository=evidence, finding_repository=finding_repo, insight_repository=analysis._insight_repository,
            report_repository=self.reports, review_repository=InMemoryReviewRepository(),
            artifact_repository=InMemoryArtifactRepository())
        context.project.owner_principal_id = "owner"
        context.project.research_design_status = "APPROVED"
        self.runs = [run]
        self.workflows = SimpleNamespace(list_workflow_runs_for_project=lambda project_id: self.runs,
            get_template=lambda template_id: context.workflow_template, get_task_results=self.run_repo.get_task_results)
        self.planning = SimpleNamespace(_order_desk_attempts=ProjectPlanningService._order_desk_attempts,
            explicit_or_inferred_methods=lambda project: ("DESK",), available_methods=lambda project: (),
            design_regeneration_eligibility=lambda project: (False, ""), design_is_current=lambda project: True)
        self.query = ProjectWorkspaceQueryService(project_service=SimpleNamespace(get_project=lambda project_id: context.project),
            workflow_service=self.workflows, quantitative_ui_service=None, research_result_service=self.results,
            project_planning_service=self.planning)
        self.context = context
        return self.query

    def workspace(self):
        return self.query.get("project", owner_id="owner")

    def test_outcome_mapping_and_execution_separation(self):
        cases = {"COMPLETED": "Завершено", "PARTIAL": "Завершено з обмеженнями",
                 "INSUFFICIENT": "Недостатньо матеріалів", "FAILED": "Технічна помилка"}
        for outcome, label in cases.items():
            self.assertEqual(present_research_outcome("completed", outcome).label, label)
            self.assertEqual(present_research_outcome("running", outcome).label, "Виконується")
        self.assertEqual(present_research_outcome("failed", "COMPLETED").label, "Технічна помилка")
        self.assertEqual(present_research_outcome("completed", None).label, "Результат не визначено")
        self.assertEqual(present_research_outcome("completed", "APPROVED").label, "Завершено")
        self.assertEqual(present_research_outcome("completed", "NOT_READY").label, "Недостатньо матеріалів")

    def test_completed_execution_insufficient_product_is_not_success(self):
        self.setup_projection("INSUFFICIENT", findings=False)
        view = self.workspace().desk
        self.assertEqual(view.state_label, "Недостатньо матеріалів")
        self.assertEqual(view.research_outcome, "INSUFFICIENT")
        self.assertEqual(view.execution_status, "TERMINAL")
        self.assertIsNone(view.progress)
        self.assertFalse(view.output.report_available)
        self.assertEqual(self.run_repo.get_by_id("run").status, WorkflowStatus.COMPLETED)

    def test_partial_uses_resolver_and_retains_unresolved_coverage(self):
        missing = "derived-YEAR_OVER_YEAR_PERCENT_CHANGE"
        self.setup_projection("PARTIAL", missing=(missing,))
        # Even with persisted Findings, the stronger coverage gate's missing ID
        # must not be lost by a query-time recomputation of the product outcome.
        view = self.workspace().desk
        self.assertEqual(view.state_label, "Завершено з обмеженнями")
        self.assertEqual(view.research_outcome, "PARTIAL")
        self.assertGreater(view.output.findings_count, 0)
        self.assertTrue(any("Не підтверджено" in reason for reason in view.insufficiency_reasons))

    def test_completed_product_does_not_invent_a_report(self):
        self.setup_projection()
        view = self.workspace().desk
        self.assertEqual(view.state_label, "Завершено")
        self.assertEqual(view.output.findings_count, 7)
        self.assertEqual(view.output.insights_count, 1)
        self.assertFalse(view.output.report_available)
        self.assertIn("окремо", view.explanation)

    def test_technical_failure_takes_priority_and_running_has_no_final_outcome(self):
        self.setup_projection("COMPLETED", status="failed")
        self.assertEqual(self.workspace().desk.state_label, "Технічна помилка")
        self.assertEqual(self.workspace().desk.research_outcome, "FAILED")
        self.setup_projection(status="running")
        self.assertEqual(self.workspace().desk.state_label, "Виконується")
        self.assertIsNone(self.workspace().desk.research_outcome)

    def test_missing_outcome_preserves_visible_materials_without_success(self):
        self.setup_projection(None)
        view = self.workspace().desk
        self.assertEqual(view.state_label, "Результат не визначено")
        self.assertEqual(view.output.findings_count, 7)
        self.assertIsNone(view.progress)

    def test_latest_insufficient_attempt_does_not_hide_successful_history_or_mutate_state(self):
        self.setup_projection()
        previous = deepcopy(self.run_repo.get_task_results("run"))
        new_id = ProjectPlanningService._desk_retry_run_id("project", "run")
        new = make_workflow_run(run_id=new_id, template_id="template")
        new.project_id = "project"
        new.ready(); new.start(); new.complete()
        self.run_repo.create(new, project_id="project")
        shared = deepcopy(self.shared)
        shared["research_product_outcome"]["outcome"] = "INSUFFICIENT"
        self.run_repo.save(new, expected_version=0, task_results={"analysis": {"definition_id": "task-analyze", "shared_state": shared}})
        self.runs = [new, self.context.workflow_run]  # Repository order is deliberately reversed.
        view = self.workspace()
        self.assertEqual(view.desk.run_id, new_id)
        self.assertEqual(view.desk.state_label, "Недостатньо матеріалів")
        self.assertEqual([r.state_label for r in view.desk_history], ["Недостатньо матеріалів", "Завершено"])
        self.assertIn("/ui/research/run/overview", [r.href for r in view.desk_history])
        self.assertEqual(self.run_repo.get_task_results("run"), previous)
        self.assertEqual(self.results.available_outputs_for_run("run")["findings_count"], 7)

    def test_readiness_reasons_are_ukrainian_and_durable_state_is_unchanged(self):
        self.setup_projection("INSUFFICIENT", findings=False)
        stored = self.run_repo.get_task_results("run")
        readiness_payload = stored["analysis"]["shared_state"]["research_readiness"]
        readiness_payload["blocking_information_need_ids"] = ["in-pop"]
        need = readiness_payload["research_question_assessments"][0]["information_need_assessments"][0]
        need.update(status="blocked", prerequisite_diagnostics={"reasons": ["unavailable_required_observations"]})
        self.run_repo.save(self.context.workflow_run, task_results=stored)
        before = deepcopy(self.run_repo.get_task_results("run"))
        reasons = self.workspace().desk.insufficiency_reasons
        self.assertIn("Бракує обов’язкових спостережень або періодів.", reasons)
        self.assertNotIn("unavailable_required_observations", " ".join(reasons))
        self.assertEqual(self.run_repo.get_task_results("run"), before)

    def test_file_availability_is_run_scoped_and_independent_of_product(self):
        self.setup_projection("INSUFFICIENT", findings=False)
        catalog = SimpleNamespace(desk=[SimpleNamespace(document=SimpleNamespace(run_id="previous"), pdf=object(), pptx=object()),
                                       SimpleNamespace(document=SimpleNamespace(run_id="run"), pdf=object(), pptx=None)])
        self.query.deliverables = SimpleNamespace(catalog=lambda project_id, owner_id: catalog)
        view = self.workspace().desk
        self.assertTrue(view.output.pdf_available)
        self.assertFalse(view.output.pptx_available)
        self.assertEqual(view.state_label, "Недостатньо матеріалів")

    def test_actual_report_remains_visible_when_product_outcome_is_missing(self):
        from domain.reports.report import Report
        self.setup_projection(None)
        report = Report(id="report", project_id="project", workflow_run_id="run", research_design_id="design",
            title="Збережений звіт", language="uk", sections=(), executive_summary="", limitations=(),
            created_at="2026-01-01T00:00:00Z", generation_method="synthetic-fixture", finding_refs=(),
            insight_refs=(), evidence_refs=(), citation_registry={}, deduplication_key="report", revision_number=1)
        self.reports.create(report)
        view = self.workspace().desk
        self.assertTrue(view.output.report_available)
        self.assertEqual(view.state_label, "Результат не визначено")

    def test_workbench_header_uses_same_mapping(self):
        self.setup_projection("INSUFFICIENT", findings=False)
        status = ResearchStatusQueryService(workflow_run_repository=self.run_repo,
            research_run_result_query_service=self.results).get_status("run")
        header = DeskWorkbenchQueryService._header(self.context.workflow_run, self.context.project, status, status.product_outcome.value)
        self.assertEqual(header.state, self.workspace().desk.state_label)
        self.assertNotEqual(header.state_tone, "success")

    def test_conflicting_metadata_remains_unknown_and_read_only(self):
        self.setup_projection()
        stored = self.run_repo.get_task_results("run")
        stored["review"] = {"definition_id": "task-review-report", "shared_state": {
            "research_product_outcome": {"outcome": "PARTIAL"}}}
        stored["report"] = {"definition_id": "task-write-report", "shared_state": {
            "research_product_outcome": {"outcome": "COMPLETED"}}}
        self.run_repo.save(self.context.workflow_run, task_results=stored)
        before = deepcopy(self.run_repo.get_task_results("run"))
        view = self.workspace().desk
        self.assertEqual(view.state_label, "Результат не визначено")
        self.assertEqual(view.output.findings_count, 7)
        status = ResearchStatusQueryService(workflow_run_repository=self.run_repo,
            research_run_result_query_service=self.results).get_status("run")
        self.assertIsNone(status.product_outcome)
        self.assertEqual(self.run_repo.get_task_results("run"), before)
