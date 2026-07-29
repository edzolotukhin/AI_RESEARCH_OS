import importlib.util
import inspect
import unittest
from pathlib import Path
from unittest.mock import Mock

from agency.agency import Agency

from application.workflow_engine import WorkflowEngine


class RuntimePipelineTests(unittest.TestCase):

    def test_workflow_run_service_module_removed(self):
        module_path = (
            Path(__file__).resolve().parents[2]
            / "application"
            / "workflow_run_service.py"
        )

        self.assertFalse(module_path.exists())

    def test_workflow_engine_is_single_execution_entry_point(self):
        source = inspect.getsource(WorkflowEngine.execute)

        self.assertIn("WorkflowContext", source)
        self.assertIn("_scheduler", source)
        self.assertIn("_task_executor", source)

    def test_agency_start_research_uses_workflow_engine(self):
        source = inspect.getsource(Agency.start_research)

        self.assertIn("_workflow_run_factory.create", source)
        self.assertIn("_workflow_engine.execute", source)
        self.assertNotIn("WorkflowRunService", source)

    def test_composition_root_builds_single_runtime_pipeline(self):
        source = inspect.getsource(
            importlib.import_module("application.composition_root"),
        )

        self.assertEqual(source.count("TaskScheduler("), 1)
        self.assertEqual(source.count("TaskExecutor("), 1)
        self.assertEqual(source.count("WorkflowEngine("), 1)
        self.assertNotIn("WorkflowRunService", source)

    def test_workflow_engine_execute_returns_workflow_context(self):
        workflow_run = Mock()
        workflow_run.tasks = []
        workflow_run.status = None

        scheduler = Mock()
        scheduler.find_ready_task.return_value = None
        scheduler.has_pending_tasks.return_value = False

        task_executor = Mock()

        engine = WorkflowEngine(
            scheduler=scheduler,
            task_executor=task_executor,
        )

        context = engine.execute(
            project=Mock(),
            workflow_template=Mock(),
            workflow_run=workflow_run,
        )

        self.assertIs(context.workflow_run, workflow_run)
        task_executor.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
