from domain.workflow_template import WorkflowTemplate
from domain.workflow_template_builder import WorkflowTemplateBuilder
from domain.value_objects.executor_type import ExecutorType


class Workflow:
    """
    Public DSL for creating WorkflowTemplate.

    Example:
        workflow = (
            Workflow(
                id="brand_health",
                name="Brand Health"
            )
            .task(
                id="planner",
                name="Planner",
                executor_id="planner"
            )
            .task(
                id="search",
                name="Search",
                executor_id="search",
                depends_on=["planner"]
            )
            .build()
        )
    """

    def __init__(
        self,
        *,
        id: str,
        name: str,
    ) -> None:
        self._builder = WorkflowTemplateBuilder(
            id=id,
            name=name,
        )

    def task(
        self,
        *,
        id: str,
        name: str,
        executor_id: str,
        executor_type: ExecutorType = ExecutorType.AGENT,
        depends_on: list[str] | None = None,
        metadata: dict | None = None,
    ) -> "Workflow":
        self._builder.add_task(
            id=id,
            name=name,
            executor_id=executor_id,
            executor_type=executor_type,
            depends_on=depends_on,
            metadata=metadata,
        )

        return self

    def build(self) -> WorkflowTemplate:
        return self._builder.build()