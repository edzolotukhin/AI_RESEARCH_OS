from copy import deepcopy
from uuid import uuid4
from pathlib import Path
import shutil
import subprocess

from api.ui.principal import resolve_ui_principal
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.workflow_template import WorkflowTemplate
from tests.api.helpers import ApiTestCase
from tests.helpers.workflow_run_builder import make_workflow_run


class ResearchProductOutcomePageTests(ApiTestCase):
    def test_polling_terminal_unknown_outcome_reloads_instead_of_staying_running(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node runtime required for actual polling script execution")
        script = Path(__file__).resolve().parents[3] / "api/static/desk-workbench.js"
        program = r"""
const fs = require('fs'), vm = require('vm');
let poll, reloads = 0, requests = 0;
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  document: {getElementById: id => id === 'desk-live-root' ? {dataset: {runId: 'synthetic', executionStatus: 'RUNNING'}} : {}},
  window: {setInterval: fn => {poll = fn}, location: {reload: () => {reloads++}}},
  fetch: async () => ++requests === 1 ? {ok: true, json: async () => ({execution_status: 'TERMINAL'})} : {ok: false, status: 409}
});
(async () => {await poll(); if (requests !== 2 || reloads !== 1) process.exit(1)})();
"""
        subprocess.run([node, "-e", program, str(script)], check=True, capture_output=True, text=True, timeout=10)

    def seed(self, *, outcome="INSUFFICIENT"):
        owner = resolve_ui_principal(self.container).principal_id
        project = self.container.project_service.create_project("Перевірка результату", owner_principal_id=owner, selected_methods=("DESK",))
        design = ResearchDesign(id="design", research_questions=(ResearchQuestion("rq", "Питання"),),
            information_needs=(InformationNeed("need", "rq", "Річні спостереження"),))
        template = WorkflowTemplate(str(uuid4()), "Synthetic Desk", (), research_design_snapshot=design)
        self.container.workflow_service.publish_template_snapshot(template, project_id=project.id)
        run = make_workflow_run(run_id=str(uuid4()), template_id=template.id)
        run.project_id = project.id
        run.ready(); run.start(); run.complete()
        repository = self.container.workflow_service._workflow_run_repository
        repository.create(run, project_id=project.id)
        state = {"research_readiness": {"ready_for_analysis": False,
            "blocking_information_need_ids": ["need"],
            "research_question_assessments": [{"information_need_assessments": [{"information_need_id": "need", "status": "missing"}]}]},
            "research_product_outcome": {"outcome": outcome, "authoritative_post_analysis": True}}
        repository.save(run, task_results={"analysis": {"definition_id": "task-analyze", "shared_state": state}})
        return project, run

    def test_workspace_outputs_and_history_show_insufficiency_without_writes_or_ai(self):
        project, run = self.seed()
        before = deepcopy(self.container.workflow_service.get_task_results(run.id))
        workspace = self.client.get(f"/ui/projects/{project.id}")
        self.assertEqual(workspace.status_code, 200)
        self.assertIn("Недостатньо матеріалів", workspace.text)
        self.assertIn("Не підтверджено: Річні спостереження", workspace.text)
        self.assertIn("Історія запусків", workspace.text)
        self.assertIn(f"/ui/research/{run.id}/overview", workspace.text)
        self.assertNotIn("Виконання етапів: 100%", workspace.text)
        self.assertIn("PDF:", workspace.text)
        outputs = self.client.get(f"/ui/projects/{project.id}/outputs")
        self.assertEqual(outputs.status_code, 200)
        self.assertIn("Недостатньо матеріалів", outputs.text)
        self.assertIn("Звіт недоступний", outputs.text)
        self.assertEqual(self.container.workflow_service.get_task_results(run.id), before)
        self.container._test_llm_client.generate.assert_not_called()

    def test_run_overview_shows_same_insufficient_product_state(self):
        project, run = self.seed()
        page = self.client.get(f"/ui/research/{run.id}/overview")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Недостатньо матеріалів", page.text)
        self.assertNotIn("Дослідження завершено; підтримані результати доступні", page.text)
        self.container._test_llm_client.generate.assert_not_called()

    def test_latest_failed_attempt_takes_precedence_on_outputs_while_history_remains(self):
        from application.services.project_planning_service import ProjectPlanningService
        project, previous = self.seed()
        run_id = ProjectPlanningService._desk_retry_run_id(project.id, previous.id)
        run = make_workflow_run(run_id=run_id, template_id=previous.workflow_template_id)
        run.project_id = project.id
        run.ready(); run.start(); run.fail()
        repo = self.container.workflow_service._workflow_run_repository
        repo.create(run, project_id=project.id)
        repo.save(run, task_results={"analysis": {"definition_id": "task-analyze", "shared_state": {
            "research_product_outcome": {"outcome": "FAILED", "authoritative_post_analysis": True}}}})
        page = self.client.get(f"/ui/projects/{project.id}/outputs")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Технічна помилка", page.text)
        self.assertNotIn("Недостатньо матеріалів", page.text)
        history = self.client.get(f"/ui/projects/{project.id}")
        self.assertIn(f"/ui/research/{previous.id}/overview", history.text)
        self.assertIn(f"/ui/research/{run.id}/overview", history.text)
        self.container._test_llm_client.generate.assert_not_called()
