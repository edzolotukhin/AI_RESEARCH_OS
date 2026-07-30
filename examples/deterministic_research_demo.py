"""
Deterministic offline demo of the research workflow runtime.

Builds a WorkflowTemplate, materializes a WorkflowRun, and executes it through
WorkflowEngine with demo-only executors registered in a local AgentRegistry.
No live LLM, network calls, or repository writes.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.contracts.base_executor import BaseExecutor
from application.executor_resolver import ExecutorResolver
from application.runtime.workflow_completion_policy import (
    WorkflowCompletionPolicy,
)
from application.task_executor import TaskExecutor
from application.task_lifecycle_manager import TaskLifecycleManager
from application.task_scheduler import TaskScheduler
from application.workflow_engine import WorkflowEngine

from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.project import Project
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template import WorkflowTemplate
from domain.workflow_template_builder import WorkflowTemplateBuilder

from registry.agent_registry import AgentRegistry
from registry.api_executor_registry import APIExecutorRegistry
from registry.human_executor_registry import HumanExecutorRegistry
from registry.tool_registry import ToolRegistry

from runtime.workflow_context import WorkflowContext


class _DemoExecutor(BaseExecutor):
    """Demo-only executor with stable, deterministic output."""

    def __init__(
        self,
        *,
        task_key: str,
        result_summary: str,
    ) -> None:
        self._task_key = task_key
        self._result_summary = result_summary

    def run(
        self,
        context: WorkflowContext,
    ) -> WorkflowContext:
        task = context.current_task
        task_key = task.definition_id if task is not None else self._task_key

        order = list(context.read_shared("execution_order") or [])
        order.append(task_key)
        context.write_shared("execution_order", order)

        results = dict(context.read_shared("task_results") or {})
        results[task_key] = self._result_summary
        context.write_shared("task_results", results)

        return context


def _register_demo_executors(registry: AgentRegistry) -> None:
    registry.register(
        "demo_collect_sources",
        _DemoExecutor(
            task_key="collect_sources",
            result_summary="Collected 2 source sets",
        ),
    )
    registry.register(
        "demo_analyze_findings",
        _DemoExecutor(
            task_key="analyze_findings",
            result_summary="Awareness stable, loyalty improving",
        ),
    )
    registry.register(
        "demo_build_report",
        _DemoExecutor(
            task_key="build_report",
            result_summary="Report draft ready",
        ),
    )


def _build_template() -> WorkflowTemplate:
    return (
        WorkflowTemplateBuilder(
            id="brand-health-demo",
            name="Brand Health Demo",
        )
        .add_task(
            id="collect_sources",
            name="Collect Sources",
            executor_id="demo_collect_sources",
            executor_type=ExecutorType.AGENT,
        )
        .add_task(
            id="analyze_findings",
            name="Analyze Findings",
            executor_id="demo_analyze_findings",
            depends_on=["collect_sources"],
        )
        .add_task(
            id="build_report",
            name="Build Report",
            executor_id="demo_build_report",
            depends_on=["analyze_findings"],
        )
        .build()
    )


def _build_engine() -> WorkflowEngine:
    agent_registry = AgentRegistry()
    _register_demo_executors(agent_registry)

    resolver = ExecutorResolver(
        agent_registry=agent_registry,
        tool_registry=ToolRegistry(),
        human_registry=HumanExecutorRegistry(),
        api_registry=APIExecutorRegistry(),
    )

    return WorkflowEngine(
        scheduler=TaskScheduler(),
        task_executor=TaskExecutor(
            resolver=resolver,
            lifecycle=TaskLifecycleManager(),
        ),
        completion_policy=WorkflowCompletionPolicy(),
    )


def _print_summary(context: WorkflowContext) -> None:
    run = context.workflow_run
    order = list(context.read_shared("execution_order") or [])
    results = dict(context.read_shared("task_results") or {})

    print("=== Deterministic Research Workflow Demo ===")
    print(f"Workflow status: {run.status.value}")
    print(f"Execution order: {' -> '.join(order)}")

    for task_key in order:
        task = next(item for item in run.tasks if item.definition_id == task_key)
        summary = results.get(task_key, "")
        print(f"Task {task_key}: {task.status.value} — {summary}")

    print("Final: workflow completed")


def main() -> None:
    template = _build_template()
    project = Project(id="demo-project", name="Brand Health Demo")
    workflow_run = WorkflowRunFactory(task_factory=TaskFactory()).create(
        template=template,
        run_id="demo-run-001",
    )

    engine = _build_engine()
    context = engine.execute(
        project=project,
        workflow_template=template,
        workflow_run=workflow_run,
    )

    _print_summary(context)


if __name__ == "__main__":
    main()
