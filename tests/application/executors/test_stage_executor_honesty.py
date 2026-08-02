"""Tests for desk-research stage executor honesty (DR-02)."""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import Mock

from application.composition_root import create_application_container
from application.config import ApplicationConfig, ApplicationOverrides
from application.exceptions.capability_not_implemented_error import (
    CapabilityNotImplementedError,
)
from application.executors.evidence_executor import EvidenceExecutor
from application.executors.search_executor import SearchExecutor
from application.executors.stage_executors import (
    DeterministicStageExecutor,
    UnimplementedCapabilityExecutor,
)
from application.services.durable_workflow_service import DurableWorkflowService
from application.task_executor import TaskExecutor
from application.task_lifecycle_manager import TaskLifecycleManager
from application.task_scheduler import TaskScheduler
from application.workflow_engine import WorkflowEngine
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.project import Project
from domain.value_objects.executor_type import ExecutorType
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus
from domain.workflow_template_builder import WorkflowTemplateBuilder

from registry.agent_registry import AgentRegistry
from registry.api_executor_registry import APIExecutorRegistry
from registry.human_executor_registry import HumanExecutorRegistry
from registry.tool_registry import ToolRegistry

from runtime.workflow_context import WorkflowContext

from application.executor_resolver import ExecutorResolver
from application.runtime.workflow_completion_policy import WorkflowCompletionPolicy

from tests.fixtures.research_brief import sample_research_brief
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock


class StageExecutorHonestyTests(unittest.TestCase):
    def test_unimplemented_capability_executor_raises(self) -> None:
        executor = UnimplementedCapabilityExecutor(
            capability="search",
            stage="collect_sources",
        )
        context = WorkflowContext(
            project=Project(id="p1", name="Test"),
            workflow_run=WorkflowRunFactory(task_factory=TaskFactory()).create(
                template=WorkflowTemplateBuilder(id="t1", name="T")
                .add_task(
                    id="task-collect-evidence",
                    name="Collect",
                    executor_id="search",
                    executor_type=ExecutorType.AGENT,
                )
                .build(),
            ),
        )
        context.current_task = context.workflow_run.tasks[0]

        with self.assertRaises(CapabilityNotImplementedError) as ctx:
            executor.run(context)

        self.assertEqual(ctx.exception.capability, "search")
        self.assertEqual(ctx.exception.stage, "collect_sources")

    def test_production_composition_root_registers_search_executor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            container = create_application_container(
                config=ApplicationConfig(
                    projects_root=temp_dir,
                    deterministic_stage_executors=False,
                    search_provider="deterministic",
                    evidence_extractor="deterministic",
                ),
                overrides=ApplicationOverrides(
                    llm_client=create_brief_aligned_llm_mock(),
                ),
            )
            registry = container.agency._agent_loader._executors
            self.assertIsInstance(registry["search"], SearchExecutor)
            self.assertIsInstance(registry["evidence"], EvidenceExecutor)
            self.assertIsInstance(registry["analysis"], UnimplementedCapabilityExecutor)
            self.assertIsInstance(registry["report"], UnimplementedCapabilityExecutor)

    def test_deterministic_stage_executors_only_when_explicitly_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            container = create_application_container(
                config=ApplicationConfig(
                    projects_root=temp_dir,
                    deterministic_stage_executors=True,
                ),
                overrides=ApplicationOverrides(
                    llm_client=create_brief_aligned_llm_mock(),
                ),
            )
            registry = container.agency._agent_loader._executors
            self.assertIsInstance(registry["search"], DeterministicStageExecutor)

    def test_production_pipeline_fails_on_first_unimplemented_stage(self) -> None:
        template = (
            WorkflowTemplateBuilder(id="desk", name="Desk")
            .add_task(
                id="task-collect-evidence",
                name="Collect",
                executor_id="search",
                executor_type=ExecutorType.AGENT,
            )
            .add_task(
                id="task-analyze",
                name="Analyze",
                executor_id="analysis",
                executor_type=ExecutorType.AGENT,
                depends_on=["task-collect-evidence"],
            )
            .build()
        )
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)

        agent_registry = AgentRegistry()
        agent_registry.register(
            "search",
            UnimplementedCapabilityExecutor(
                capability="search",
                stage="collect_sources",
            ),
        )
        agent_registry.register(
            "analysis",
            UnimplementedCapabilityExecutor(
                capability="analysis",
                stage="analyze",
            ),
        )

        resolver = ExecutorResolver(
            agent_registry=agent_registry,
            tool_registry=ToolRegistry(),
            human_registry=HumanExecutorRegistry(),
            api_registry=APIExecutorRegistry(),
        )
        engine = WorkflowEngine(
            scheduler=TaskScheduler(),
            task_executor=TaskExecutor(
                resolver=resolver,
                lifecycle=TaskLifecycleManager(),
            ),
            completion_policy=WorkflowCompletionPolicy(),
        )

        project = Project(id="p1", name="Test")
        project.research_brief = sample_research_brief()

        with self.assertRaises(CapabilityNotImplementedError):
            engine.execute(
                project=project,
                workflow_template=template,
                workflow_run=run,
            )

        self.assertEqual(run.status, WorkflowStatus.FAILED)
        self.assertEqual(run.tasks[0].status, TaskStatus.FAILED)
        self.assertEqual(run.tasks[1].status, TaskStatus.SKIPPED)


if __name__ == "__main__":
    unittest.main()
