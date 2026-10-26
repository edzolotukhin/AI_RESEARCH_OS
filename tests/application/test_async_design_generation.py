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
from domain.task_definition import TaskDefinition
from runtime.workflow_context import WorkflowContext
from application.workflow_kind import WorkflowKind, classify_workflow_template


class _WorkflowService:
    def __init__(self, runs=(), templates=()):
        self.runs = list(runs)
        self.templates = {item.id: item for item in templates}

    def list_workflow_runs_for_project(self, project_id):
        return list(self.runs)

    def get_template(self, template_id):
        return self.templates[template_id]


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

    def test_unresolved_design_schedules_new_attempt_with_same_fingerprint(self):
        project = self._project()
        service = self._service(_Durable())
        project.current_research_design = SimpleNamespace(
            id="unresolved-design",
            research_subject=SimpleNamespace(
                resolution_status=SimpleNamespace(value="unresolved")
            ),
        )
        project.research_design_input_fingerprint = service.input_fingerprint(
            project.research_brief, ("DESK",),
        )

        result = service.schedule_design_generation(project)

        self.assertEqual(result.id, "queued-design")
        self.assertEqual(len(service.durable_workflow.calls), 1)

    def test_design_generation_workflow_is_not_a_desk_activation(self):
        project = self._project()
        fingerprint = ProjectPlanningService.input_fingerprint(
            project.research_brief, ("DESK",),
        )
        design_run = WorkflowRun(
            id="design-run",
            project_id=project.id,
            workflow_template_id=f"project-design:{project.id}:{fingerprint}",
        )
        service = self._service(None, [design_run])

        self.assertEqual(service._desk_runs(project.id), [])
        self.assertIsNone(service._desk_run(project.id))
        self.assertFalse(service._has_any_activation(project.id))

    def _execution_context(self, project):
        fingerprint = ProjectPlanningService.input_fingerprint(
            project.research_brief, ("DESK",),
        )
        return WorkflowContext(
            project=project,
            workflow_run=WorkflowRun(
                id="design-run", project_id=project.id,
                workflow_template_id=f"project-design:{project.id}:{fingerprint}",
            ),
            workflow_template=WorkflowTemplate(
                id=f"project-design:{project.id}:{fingerprint}",
                name="Project design generation",
            ),
        )

    def _executor(self, project, *, planner, projects, other_runs=()):
        context = self._execution_context(project)
        workflows = _WorkflowService([*other_runs, context.workflow_run])
        return DesignGenerationExecutor(
            planner_agent=planner,
            project_service=projects,
            workflow_service=workflows,
        ), context

    def test_duplicate_worker_delivery_after_success_is_noop(self):
        project = self._project()
        fingerprint = ProjectPlanningService.input_fingerprint(
            project.research_brief, ("DESK",),
        )
        project.current_research_design = SimpleNamespace(id="design-1")
        project.research_design_input_fingerprint = fingerprint
        planner = SimpleNamespace(run=lambda context: self.fail("planner must not run"))
        projects = SimpleNamespace(save_project=lambda project: self.fail("save must not run"))
        executor, context = self._executor(
            project, planner=planner, projects=projects,
        )
        context = executor.run(context)
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

        executor, context = self._executor(
            project,
            planner=SimpleNamespace(run=generate_replacement),
            projects=SimpleNamespace(save_project=saves.append),
        )

        context = executor.run(context)

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
        executor, context = self._executor(
            project,
            planner=SimpleNamespace(run=lambda context: SimpleNamespace(
                workflow_template=SimpleNamespace(research_design_snapshot=design),
            )),
            projects=SimpleNamespace(save_project=saves.append),
        )
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
        executor, context = self._executor(
            project, planner=planner,
            projects=SimpleNamespace(save_project=reject_stale_save),
        )
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
        executor, context = self._executor(
            project,
            planner=SimpleNamespace(run=fail_provider),
            projects=SimpleNamespace(save_project=saved.append),
        )
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
        executor, context = self._executor(
            project,
            planner=SimpleNamespace(
                run=lambda context: (_ for _ in ()).throw(
                    ValueError("private generated design body")
                )
            ),
            projects=SimpleNamespace(
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

    def test_changed_method_uses_new_generation_identity(self):
        project = self._project()
        old_fingerprint = ProjectPlanningService.input_fingerprint(
            project.research_brief, ("DESK",),
        )
        old = SimpleNamespace(
            id="old", workflow_template_id=f"project-design:{project.id}:{old_fingerprint}",
            is_terminal=False, status=WorkflowStatus.RUNNING, tasks=[],
        )
        project.selected_methods = ("DESK", "QUANTITATIVE")
        durable = _Durable()

        self._service(durable, [old]).schedule_design_generation(project)

        self.assertNotEqual(durable.calls[0][1].id, old.workflow_template_id)

    def test_newer_same_fingerprint_attempt_blocks_late_old_completion(self):
        project = self._project()
        fingerprint = ProjectPlanningService.input_fingerprint(
            project.research_brief, ("DESK",),
        )
        old_context = self._execution_context(project)
        old_context.workflow_run.id = "attempt-a"
        old_context.workflow_run.tasks = [SimpleNamespace(created_at="2026-01-01T00:00:00Z")]
        newer = WorkflowRun(
            id="attempt-b", project_id=project.id,
            workflow_template_id=f"project-design:{project.id}:{fingerprint}",
        )
        newer.tasks = [SimpleNamespace(created_at="2026-01-02T00:00:00Z")]
        workflows = _WorkflowService([old_context.workflow_run])
        def finish_after_newer_attempt_started(context):
            workflows.runs.append(newer)
            return SimpleNamespace(
                workflow_template=SimpleNamespace(
                    research_design_snapshot=SimpleNamespace(id="stale-design")
                )
            )
        executor = DesignGenerationExecutor(
            planner_agent=SimpleNamespace(run=finish_after_newer_attempt_started),
            project_service=SimpleNamespace(save_project=lambda project: self.fail("must not save")),
            workflow_service=workflows,
        )

        with self.assertRaises(ConcurrentModificationError):
            executor.run(old_context)

        self.assertIsNone(project.current_research_design)

    def test_resolver_selects_latest_same_fingerprint_attempt_and_preserves_history(self):
        project = self._project()
        fingerprint = ProjectPlanningService.input_fingerprint(project.research_brief, ("DESK",))
        first = WorkflowRun(id="attempt-a", project_id=project.id,
                            workflow_template_id=f"project-design:{project.id}:{fingerprint}")
        first.tasks = [SimpleNamespace(created_at="2026-01-01T00:00:00Z")]
        first.ready(); first.start(); first.fail()
        second = WorkflowRun(id="attempt-b", project_id=project.id,
                             workflow_template_id=f"project-design:{project.id}:{fingerprint}")
        second.tasks = [SimpleNamespace(created_at="2026-01-02T00:00:00Z")]
        resolution = self._service(None, [second, first]).resolve_design_generation(project)
        self.assertEqual(resolution.current_attempt.id, "attempt-b")
        self.assertEqual([item.id for item in resolution.historical_attempts], ["attempt-a"])
        self.assertEqual(resolution.state, "active")

    def test_workflow_kind_classifier_does_not_infer_unknown_as_desk(self):
        unknown = WorkflowTemplate(id="unrelated", name="Other")
        desk = WorkflowTemplate(
            id="desk-snapshot", name="Desk",
            task_definitions=[TaskDefinition(str(index), value, value) for index, value in enumerate(
                ("search", "evidence", "research_quality", "analysis", "report", "review", "finalization")
            )],
            research_design_snapshot=SimpleNamespace(id="design"),
        )
        self.assertEqual(classify_workflow_template(unknown), WorkflowKind.UNKNOWN)
        self.assertEqual(classify_workflow_template(desk), WorkflowKind.DESK)

    def test_project_design_and_desk_history_never_cross_selectors(self):
        project = self._project()
        fingerprint = ProjectPlanningService.input_fingerprint(project.research_brief, ("DESK",))
        design_run = WorkflowRun(id="design-attempt", project_id=project.id,
                                 workflow_template_id=f"project-design:{project.id}:{fingerprint}")
        desk_run = WorkflowRun(id="desk-attempt", project_id=project.id,
                               workflow_template_id="desk-template")
        desk_template = WorkflowTemplate(
            id="desk-template", name="Desk",
            task_definitions=[TaskDefinition(str(index), value, value) for index, value in enumerate(
                ("search", "evidence", "research_quality", "analysis", "report", "review", "finalization")
            )],
            research_design_snapshot=SimpleNamespace(id="approved-design"),
        )
        service = ProjectPlanningService(
            project_service=SimpleNamespace(),
            workflow_service=_WorkflowService([design_run, desk_run], [desk_template]),
            planner_agent=SimpleNamespace(), workflow_mapper=SimpleNamespace(),
            agency=SimpleNamespace(), quantitative_ui_service=None,
        )

        self.assertEqual([item.id for item in service._desk_runs(project.id)], ["desk-attempt"])
        self.assertEqual(service.resolve_design_generation(project).current_attempt.id, "design-attempt")

    def test_desk_activation_freezes_exact_current_approved_design(self):
        project = self._project()
        approved = SimpleNamespace(id="approved-current")
        historical = SimpleNamespace(id="historical")
        project.current_research_design = approved
        captured = []
        mapper = SimpleNamespace(from_research_design=lambda design, value: (
            captured.append(design)
            or WorkflowTemplate(
                id="desk-template", name="Desk",
                research_design_snapshot=design,
            )
        ))
        agency = SimpleNamespace(start_research_from_template=lambda value, template, run_id: (
            SimpleNamespace(workflow_run=SimpleNamespace(
                id=run_id, template=template, unrelated_historical=historical,
            ))
        ))
        service = ProjectPlanningService(
            project_service=SimpleNamespace(), workflow_service=_WorkflowService(),
            planner_agent=SimpleNamespace(), workflow_mapper=mapper, agency=agency,
            quantitative_ui_service=None,
        )
        service._require_activation = lambda value, method: None

        run = service._activate_desk_locked(project)

        self.assertEqual(captured, [approved])
        self.assertIs(run.template.research_design_snapshot, approved)


if __name__ == "__main__":
    unittest.main()
