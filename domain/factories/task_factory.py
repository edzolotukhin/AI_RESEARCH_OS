from uuid import uuid4
from datetime import datetime, UTC

from domain.task import Task
from domain.task_definition import TaskDefinition

from domain.factories.base_factory import BaseFactory


class TaskFactory(BaseFactory):
    """
    Фабрика создания экземпляров Task из TaskDefinition.
    """

    def create(
        self,
        definition: TaskDefinition,
    ) -> Task:

        now = datetime.now(UTC).isoformat()

        return Task(
            id=str(uuid4()),
            definition_id=definition.id,
            name=definition.name,
            executor_id=definition.executor_id,
            depends_on=list(definition.depends_on),
            created_at=now,
            updated_at=now,
        )