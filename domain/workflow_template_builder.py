from domain.task_definition import TaskDefinition
from domain.workflow_template import WorkflowTemplate
from domain.workflow_validator import WorkflowValidator


class WorkflowTemplateBuilder:
    def __init__(
        self,
        *,
        id: str,
        name: str,
    ) -> None:
        self._id = id
        self._name = name
        self._tasks: list[TaskDefinition] = []

    def add_task(
        self,
        *,
        id: str,
        name: str,
        executor_id: str,
        depends_on: list[str] | None = None,
        metadata: dict | None = None,
    ) -> "WorkflowTemplateBuilder":
        self._tasks.append(
            TaskDefinition(
                id=id,
                name=name,
                executor_id=executor_id,
                depends_on=depends_on or [],
                metadata=metadata or {},
            )
        )

        return self

    def build(self) -> WorkflowTemplate:
        workflow = WorkflowTemplate(
            id=self._id,
            name=self._name,
            task_definitions=self._tasks,
        )

        WorkflowValidator().validate(workflow)

        return workflow