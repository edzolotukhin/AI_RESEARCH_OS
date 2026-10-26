import unittest
from types import SimpleNamespace

from application.services.project_planning_service import ProjectPlanningService
from application.executors.design_generation_executor import DesignGenerationExecutor
from application.persistence.exceptions import ConcurrentModificationError
from domain.project import Project
from domain.research_brief import ResearchBrief
from domain.workflow_run import WorkflowRun
from domain.workflow_status import WorkflowStatus
from domain.workflow_template import WorkflowTemplate
from runtime.workflow_context import WorkflowContext


class _WorkflowService:
    def __init__(self, runs=()):
        self.runs = list(runs)

    def list_workflow_runs_for_project(self, project_id):
        return list(self.runs)


class _Durable:
    def __init__(self):
        self.calls = []

    def submit_research(self, project, template, *, initial_task_results):
        self.calls.append((project, template, initial_task_results))
        return SimpleNamespace(workflow_run=SimpleNamespace(id="queued-design"))


class AsyncDesignGenerationTests(unittest.TestCase):
    def _service(self, durable, runs=()):
        return ProjectPlanningService(
            project_service=SimpleNamespace(), workflow_service=_WorkflowService(runs),
            planner_agent=SimpleNamespace(), workflow_mapper=SimpleNamespace(),
            agency=SimpleNamespace(), quantitative_ui_service=None,
            durable_workflow_service=durable,
        )

    def _project(self):
        return Project(
            id="project-1", name="Test", selected_methods=("DESK",),
            research_brief=ResearchBrief(title="T", business_question="Q"),
        )

    def test_post_path_only_submits_durable_task(self):
        durable = _Durable()
        result = self._service(durable).schedule_design_generation(self._project())
        self.assertEqual(result.id, "queued-design")
        self.assertEqual(len(durable.calls), 1)
        self.assertEqual(durable.calls[0][1].task_definitions[0].executor_id, "design_generation")

    def test_active_generation_is_reused(self):
        project = self._project()
        service = self._service(None)
        fingerprint = service.input_fingerprint(project.research_brief, ("DESK",))
        active = SimpleNamespace(
            id="active", workflow_template_id=f"project-design:{project.id}:{fingerprint}",
            is_terminal=False, status=WorkflowStatus.RUNNING,
        )
        durable = _Durable()
        result = self._service(durable, [active]).schedule_design_generation(project)
        self.assertIs(result, active)
        self.assertEqual(durable.calls, [])

    def test_completed_design_is_idempotent(self):
        project = self._project()
        service = self._service(_Durable())
        project.current_research_design = SimpleNamespace(research_subject=None)
        project.research_design_input_fingerprint = service.input_fingerprint(
            project.research_brief, ("DESK",)
        )
        self.assertIsNone(service.schedule_design_generation(project))

    def _execution_context(self, project):
        fingerprint = ProjectPlanningService.input_fingerprint(
            project.research_brief, ("DESK",),
        )
        return WorkflowContext(
            project=project,
            workflow_run=WorkflowRun(id="design-run", project_id=project.id),
            workflow_template=WorkflowTemplate(
                id=f"project-design:{project.id}:{fingerprint}",
                name="Project design generation",
            ),
        )

    def test_duplicate_worker_delivery_after_success_is_noop(self):
        project = self._project()
        fingerprint = ProjectPlanningService.input_fingerprint(
            project.research_brief, ("DESK",),
        )
        project.current_research_design = SimpleNamespace(id="design-1")
        project.research_design_input_fingerprint = fingerprint
        planner = SimpleNamespace(run=lambda context: self.fail("planner must not run"))
        projects = SimpleNamespace(save_project=lambda project: self.fail("save must not run"))
        context = DesignGenerationExecutor(
            planner_agent=planner, project_service=projects,
        ).run(self._execution_context(project))
        self.assertEqual(context.read_shared("design_generation")["design_id"], "design-1")

    def test_unresolved_design_same_fingerprint_is_explicitly_regenerated(self):
        project = self._project()
        original_brief = project.research_brief
        fingerprint = ProjectPlanningService.input_fingerprint(
            original_brief, ("DESK",),
        )
        project.current_research_design = SimpleNamespace(
            id="unresolved-design",
            research_subject=SimpleNamespace(
                resolution_status=SimpleNamespace(value="unresolved")
            ),
        )
        project.research_design_input_fingerprint = fingerprint
        replacement = SimpleNamespace(id="replacement-design")
        saves = []

        def generate_replacement(context):
            context.workflow_template = SimpleNamespace(
                research_design_snapshot=replacement
            )
            return context

        executor = DesignGenerationExecutor(
            planner_agent=SimpleNamespace(run=generate_replacement),
            project_service=SimpleNamespace(save_project=saves.append),
        )

        context = executor.run(self._execution_context(project))

        self.assertIs(project.current_research_design, replacement)
        self.assertEqual(project.research_brief, original_brief)
        self.assertEqual(saves, [project])
        self.assertEqual(
            context.read_shared("design_generation")["design_id"],
            "replacement-design",
        )

    def test_worker_success_persists_one_current_design(self):
        project = self._project()
        design = SimpleNamespace(id="generated-design")
        saves = []
        executor = DesignGenerationExecutor(
            planner_agent=SimpleNamespace(run=lambda context: SimpleNamespace(
                workflow_template=SimpleNamespace(research_design_snapshot=design),
            )),
            project_service=SimpleNamespace(save_project=saves.append),
        )
        context = self._execution_context(project)
        executor.run(context)
        self.assertIs(project.current_research_design, design)
        self.assertEqual(saves, [project])
        self.assertEqual(context.read_shared("design_generation")["status"], "completed")

    def test_stale_completion_cannot_cross_optimistic_save_boundary(self):
        project = self._project()
        design = SimpleNamespace(id="generated-design")
        planner = SimpleNamespace(run=lambda context: SimpleNamespace(
            workflow_template=SimpleNamespace(research_design_snapshot=design),
        ))
        def reject_stale_save(project):
            raise ConcurrentModificationError("brief changed concurrently")
        executor = DesignGenerationExecutor(
            planner_agent=planner,
            project_service=SimpleNamespace(save_project=reject_stale_save),
        )
        context = self._execution_context(project)
        with self.assertRaises(ConcurrentModificationError):
            executor.run(context)
        self.assertEqual(
            context.read_shared("design_generation")["category"],
            "other_design_generation_failure",
        )

    def test_provider_failure_leaves_no_completed_design(self):
        project = self._project()
        def fail_provider(context):
            raise RuntimeError("provider boundary failed")
        saved = []
        executor = DesignGenerationExecutor(
            planner_agent=SimpleNamespace(run=fail_provider),
            project_service=SimpleNamespace(save_project=saved.append),
        )
        context = self._execution_context(project)
        with self.assertRaisesRegex(RuntimeError, "provider boundary failed"):
            executor.run(context)
        self.assertIsNone(project.current_research_design)
        self.assertEqual(saved, [])
        self.assertEqual(context.read_shared("design_generation"), {
            "version": 1,
            "status": "failed",
            "category": "provider_model_execution_failure",
            "project_id": "project-1",
            "workflow_run_id": "design-run",
            "input_fingerprint": ProjectPlanningService.input_fingerprint(
                project.research_brief, ("DESK",),
            ),
        })

    def test_generated_design_validation_failure_is_bounded(self):
        project = self._project()
        context = self._execution_context(project)
        executor = DesignGenerationExecutor(
            planner_agent=SimpleNamespace(
                run=lambda context: (_ for _ in ()).throw(
                    ValueError("private generated design body")
                )
            ),
            project_service=SimpleNamespace(
                save_project=lambda project: self.fail("save must not run")
            ),
        )

        with self.assertRaises(ValueError):
            executor.run(context)

        diagnostic = context.read_shared("design_generation")
        self.assertEqual(
            diagnostic["category"], "generated_design_validation_failure"
        )
        self.assertNotIn("private generated design body", str(diagnostic))
        self.assertIsNone(project.current_research_design)

    def test_failed_attempt_is_historical_and_retry_gets_new_run(self):
        project = self._project()
        service = self._service(None)
        fingerprint = service.input_fingerprint(project.research_brief, ("DESK",))
        failed = SimpleNamespace(
            id="failed", workflow_template_id=f"project-design:{project.id}:{fingerprint}",
            is_terminal=True, status=WorkflowStatus.FAILED,
        )
        durable = _Durable()
        retry = self._service(durable, [failed]).schedule_design_generation(project)
        self.assertEqual(retry.id, "queued-design")
        self.assertEqual(len(durable.calls), 1)

    def test_changed_brief_uses_new_generation_identity(self):
        project = self._project()
        service = self._service(None)
        old_fingerprint = service.input_fingerprint(project.research_brief, ("DESK",))
        old = SimpleNamespace(
            id="old", workflow_template_id=f"project-design:{project.id}:{old_fingerprint}",
            is_terminal=False, status=WorkflowStatus.RUNNING,
        )
        project.research_brief = ResearchBrief(title="Changed", business_question="New Q")
        durable = _Durable()
        self._service(durable, [old]).schedule_design_generation(project)
        new_template = durable.calls[0][1]
        self.assertNotEqual(new_template.id, old.workflow_template_id)


if __name__ == "__main__":
    unittest.main()
