from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_dependency_graph_builder import (
    WorkflowRunDependencyGraphBuilder,
)
from domain.workflow_template import WorkflowTemplate
from domain.workflow_run import WorkflowRun


class WorkflowRunFactory:

    def __init__(
        self,
        task_factory: TaskFactory,
    ):
        self.task_factory = task_factory

    def create(
        self,
        template: WorkflowTemplate,
        run_id: str,
    ) -> WorkflowRun:
        tasks = [
            self.task_factory.create(definition)
            for definition in template.task_definitions
        ]

        dependency_graph = WorkflowRunDependencyGraphBuilder.build_from_template(
            template,
            tasks,
        )

        workflow_run = WorkflowRun(
            id=run_id,
            workflow_template_id=template.id,
            tasks=tasks,
            dependency_graph=dependency_graph,
        )
        workflow_run.validate_dependency_graph()

        return workflow_run
