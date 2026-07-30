from domain.workflow_template import WorkflowTemplate


class WorkflowValidator:
    """
    Проверяет корректность WorkflowTemplate.

    На данном этапе выполняет три проверки:

    - уникальность TaskDefinition.id;
    - существование всех depends_on;
    - отсутствие циклических зависимостей.
    """

    def validate(self, workflow: WorkflowTemplate) -> None:
        self._validate_unique_task_ids(workflow)
        self._validate_dependencies_exist(workflow)
        self._validate_cycles(workflow)

    def _validate_unique_task_ids(self, workflow: WorkflowTemplate) -> None:
        seen: set[str] = set()

        for task in workflow.task_definitions:
            if task.id in seen:
                raise ValueError(f"Duplicate task id: '{task.id}'")

            seen.add(task.id)

    def _validate_dependencies_exist(self, workflow: WorkflowTemplate) -> None:
        task_ids = {task.id for task in workflow.task_definitions}

        for task in workflow.task_definitions:
            for dependency in task.depends_on:
                if dependency not in task_ids:
                    raise ValueError(
                        f"Unknown dependency '{dependency}' in task '{task.id}'"
                    )

    def _validate_cycles(self, workflow: WorkflowTemplate) -> None:
        graph = {
            task.id: task.depends_on
            for task in workflow.task_definitions
        }

        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise ValueError("Workflow contains circular dependencies")

            if node in visited:
                return

            visiting.add(node)

            for dependency in graph[node]:
                visit(dependency)

            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)